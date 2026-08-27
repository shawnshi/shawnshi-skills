#!/usr/bin/env python3
"""Deterministic, offline research planning and runtime audit support.

The script never performs network access.  It turns a business-mode profile and
task inputs into a de-duplicated search queue, batches the queue, and persists
four machine-auditable files under ``<workspace>/runtime``:

* search-plan.json
* source-cache.json
* evidence-manifest.json
* run-metrics.json

``runtime/manifest.json`` is deliberately not read or written here; the
transaction runtime owns that file.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from capability_receipt import CapabilityReceiptError, verify_capability_receipt
except ModuleNotFoundError:
    _capability_path = Path(__file__).with_name("capability_receipt.py")
    _capability_spec = importlib.util.spec_from_file_location("capability_receipt", _capability_path)
    if _capability_spec is None or _capability_spec.loader is None:
        raise RuntimeError(f"无法加载能力收据验证模块：{_capability_path}")
    _capability_module = importlib.util.module_from_spec(_capability_spec)
    sys.modules["capability_receipt"] = _capability_module
    _capability_spec.loader.exec_module(_capability_module)
    CapabilityReceiptError = _capability_module.CapabilityReceiptError
    verify_capability_receipt = _capability_module.verify_capability_receipt


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_ROOT / "config" / "business-modes.json"
RUNTIME_DIRNAME = "runtime"
SEARCH_PLAN_NAME = "search-plan.json"
SOURCE_CACHE_NAME = "source-cache.json"
EVIDENCE_MANIFEST_NAME = "evidence-manifest.json"
RUN_METRICS_NAME = "run-metrics.json"
CANDIDATE_MARKER_NAME = "candidate-receipt.json"

BUSINESS_MODES = ("briefing", "standard_visit", "strategic_account", "letter")
MODULES = ("institution", "leader", "internal", "strategy", "letter")
TTL_CLASSES = ("institution", "leader", "procurement", "internal")
CONTENT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CAPTURE_METHOD_RAW_BYTES = "raw-bytes-v1"
CAPTURE_METHOD_TEXT = "text-nfc-lf-utf8-v1"
CAPTURE_METHODS = (CAPTURE_METHOD_RAW_BYTES, CAPTURE_METHOD_TEXT)
EXPECTED_COMPATIBILITY = {
    "briefing": ("visit_prep", "quick"),
    "standard_visit": ("visit_prep", "standard"),
    "strategic_account": ("strategy", "deep"),
    "letter": ("letter", "standard"),
}
ID_RE = re.compile(r"^[A-Za-z0-9._-]{3,128}$")
CONTEXT_RE = re.compile(r"^dcx-\d{8}-[A-Za-z0-9]{8}$")
RUN_RE = re.compile(r"^dcr-\d{8}T\d{6}-[A-Za-z0-9]{4}$")
UNRESOLVED = {
    "",
    "待确认",
    "未确认",
    "待核实",
    "未核实",
    "待补充",
    "待指定",
    "unknown",
    "none",
    "n/a",
    "na",
}


class PlanError(RuntimeError):
    """Raised when a plan or runtime contract is invalid."""


def _load_preflight_module():
    try:
        import preflight_intake as module

        return module
    except ModuleNotFoundError:
        path = Path(__file__).with_name("preflight_intake.py")
        spec = importlib.util.spec_from_file_location("preflight_intake", path)
        if spec is None or spec.loader is None:
            raise PlanError(f"无法加载intake预检模块：{path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["preflight_intake"] = module
        spec.loader.exec_module(module)
        return module


PREFLIGHT = _load_preflight_module()


def require_ready_intake(
    path_text: str,
    *,
    business_mode: str,
    customer_name: str,
    organization_scope: str,
    now: datetime,
) -> tuple[dict[str, object], dict[str, object]]:
    try:
        payload = PREFLIGHT.load_payload(path_text)
        result = PREFLIGHT.evaluate_intake(payload, now=now)
    except PREFLIGHT.PreflightError as exc:
        raise PlanError(f"intake预检无效：{exc}") from exc
    if result.get("business_mode") != business_mode:
        raise PlanError("intake预检business_mode与研究计划不一致。")
    if result.get("status") != "ready" or result.get("safe_to_initialize_or_search") is not True:
        questions = [
            str(item.get("question", ""))
            for item in result.get("questions", [])
            if isinstance(item, dict) and item.get("question")
        ]
        raise PlanError("intake_preflight_blocked：" + ("；".join(questions) or "关键输入待澄清。"))
    selected = result.get("selected_values", {})
    customer_values = selected.get("customer_name", {}).get("values", []) if isinstance(selected, dict) else []
    scope_values = selected.get("organization_scope", {}).get("values", []) if isinstance(selected, dict) else []
    if customer_values != [normalized_text(customer_name)] or scope_values != [normalized_text(organization_scope)]:
        raise PlanError("intake预检的客户主体或组织范围与研究计划不一致。")
    receipt = {
        "gate_id": result["gate_id"],
        "input_sha256": result["input_sha256"],
        "business_mode": result["business_mode"],
        "evaluated_at": result["evaluated_at"],
        "expires_at": result["expires_at"],
    }
    return receipt, dict(selected)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        raise PlanError("时间必须包含时区。")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanError(f"无效时间：{value}") from exc
    if parsed.tzinfo is None:
        raise PlanError(f"时间缺少时区：{value}")
    return parsed


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(f"无法读取JSON：{path}: {exc}") from exc


def normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def is_resolved(value: Any) -> bool:
    text = normalized_text(value)
    return bool(text and text.casefold() not in UNRESOLVED and not re.search(r"\{\{[^{}]+\}\}", text))


def stable_id(value: Any) -> bool:
    return bool(ID_RE.fullmatch(normalized_text(value)))


def normalize_query(value: str) -> str:
    text = normalized_text(value).casefold()
    text = re.sub(r"[\u3000\s]+", " ", text)
    text = re.sub(r"[，。；：、,.!?！？;:()（）\[\]{}<>《》\"'“”‘’]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonicalize_source_locator(locator: str) -> str:
    """Return a stable locator used for cache identity.

    URL fragments are never sent to an origin and are therefore excluded. Query
    parameters are sorted, repeated slashes are collapsed, and default HTTP(S)
    ports are removed. Non-URL locators retain the legacy case-folded behavior.
    """

    value = normalized_text(locator)
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value.casefold()
    if not parsed.scheme or not parsed.netloc:
        return value.casefold()
    host = (parsed.hostname or "").casefold()
    try:
        parsed_port = parsed.port
    except ValueError:
        return value.casefold()
    default_port = (parsed.scheme.casefold(), parsed_port) in {("http", 80), ("https", 443)}
    port = f":{parsed_port}" if parsed_port and not default_port else ""
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.casefold(), host + port, path, query, ""))


def canonical_locator(locator: str) -> str:
    """Backward-compatible alias for :func:`canonicalize_source_locator`."""

    return canonicalize_source_locator(locator)


def canonicalize_source_content(content: str | bytes | bytearray | memoryview) -> tuple[bytes, str]:
    """Canonicalize captured content without changing its meaning.

    Raw bytes are hashed exactly as retrieved. Text-only tools use a documented
    representation: Unicode NFC, LF line endings, then UTF-8. No whitespace is
    trimmed, so content changes remain observable.
    """

    if isinstance(content, str):
        normalized = unicodedata.normalize("NFC", content).replace("\r\n", "\n").replace("\r", "\n")
        return normalized.encode("utf-8"), CAPTURE_METHOD_TEXT
    if isinstance(content, (bytes, bytearray, memoryview)):
        return bytes(content), CAPTURE_METHOD_RAW_BYTES
    raise PlanError("source snapshot内容必须是文本或字节。")


def capture_source_snapshot(
    locator: str,
    content: str | bytes | bytearray | memoryview,
    *,
    final_url: str | None = None,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    """Capture deterministic, content-derived source fingerprint metadata.

    ``source_fingerprint`` is always the SHA-256 of the canonicalized captured
    content. A URL, title, or caller-supplied digest is never accepted as the
    fingerprint.
    """

    requested = normalized_text(locator)
    resolved = normalized_text(final_url or requested)
    if not requested:
        raise PlanError("source snapshot locator不能为空。")
    if not resolved:
        raise PlanError("source snapshot final_url不能为空。")
    captured_at = retrieved_at or utc_now()
    if captured_at.tzinfo is None:
        raise PlanError("source snapshot retrieved_at必须包含时区。")
    payload, capture_method = canonicalize_source_content(content)
    digest = hashlib.sha256(payload).hexdigest()
    canonical = canonicalize_source_locator(resolved)
    return {
        "locator": requested,
        "final_url": resolved,
        "canonical_locator": canonical,
        "retrieved_at": isoformat(captured_at),
        "capture_method": capture_method,
        "length": len(payload),
        "content_sha256": digest,
        "source_fingerprint": "sha256:" + digest,
    }


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    config = read_json(Path(path))
    validate_config(config)
    return config


def _positive_range(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"min", "max"}:
        raise PlanError(f"{label}必须只包含min/max。")
    if not all(isinstance(value[key], int) for key in ("min", "max")):
        raise PlanError(f"{label}.min/max必须为整数。")
    if value["min"] < 0 or value["max"] < 1 or value["min"] > value["max"]:
        raise PlanError(f"{label}范围无效。")


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != "1.0.0":
        raise PlanError("business mode schema_version必须为1.0.0。")
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(BUSINESS_MODES):
        raise PlanError("profiles必须且只能定义四种business_mode。")
    contract = config.get("authorization_contract")
    if not isinstance(contract, dict) or not {"tenant_id", "customer_id", "project_id"} <= set(contract):
        raise PlanError("authorization_contract缺少稳定tenant/customer/project要求。")
    for identifier in ("tenant_id", "customer_id", "project_id"):
        requirement = contract.get(identifier)
        if not isinstance(requirement, dict) or requirement.get("stable") is not True:
            raise PlanError(f"authorization_contract.{identifier}必须stable=true。")

    for mode in BUSINESS_MODES:
        profile = profiles[mode]
        if not isinstance(profile, dict):
            raise PlanError(f"profiles.{mode}必须为对象。")
        required = {
            "route",
            "depth",
            "modules",
            "query_budget",
            "source_budget",
            "turn_budget",
            "output_pages",
            "ttl_days",
            "required_business_fields",
            "authorization_requirements",
            "planning_gate",
            "query_templates",
        }
        missing = sorted(required - set(profile))
        if missing:
            raise PlanError(f"profiles.{mode}缺少：{', '.join(missing)}")
        if (profile["route"], profile["depth"]) != EXPECTED_COMPATIBILITY[mode]:
            raise PlanError(f"profiles.{mode}的route/depth兼容映射无效。")
        modules = profile["modules"]
        optional = profile.get("optional_modules", [])
        if not isinstance(modules, list) or not modules or len(set(modules)) != len(modules):
            raise PlanError(f"profiles.{mode}.modules必须为非空去重数组。")
        if not set(modules + optional) <= set(MODULES) or set(modules) & set(optional):
            raise PlanError(f"profiles.{mode}模块集合无效或重叠。")
        route_required = {"visit_prep": "strategy", "strategy": "strategy", "letter": "letter"}[profile["route"]]
        if route_required not in modules:
            raise PlanError(f"profiles.{mode}缺少route必需模块{route_required}。")
        if not set(modules) & {"institution", "leader", "internal"}:
            raise PlanError(f"profiles.{mode}缺少研究载体。")
        query_budget = profile["query_budget"]
        expected_query_keys = {"public_max", "internal_max", "batch_size", "parallelism"}
        if not isinstance(query_budget, dict) or set(query_budget) != expected_query_keys:
            raise PlanError(f"profiles.{mode}.query_budget字段无效。")
        if not all(isinstance(query_budget[key], int) for key in expected_query_keys):
            raise PlanError(f"profiles.{mode}.query_budget必须为整数。")
        if query_budget["public_max"] < 1 or query_budget["internal_max"] < 0:
            raise PlanError(f"profiles.{mode}.query_budget上限无效。")
        if not 1 <= query_budget["batch_size"] <= 10 or not 1 <= query_budget["parallelism"] <= 8:
            raise PlanError(f"profiles.{mode}.batch_size/parallelism无效。")
        _positive_range(profile["source_budget"], f"profiles.{mode}.source_budget")
        _positive_range(profile["output_pages"], f"profiles.{mode}.output_pages")
        turn = profile["turn_budget"]
        if not isinstance(turn, dict) or set(turn) != {"formal_max", "questions_per_turn_max"}:
            raise PlanError(f"profiles.{mode}.turn_budget字段无效。")
        if not 0 <= turn["formal_max"] <= 3 or not 1 <= turn["questions_per_turn_max"] <= 3:
            raise PlanError(f"profiles.{mode}.turn_budget范围无效。")
        ttl = profile["ttl_days"]
        if not isinstance(ttl, dict) or set(ttl) != set(TTL_CLASSES):
            raise PlanError(f"profiles.{mode}.ttl_days必须细分institution/leader/procurement/internal。")
        if not all(isinstance(ttl[key], int) and ttl[key] > 0 for key in TTL_CLASSES):
            raise PlanError(f"profiles.{mode}.ttl_days必须为正整数。")
        fields = profile["required_business_fields"]
        if not isinstance(fields, list) or not fields or len(fields) != len(set(fields)):
            raise PlanError(f"profiles.{mode}.required_business_fields无效。")
        auth = profile["authorization_requirements"]
        if not isinstance(auth, dict) or "customer_id" not in auth.get("stable_ids", []):
            raise PlanError(f"profiles.{mode}必须要求稳定customer_id。")
        if set(auth.get("internal_stable_ids", [])) != {"tenant_id", "customer_id", "project_id"}:
            raise PlanError(f"profiles.{mode}内部授权必须绑定tenant/customer/project。")
        if auth.get("project_allowlist_required_for_internal") is not True:
            raise PlanError(f"profiles.{mode}内部授权必须要求project allowlist。")
        if auth.get("authorization_expiry_required_for_internal") is not True:
            raise PlanError(f"profiles.{mode}内部授权必须有到期时间。")
        gate = profile["planning_gate"]
        if not isinstance(gate, dict) or not gate.get("required") or not isinstance(gate.get("conditional"), dict):
            raise PlanError(f"profiles.{mode}.planning_gate无效。")
        templates = profile["query_templates"]
        if not isinstance(templates, list) or not templates:
            raise PlanError(f"profiles.{mode}.query_templates不能为空。")
        ids: set[str] = set()
        for template in templates:
            if not isinstance(template, dict):
                raise PlanError(f"profiles.{mode}.query_templates元素必须为对象。")
            if template.get("id") in ids:
                raise PlanError(f"profiles.{mode}存在重复query template id。")
            ids.add(template.get("id"))
            if template.get("channel") not in {"public", "internal"}:
                raise PlanError(f"profiles.{mode} query channel无效。")
            if template.get("scope") not in {"customer", "alias", "person", "topic", "project"}:
                raise PlanError(f"profiles.{mode} query scope无效。")
            if not isinstance(template.get("priority"), int) or not normalized_text(template.get("template")):
                raise PlanError(f"profiles.{mode} query template无效。")


def profile_for(mode: str, config: Mapping[str, Any]) -> dict[str, Any]:
    if mode not in BUSINESS_MODES:
        raise PlanError(f"未知business_mode：{mode}")
    return copy.deepcopy(config["profiles"][mode])


def _gate_checks(
    profile: Mapping[str, Any],
    selected_modules: Sequence[str],
    business_fields: Mapping[str, Any],
    authorization: Mapping[str, Any],
    people: Sequence[str],
    now: datetime,
) -> dict[str, bool]:
    required_fields = profile["required_business_fields"]
    project_id = authorization.get("project_id")
    allowed_projects = authorization.get("allowed_project_ids") or []
    auth_expiry = authorization.get("authorization_expires_at")
    try:
        auth_current = bool(auth_expiry and parse_timestamp(str(auth_expiry)) > now)
    except PlanError:
        auth_current = False
    recipient = normalized_text(business_fields.get("recipient_role"))
    recipient_confirmed = is_resolved(recipient) and (
        "已确认" in recipient or "confirmed" in recipient.casefold()
    )
    target_resolved = bool([person for person in people if is_resolved(person)]) or is_resolved(
        business_fields.get("target_contact_level")
    )
    internal_ids_stable = all(stable_id(authorization.get(key)) for key in ("tenant_id", "customer_id", "project_id"))
    list_resolved = lambda key: bool(authorization.get(key)) and all(
        is_resolved(value) for value in authorization.get(key, [])
    )
    checks = {
        "business_fields_complete": all(is_resolved(business_fields.get(key)) for key in required_fields),
        "stable_customer_id": stable_id(authorization.get("customer_id")),
        "stable_project_id": stable_id(project_id),
        "route_depth_compatible": (
            profile.get("route"),
            profile.get("depth"),
        ) in set(EXPECTED_COMPATIBILITY.values()),
        "query_budget_valid": profile["query_budget"]["public_max"] > 0
        and profile["query_budget"]["batch_size"] > 0,
        "output_contract_resolved": profile["output_pages"]["max"] >= profile["output_pages"]["min"],
        "target_identity_or_role_resolved": target_resolved,
        "recipient_identity_and_role_confirmed": recipient_confirmed,
        "tenant_customer_project_ids_stable": internal_ids_stable,
        "project_authorized": stable_id(project_id) and project_id in allowed_projects,
        "authorization_current": auth_current,
        "authorization_owner_resolved": is_resolved(authorization.get("authorization_owner")),
        "connector_id_stable": stable_id(authorization.get("connector_id")),
        "authorized_roots_present": list_resolved("authorized_roots"),
        "allowed_dataset_aliases_present": list_resolved("allowed_dataset_aliases"),
        "allowed_confidentiality_present": list_resolved("allowed_confidentiality"),
        "authorization_purpose_resolved": is_resolved(authorization.get("authorization_purpose")),
        "capability_receipt_bound": stable_id(authorization.get("capability_receipt_id")),
        "authorization_actor_id_stable": stable_id(authorization.get("authorization_actor_id")),
        "capability_receipt_verified": authorization.get("capability_receipt_verified") is True,
        "strategy_variant_valid": True,
        "strategic_question_resolved": is_resolved(business_fields.get("strategic_question")),
        "planning_horizon_resolved": is_resolved(business_fields.get("planning_horizon")),
    }
    if "internal" not in selected_modules:
        checks.update(
            {
                "tenant_customer_project_ids_stable": True,
                "project_authorized": True,
                "authorization_current": True,
                "authorization_owner_resolved": True,
                "connector_id_stable": True,
                "authorized_roots_present": True,
                "allowed_dataset_aliases_present": True,
                "allowed_confidentiality_present": True,
                "authorization_purpose_resolved": True,
                "capability_receipt_bound": True,
                "authorization_actor_id_stable": True,
                "capability_receipt_verified": True,
            }
        )
    if "leader" not in selected_modules:
        checks["target_identity_or_role_resolved"] = True
    return checks


def evaluate_planning_gate(
    profile: Mapping[str, Any],
    selected_modules: Sequence[str],
    business_fields: Mapping[str, Any],
    authorization: Mapping[str, Any],
    people: Sequence[str],
    now: datetime,
) -> tuple[bool, dict[str, list[str]]]:
    checks = _gate_checks(profile, selected_modules, business_fields, authorization, people, now)
    names = list(profile["planning_gate"]["required"])
    conditionals = profile["planning_gate"]["conditional"]
    for trigger, gate_names in conditionals.items():
        module = trigger.removesuffix("_selected")
        if module in selected_modules:
            names.extend(gate_names)
    if "internal" in selected_modules:
        names.extend(
            (
                "tenant_customer_project_ids_stable",
                "project_authorized",
                "authorization_current",
                "authorization_owner_resolved",
                "connector_id_stable",
                "authorized_roots_present",
                "allowed_dataset_aliases_present",
                "allowed_confidentiality_present",
                "authorization_purpose_resolved",
                "capability_receipt_bound",
                "authorization_actor_id_stable",
                "capability_receipt_verified",
            )
        )
    strategy_contract = profile.get("strategy_variants")
    if isinstance(strategy_contract, dict):
        variant = normalized_text(business_fields.get("strategy_variant")) or normalized_text(
            strategy_contract.get("default")
        )
        variants = strategy_contract.get("variants", {})
        variant_profile = variants.get(variant) if isinstance(variants, dict) else None
        if not isinstance(variant_profile, dict):
            checks["strategy_variant_valid"] = False
            names.append("strategy_variant_valid")
        else:
            names.append("strategy_variant_valid")
            names.extend(variant_profile.get("planning_gate", []))
            for field in variant_profile.get("required_business_fields", []):
                check_name = f"variant_field:{field}"
                checks[check_name] = is_resolved(business_fields.get(field))
                names.append(check_name)
    names = list(dict.fromkeys(names))
    passed = [name for name in names if checks.get(name, False)]
    failed = [name for name in names if not checks.get(name, False)]
    return not failed, {"passed": passed, "failed": failed}


def _scope_values(
    scope: str,
    customer_name: str,
    aliases: Sequence[str],
    people: Sequence[str],
    topics: Sequence[str],
    projects: Sequence[str],
) -> list[dict[str, str]]:
    if scope == "customer":
        subjects = [customer_name, *aliases]
        return [{"subject": item, "person": "", "topic": "", "project": ""} for item in subjects if is_resolved(item)]
    if scope == "alias":
        return [{"subject": alias, "person": "", "topic": "", "project": ""} for alias in aliases if is_resolved(alias)]
    if scope == "person":
        return [{"subject": customer_name, "person": person, "topic": "", "project": ""} for person in people if is_resolved(person)]
    if scope == "topic":
        return [{"subject": customer_name, "person": "", "topic": topic, "project": ""} for topic in topics if is_resolved(topic)]
    if scope == "project":
        return [{"subject": customer_name, "person": "", "topic": "", "project": project} for project in projects if is_resolved(project)]
    return []


def _query_entry(channel: str, purpose: str, priority: int, query: str, sequence: int) -> dict[str, Any]:
    normalized = normalize_query(query)
    cache_key = hashlib.sha256(f"{channel}\n{normalized}".encode("utf-8")).hexdigest()
    query_id = "QRY-" + cache_key[:12]
    return {
        "query_id": query_id,
        "channel": channel,
        "purpose": purpose,
        "priority": priority,
        "query": normalized_text(query),
        "normalized_query": normalized,
        "cache_key": cache_key,
        "_sequence": sequence,
    }


def build_query_queue(
    profile: Mapping[str, Any],
    customer_name: str,
    *,
    aliases: Sequence[str] = (),
    people: Sequence[str] = (),
    topics: Sequence[str] = (),
    projects: Sequence[str] = (),
    custom_queries: Sequence[str | Mapping[str, Any]] = (),
    selected_modules: Sequence[str] | None = None,
    query_year: int | None = None,
) -> list[dict[str, Any]]:
    if not is_resolved(customer_name):
        raise PlanError("customer_name不能为空或占位。")
    modules = list(selected_modules or profile["modules"])
    candidates: list[dict[str, Any]] = []
    sequence = 0
    for template in profile["query_templates"]:
        if template["channel"] == "internal" and "internal" not in modules:
            continue
        for values in _scope_values(
            template["scope"], customer_name, aliases, people, topics, projects
        ):
            sequence += 1
            values["year"] = str(query_year or utc_now().year)
            try:
                query = template["template"].format(**values)
            except KeyError as exc:
                raise PlanError(f"query template缺少占位字段：{exc}") from exc
            entry = _query_entry(
                template["channel"], template["id"], template["priority"], query, sequence
            )
            if entry["normalized_query"]:
                candidates.append(entry)
    for custom in custom_queries:
        sequence += 1
        if isinstance(custom, str):
            entry = _query_entry("public", "custom", 50, custom, sequence)
        else:
            entry = _query_entry(
                str(custom.get("channel", "public")),
                str(custom.get("purpose", "custom")),
                int(custom.get("priority", 50)),
                str(custom.get("query", "")),
                sequence,
            )
        if entry["channel"] not in {"public", "internal"}:
            raise PlanError("custom query channel只允许public/internal。")
        if entry["channel"] == "internal" and "internal" not in modules:
            continue
        if entry["normalized_query"]:
            candidates.append(entry)

    candidates.sort(key=lambda item: (item["priority"], item["_sequence"]))
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    counts = {"public": 0, "internal": 0}
    limits = {
        "public": profile["query_budget"]["public_max"],
        "internal": profile["query_budget"]["internal_max"],
    }
    for entry in candidates:
        key = (entry["channel"], entry["normalized_query"])
        if key in seen or counts[entry["channel"]] >= limits[entry["channel"]]:
            continue
        seen.add(key)
        counts[entry["channel"]] += 1
        entry = {key: value for key, value in entry.items() if key != "_sequence"}
        deduplicated.append(entry)
    return deduplicated


def batch_queries(queries: Sequence[Mapping[str, Any]], batch_size: int) -> list[dict[str, Any]]:
    if batch_size < 1:
        raise PlanError("batch_size必须大于0。")
    batches: list[dict[str, Any]] = []
    for channel in ("public", "internal"):
        ids = [query["query_id"] for query in queries if query["channel"] == channel]
        for offset in range(0, len(ids), batch_size):
            batches.append(
                {
                    "batch_id": f"BAT-{len(batches) + 1:03d}",
                    "channel": channel,
                    "query_ids": ids[offset : offset + batch_size],
                }
            )
    return batches


def build_search_plan(
    *,
    business_mode: str,
    context_id: str,
    run_id: str,
    customer_name: str,
    customer_id: str,
    organization_scope: str,
    project_id: str | None = None,
    tenant_id: str | None = None,
    allowed_project_ids: Sequence[str] = (),
    authorization_expires_at: str | None = None,
    authorization_owner: str | None = None,
    connector_id: str | None = None,
    authorized_roots: Sequence[str] = (),
    allowed_dataset_aliases: Sequence[str] = (),
    allowed_confidentiality: Sequence[str] = (),
    authorization_purpose: str | None = None,
    capability_receipt_id: str | None = None,
    authorization_actor_id: str | None = None,
    capability_receipt_file: str | os.PathLike[str] | None = None,
    business_fields: Mapping[str, Any] | None = None,
    selected_modules: Sequence[str] | None = None,
    aliases: Sequence[str] = (),
    people: Sequence[str] = (),
    topics: Sequence[str] = (),
    projects: Sequence[str] = (),
    custom_queries: Sequence[str | Mapping[str, Any]] = (),
    config: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
    intake_preflight: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    if not CONTEXT_RE.fullmatch(context_id):
        raise PlanError("context_id格式无效。")
    if not RUN_RE.fullmatch(run_id):
        raise PlanError("run_id格式无效。")
    effective_config = dict(config or load_config())
    validate_config(effective_config)
    profile = profile_for(business_mode, effective_config)
    modules = list(selected_modules or profile["modules"])
    if not modules or len(modules) != len(set(modules)) or not set(modules) <= set(MODULES):
        raise PlanError("selected_modules无效。")
    if not set(profile["modules"]) <= set(modules):
        raise PlanError("selected_modules不能移除business_mode默认模块。")
    if not set(modules) <= set(profile["modules"] + profile.get("optional_modules", [])):
        raise PlanError("selected_modules包含business_mode未授权模块。")
    now = generated_at or utc_now()
    fields = dict(business_fields or {})
    fields.setdefault("customer_name", customer_name)
    fields.setdefault("organization_scope", organization_scope)
    strategy_contract = profile.get("strategy_variants")
    if isinstance(strategy_contract, dict):
        fields.setdefault("strategy_variant", strategy_contract.get("default", ""))
    authorization = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "project_id": project_id,
        "allowed_project_ids": list(allowed_project_ids),
        "authorization_expires_at": authorization_expires_at,
        "authorization_owner": authorization_owner,
        "connector_id": connector_id,
        "authorized_roots": list(authorized_roots),
        "allowed_dataset_aliases": list(allowed_dataset_aliases),
        "allowed_confidentiality": list(allowed_confidentiality),
        "authorization_purpose": authorization_purpose,
        "capability_receipt_id": capability_receipt_id,
        "authorization_actor_id": authorization_actor_id,
        "capability_operation": "internal_read",
        "capability_receipt_verified": False,
        "capability_receipt_issuer": None,
        "capability_receipt_key_id": None,
        "capability_receipt_sha256": None,
        "capability_receipt_verified_at": None,
        "capability_receipt_expires_at": None,
    }
    if "internal" in modules and capability_receipt_file is not None:
        try:
            verified_receipt = verify_capability_receipt(
                capability_receipt_file,
                expected={
                    "receipt_id": capability_receipt_id,
                    "actor_id": authorization_actor_id,
                    "run_id": run_id,
                    "connector_id": connector_id,
                    "operation": "internal_read",
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "project_id": project_id,
                    "allowed_project_ids": list(allowed_project_ids),
                    "authorization_owner": authorization_owner,
                    "authorization_expires_at": authorization_expires_at,
                    "authorized_roots": list(authorized_roots),
                    "allowed_dataset_aliases": list(allowed_dataset_aliases),
                    "allowed_confidentiality": list(allowed_confidentiality),
                    "authorization_purpose": authorization_purpose,
                },
                at=now,
            )
        except CapabilityReceiptError as exc:
            raise PlanError(f"capability_receipt_invalid：{exc}") from exc
        authorization.update(verified_receipt.audit_fields())
    planning_ready, gate_results = evaluate_planning_gate(
        profile, modules, fields, authorization, people, now
    )
    queries = build_query_queue(
        profile,
        customer_name,
        aliases=aliases,
        people=people,
        topics=topics,
        projects=projects,
        custom_queries=custom_queries,
        selected_modules=modules,
        query_year=now.year,
    )
    internal_gate_names = {
        "tenant_customer_project_ids_stable",
        "project_authorized",
        "authorization_current",
        "authorization_owner_resolved",
        "connector_id_stable",
        "authorized_roots_present",
        "allowed_dataset_aliases_present",
        "allowed_confidentiality_present",
        "authorization_purpose_resolved",
        "capability_receipt_bound",
        "authorization_actor_id_stable",
        "capability_receipt_verified",
    }
    internal_queries_suppressed = bool(internal_gate_names & set(gate_results["failed"]))
    if internal_queries_suppressed:
        queries = [query for query in queries if query.get("channel") != "internal"]
    plan = {
        "schema": "discovery-call-search-plan/v1",
        "context_id": context_id,
        "run_id": run_id,
        "business_mode": business_mode,
        "route": profile["route"],
        "depth": profile["depth"],
        "customer_id": customer_id,
        "organization_scope": organization_scope,
        "selected_modules": modules,
        "strategy_variant": fields.get("strategy_variant", "scheduled_visit") if "strategy" in modules else None,
        "authorization_context": {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "project_id": project_id,
            "allowed_project_ids": list(allowed_project_ids),
            "authorization_expires_at": authorization_expires_at,
            "authorization_owner": authorization_owner,
            "connector_id": connector_id,
            "authorized_roots": list(authorized_roots),
            "allowed_dataset_aliases": list(allowed_dataset_aliases),
            "allowed_confidentiality": list(allowed_confidentiality),
            "authorization_purpose": authorization_purpose,
            "capability_receipt_id": capability_receipt_id,
            "authorization_actor_id": authorization_actor_id,
            "capability_operation": authorization["capability_operation"],
            "capability_receipt_verified": authorization["capability_receipt_verified"],
            "capability_receipt_issuer": authorization["capability_receipt_issuer"],
            "capability_receipt_key_id": authorization["capability_receipt_key_id"],
            "capability_receipt_sha256": authorization["capability_receipt_sha256"],
            "capability_receipt_verified_at": authorization["capability_receipt_verified_at"],
            "capability_receipt_expires_at": authorization["capability_receipt_expires_at"],
        },
        "internal_queries_suppressed": internal_queries_suppressed,
        "generated_at": isoformat(now),
        # This is an input gate for beginning research. Final artifact
        # ready_for_use is decided only after evidence, TTL, and human review.
        "planning_ready": planning_ready,
        "gate_results": gate_results,
        "budgets": {
            "query": profile["query_budget"],
            "source": profile["source_budget"],
            "turn": profile["turn_budget"],
            "output_pages": profile["output_pages"],
            "ttl_days": profile["ttl_days"],
        },
        "queries": queries,
        "batches": batch_queries(queries, profile["query_budget"]["batch_size"]),
    }
    if intake_preflight is not None:
        plan["intake_preflight"] = dict(intake_preflight)
    return plan


@dataclass
class SourceCache:
    path: Path
    ttl_days: Mapping[str, int]
    clock: Callable[[], datetime] = utc_now

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": "discovery-call-source-cache/v1",
            "updated_at": isoformat(self.clock()),
            "entries": {},
        }

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        value = read_json(self.path)
        if value.get("schema") != "discovery-call-source-cache/v1" or not isinstance(value.get("entries"), dict):
            raise PlanError("source-cache.json结构无效。")
        # Legacy or tampered entries are safe cache misses. They are pruned from
        # the next write instead of being silently upgraded with invented
        # snapshot metadata.
        value["entries"] = {
            key: entry
            for key, entry in value["entries"].items()
            if self._entry_valid(key, entry)
        }
        return value

    def save(self, value: Mapping[str, Any]) -> None:
        atomic_write_json(self.path, value)

    @staticmethod
    def _entry_valid(key: Any, entry: Any) -> bool:
        if not isinstance(key, str) or not CONTENT_SHA256_RE.fullmatch(key) or not isinstance(entry, dict):
            return False
        required = {
            "cache_key",
            "locator",
            "final_url",
            "canonical_locator",
            "source_fingerprint",
            "content_sha256",
            "retrieved_at",
            "capture_method",
            "length",
            "expires_at",
            "ttl_class",
            "metadata",
        }
        if not required <= set(entry):
            return False
        digest = entry.get("content_sha256")
        canonical = entry.get("canonical_locator")
        if (
            entry.get("cache_key") != key
            or not isinstance(digest, str)
            or not CONTENT_SHA256_RE.fullmatch(digest)
            or entry.get("source_fingerprint") != "sha256:" + digest
            or not isinstance(entry.get("locator"), str)
            or not normalized_text(entry.get("locator"))
            or not isinstance(entry.get("final_url"), str)
            or not normalized_text(entry.get("final_url"))
            or not isinstance(canonical, str)
            or canonical != canonicalize_source_locator(str(entry.get("final_url")))
            or hashlib.sha256(canonical.encode("utf-8")).hexdigest() != key
            or entry.get("capture_method") not in CAPTURE_METHODS
            or isinstance(entry.get("length"), bool)
            or not isinstance(entry.get("length"), int)
            or entry["length"] < 0
            or entry.get("ttl_class") not in TTL_CLASSES
            or not isinstance(entry.get("metadata"), dict)
        ):
            return False
        try:
            retrieved = parse_timestamp(str(entry.get("retrieved_at")))
            expires = parse_timestamp(str(entry.get("expires_at")))
        except PlanError:
            return False
        return expires > retrieved

    def lookup(
        self,
        locator: str,
        *,
        at: datetime | None = None,
        expected_content_sha256: str | None = None,
    ) -> dict[str, Any] | None:
        now = at or self.clock()
        key = hashlib.sha256(canonical_locator(locator).encode("utf-8")).hexdigest()
        entry = self.load()["entries"].get(key)
        if not entry:
            return None
        if parse_timestamp(entry["expires_at"]) <= now:
            return None
        if expected_content_sha256 and entry.get("content_sha256") != expected_content_sha256:
            return None
        return copy.deepcopy(entry)

    def put(
        self,
        locator: str,
        content: str | bytes | bytearray | memoryview,
        *,
        ttl_class: str,
        metadata: Mapping[str, Any] | None = None,
        final_url: str | None = None,
        retrieved_at: datetime | None = None,
        fetched_at: datetime | None = None,
    ) -> dict[str, Any]:
        if ttl_class not in TTL_CLASSES:
            raise PlanError(f"未知ttl_class：{ttl_class}")
        if ttl_class not in self.ttl_days or self.ttl_days[ttl_class] < 1:
            raise PlanError(f"缺少有效TTL：{ttl_class}")
        if retrieved_at is not None and fetched_at is not None and retrieved_at != fetched_at:
            raise PlanError("retrieved_at与兼容参数fetched_at不能冲突。")
        now = retrieved_at or fetched_at or self.clock()
        snapshot = capture_source_snapshot(
            locator,
            content,
            final_url=final_url,
            retrieved_at=now,
        )
        canonical = str(snapshot["canonical_locator"])
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        entry = snapshot | {
            "cache_key": key,
            "expires_at": isoformat(now + timedelta(days=self.ttl_days[ttl_class])),
            "ttl_class": ttl_class,
            "metadata": dict(metadata or {}),
        }
        cache = self.load()
        cache["entries"][key] = entry
        cache["updated_at"] = isoformat(now)
        self.save(cache)
        return copy.deepcopy(entry)


@dataclass
class RunMetrics:
    path: Path
    context_id: str
    run_id: str
    business_mode: str
    started_at: datetime

    COUNTERS = (
        "formal_user_turns",
        "queries_planned",
        "queries_executed",
        "cache_hits",
        "cache_misses",
        "sources_opened",
        "sources_accepted",
        "claims_created",
        "claims_reused",
        "files_persisted",
        "files_delivered",
        "input_tokens",
        "output_tokens",
    )

    def initial(self, planned_queries: int = 0) -> dict[str, Any]:
        counters: dict[str, int | None] = {key: 0 for key in self.COUNTERS}
        counters["input_tokens"] = None
        counters["output_tokens"] = None
        counters["queries_planned"] = planned_queries
        return {
            "schema": "discovery-call-run-metrics/v1",
            "context_id": self.context_id,
            "run_id": self.run_id,
            "business_mode": self.business_mode,
            "started_at": isoformat(self.started_at),
            "ended_at": None,
            "elapsed_ms": None,
            "counters": counters,
        }

    def load(self) -> dict[str, Any]:
        return read_json(self.path)

    def save(self, value: Mapping[str, Any]) -> None:
        atomic_write_json(self.path, value)

    def increment(self, **changes: int) -> dict[str, Any]:
        value = self.load()
        for key, amount in changes.items():
            if key not in self.COUNTERS or not isinstance(amount, int) or amount < 0:
                raise PlanError(f"无效metrics增量：{key}={amount}")
            current = value["counters"].get(key)
            value["counters"][key] = amount if current is None else current + amount
        self.save(value)
        return value

    def finish(
        self,
        *,
        ended_at: datetime | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> dict[str, Any]:
        value = self.load()
        ended = ended_at or utc_now()
        elapsed = max(0, int((ended - self.started_at).total_seconds() * 1000))
        value["ended_at"] = isoformat(ended)
        value["elapsed_ms"] = elapsed
        if input_tokens is not None:
            value["counters"]["input_tokens"] = input_tokens
        if output_tokens is not None:
            value["counters"]["output_tokens"] = output_tokens
        self.save(value)
        return value


class RuntimeWorkspace:
    """Persist planning machine files below workspace/runtime.

    Context/run transactions are owned by ``runtime_tx.py`` and
    ``runtime/manifest.json``.  This class intentionally has no competing state,
    journal, lock, or commit implementation.
    """

    RECEIPT_FIELDS = {
        "schema",
        "context_id",
        "run_id",
        "source_manifest_revision",
        "source_manifest_sha256",
        "source_workspace",
        "candidate_workspace",
        "payload_sha256",
    }

    def __init__(self, workspace: Path | str, *, source_workspace: Path | str):
        supplied = Path(workspace).expanduser()
        source_supplied = Path(source_workspace).expanduser()
        if supplied.is_symlink() or source_supplied.is_symlink():
            raise PlanError("候选或正式workspace不得为符号链接。")
        self.workspace = supplied.resolve()
        self.source_workspace = source_supplied.resolve()
        if self.workspace == self.source_workspace:
            raise PlanError("拒绝直接写正式workspace；候选区必须与source workspace分离。")
        if not self.workspace.is_dir() or not self.source_workspace.is_dir():
            raise PlanError("候选与source workspace都必须是现有普通目录。")
        self.runtime = self.workspace / RUNTIME_DIRNAME
        self._receipt = self._verify_candidate_receipt()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_candidate_receipt(self) -> dict[str, Any]:
        marker_path = self.runtime / CANDIDATE_MARKER_NAME
        candidate_manifest_path = self.runtime / "manifest.json"
        source_manifest_path = self.source_workspace / RUNTIME_DIRNAME / "manifest.json"
        for path, label in (
            (marker_path, "candidate receipt"),
            (candidate_manifest_path, "candidate manifest"),
            (source_manifest_path, "source manifest"),
        ):
            if path.is_symlink() or not path.is_file():
                raise PlanError(f"{label}缺失或不是普通文件。")
        marker = read_json(marker_path)
        if not isinstance(marker, dict) or set(marker) != self.RECEIPT_FIELDS:
            raise PlanError("candidate receipt字段不完整或含未知字段。")
        if marker.get("schema") != "discovery-call-candidate-receipt/v1":
            raise PlanError("candidate receipt schema无效。")
        if Path(str(marker.get("candidate_workspace", ""))).resolve() != self.workspace:
            raise PlanError("candidate receipt未绑定当前候选路径。")
        if Path(str(marker.get("source_workspace", ""))).resolve() != self.source_workspace:
            raise PlanError("candidate receipt未绑定当前source workspace。")
        if not CONTENT_SHA256_RE.fullmatch(str(marker.get("payload_sha256", ""))):
            raise PlanError("candidate receipt payload_sha256无效。")
        source_manifest = read_json(source_manifest_path)
        candidate_manifest = read_json(candidate_manifest_path)
        if self._file_sha256(candidate_manifest_path) != marker.get("payload_sha256"):
            raise PlanError("candidate receipt未绑定当前candidate manifest。")
        source_revision = marker.get("source_manifest_revision")
        if not isinstance(source_revision, int) or isinstance(source_revision, bool) or source_revision < 1:
            raise PlanError("candidate receipt source_manifest_revision无效。")
        if source_manifest.get("transaction_sequence") != source_revision:
            raise PlanError("source manifest revision已变化，必须重建候选。")
        if self._file_sha256(source_manifest_path) != marker.get("source_manifest_sha256"):
            raise PlanError("source manifest SHA-256已变化，必须重建候选。")
        for field in ("context_id", "customer_id", "business_mode"):
            if candidate_manifest.get(field) != source_manifest.get(field):
                raise PlanError(f"candidate/source manifest的{field}不一致。")
        if candidate_manifest.get("context_id") != marker.get("context_id"):
            raise PlanError("candidate receipt context_id不一致。")
        if candidate_manifest.get("latest_run_id") != marker.get("run_id"):
            raise PlanError("candidate receipt run_id不一致。")
        if candidate_manifest.get("transaction_sequence") != source_revision + 1:
            raise PlanError("candidate manifest事务序号未绑定source revision。")
        return marker

    def materialize(
        self,
        plan: Mapping[str, Any],
        *,
        project_id: str | None = None,
        generated_at: datetime | None = None,
    ) -> dict[str, Path]:
        now = generated_at or parse_timestamp(str(plan["generated_at"]))
        if (
            self._receipt.get("context_id") != plan.get("context_id")
            or self._receipt.get("run_id") != plan.get("run_id")
        ):
            raise PlanError("候选收据与研究计划context_id/run_id不一致。")
        candidate_manifest_path = self.runtime / "manifest.json"
        candidate_manifest = read_json(candidate_manifest_path)
        if candidate_manifest.get("business_mode") != plan.get("business_mode"):
            raise PlanError("候选manifest与研究计划business_mode不一致。")
        established_authorization = candidate_manifest.get("authorization")
        plan_authorization = plan.get("authorization_context")
        if not isinstance(established_authorization, dict) or not isinstance(plan_authorization, dict):
            raise PlanError("候选manifest或研究计划authorization结构无效。")
        stable_authorization_fields = (
            "tenant_id",
            "customer_id",
            "project_id",
            "allowed_project_ids",
            "authorization_expires_at",
            "authorization_owner",
            "connector_id",
            "authorized_roots",
            "allowed_dataset_aliases",
            "allowed_confidentiality",
            "authorization_purpose",
        )
        if "internal" in plan.get("selected_modules", []):
            for field in stable_authorization_fields:
                if established_authorization.get(field) != plan_authorization.get(field):
                    raise PlanError(f"研究计划试图改变既有授权范围：{field}。")
            # Receipt lineage is run-scoped.  Replace any older live-run audit
            # fields with the receipt already verified while building this plan.
            candidate_manifest["authorization"] = {
                **established_authorization,
                **plan_authorization,
            }
        search_path = self.runtime / SEARCH_PLAN_NAME
        cache_path = self.runtime / SOURCE_CACHE_NAME
        evidence_path = self.runtime / EVIDENCE_MANIFEST_NAME
        metrics_path = self.runtime / RUN_METRICS_NAME
        atomic_write_json(search_path, plan)
        if not cache_path.exists():
            atomic_write_json(
                cache_path,
                {
                    "schema": "discovery-call-source-cache/v1",
                    "context_id": plan["context_id"],
                    "run_id": plan["run_id"],
                    "business_mode": plan["business_mode"],
                    "updated_at": isoformat(now),
                    "entries": {},
                },
            )
        else:
            cache_payload = read_json(cache_path)
            if cache_payload.get("schema") != "discovery-call-source-cache/v1" or not isinstance(cache_payload.get("entries"), dict):
                raise PlanError("候选source-cache.json结构无效。")
            cache_payload.update(
                {
                    "context_id": plan["context_id"],
                    "run_id": plan["run_id"],
                    "business_mode": plan["business_mode"],
                    "updated_at": isoformat(now),
                }
            )
            atomic_write_json(cache_path, cache_payload)
        atomic_write_json(
            evidence_path,
            {
                "schema": "discovery-call-evidence-manifest/v1",
                "context_id": plan["context_id"],
                "run_id": plan["run_id"],
                "business_mode": plan["business_mode"],
                "customer_id": plan["customer_id"],
                "project_id": project_id,
                "updated_at": isoformat(now),
                "connector_audit": {
                    "status": "not_configured" if "internal" in plan["selected_modules"] else "not_applicable",
                    "connector_id": plan.get("authorization_context", {}).get("connector_id"),
                    "call_id": None,
                    "called_at": None,
                    "tenant_id": plan.get("authorization_context", {}).get("tenant_id"),
                    "customer_id": plan["customer_id"],
                    "project_id": project_id,
                    "allowed_project_ids": plan.get("authorization_context", {}).get("allowed_project_ids", []),
                    "authorization_owner": plan.get("authorization_context", {}).get("authorization_owner"),
                    "authorization_expires_at": plan.get("authorization_context", {}).get("authorization_expires_at"),
                    "authorized_roots": plan.get("authorization_context", {}).get("authorized_roots", []),
                    "allowed_dataset_aliases": plan.get("authorization_context", {}).get("allowed_dataset_aliases", []),
                    "allowed_confidentiality": plan.get("authorization_context", {}).get("allowed_confidentiality", []),
                    "authorization_purpose": plan.get("authorization_context", {}).get("authorization_purpose"),
                    "capability_receipt_id": plan.get("authorization_context", {}).get("capability_receipt_id"),
                    "authorization_actor_id": plan.get("authorization_context", {}).get("authorization_actor_id"),
                    "capability_operation": plan.get("authorization_context", {}).get("capability_operation"),
                    "capability_receipt_verified": plan.get("authorization_context", {}).get("capability_receipt_verified", False),
                    "capability_receipt_issuer": plan.get("authorization_context", {}).get("capability_receipt_issuer"),
                    "capability_receipt_key_id": plan.get("authorization_context", {}).get("capability_receipt_key_id"),
                    "capability_receipt_sha256": plan.get("authorization_context", {}).get("capability_receipt_sha256"),
                    "capability_receipt_verified_at": plan.get("authorization_context", {}).get("capability_receipt_verified_at"),
                    "capability_receipt_expires_at": plan.get("authorization_context", {}).get("capability_receipt_expires_at"),
                    "server_filter_verified": False,
                    "response_scope_verified": False,
                    "response_fingerprint": None,
                    "isolated_record_count": 0,
                },
                "sources": {},
                "claims": {},
                "query_links": {},
            },
        )
        metrics = RunMetrics(
            metrics_path,
            str(plan["context_id"]),
            str(plan["run_id"]),
            str(plan["business_mode"]),
            now,
        )
        metrics.save(metrics.initial(len(plan["queries"])))
        runtime_files: dict[str, dict[str, object]] = {}
        for path in (search_path, cache_path, evidence_path, metrics_path):
            payload = read_json(path)
            runtime_files[path.name] = {
                "path": f"runtime/{path.name}",
                "sha256": self._file_sha256(path),
                "schema": payload.get("schema", ""),
                "context_id": payload.get("context_id", ""),
                "run_id": payload.get("run_id", ""),
            }
        candidate_manifest["runtime_files"] = runtime_files
        candidate_manifest["evidence_run_id"] = str(plan["run_id"])
        candidate_manifest["updated_at"] = isoformat(now)
        atomic_write_json(candidate_manifest_path, candidate_manifest)
        refreshed_receipt = dict(self._receipt)
        refreshed_receipt["payload_sha256"] = self._file_sha256(candidate_manifest_path)
        atomic_write_json(self.runtime / CANDIDATE_MARKER_NAME, refreshed_receipt)
        self._receipt = refreshed_receipt
        return {
            "search_plan": search_path,
            "source_cache": cache_path,
            "evidence_manifest": evidence_path,
            "run_metrics": metrics_path,
        }

def validate_evidence_source_record(source_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(value))
    required = {
        "source_id", "locator", "canonical_locator", "final_url", "cache_key",
        "source_fingerprint", "content_sha256", "retrieved_at", "capture_method", "length",
    }
    missing = sorted(required - set(record))
    if missing:
        raise PlanError(f"{source_id}机器来源记录缺少：{', '.join(missing)}")
    digest = record.get("content_sha256")
    if record.get("source_id") != source_id or not isinstance(digest, str) or not CONTENT_SHA256_RE.fullmatch(digest):
        raise PlanError(f"{source_id}机器来源ID或content_sha256无效。")
    if record.get("source_fingerprint") != f"sha256:{digest}":
        raise PlanError(f"{source_id}.source_fingerprint必须由内容SHA-256生成。")
    if record.get("capture_method") not in CAPTURE_METHODS or not isinstance(record.get("length"), int) or isinstance(record.get("length"), bool) or record["length"] < 0:
        raise PlanError(f"{source_id}捕获方法或长度无效。")
    parse_timestamp(str(record.get("retrieved_at", "")))
    return record


def validate_evidence_claim_record(
    claim_id: str,
    value: Mapping[str, Any],
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    record = copy.deepcopy(dict(value))
    required = {
        "claim_id", "information_type", "ttl_class", "evidence_anchor_at", "date_basis",
        "verified_at", "ttl_days", "expires_at", "verification_status", "supporting_source_ids",
    }
    missing = sorted(required - set(record))
    if missing:
        raise PlanError(f"{claim_id}机器主张记录缺少：{', '.join(missing)}")
    if record.get("claim_id") != claim_id or record.get("information_type") != record.get("ttl_class") or record.get("ttl_class") not in TTL_CLASSES:
        raise PlanError(f"{claim_id}信息类型或TTL分类无效。")
    ttl_days = record.get("ttl_days")
    if not isinstance(ttl_days, int) or isinstance(ttl_days, bool) or ttl_days < 1:
        raise PlanError(f"{claim_id}.ttl_days无效。")
    anchor = parse_timestamp(str(record.get("evidence_anchor_at", "")))
    verified = parse_timestamp(str(record.get("verified_at", "")))
    expires = parse_timestamp(str(record.get("expires_at", "")))
    if anchor > verified:
        raise PlanError(f"{claim_id}.evidence_anchor_at不得晚于verified_at。")
    if verified > (at or utc_now()):
        raise PlanError(f"{claim_id}.verified_at不得位于未来。")
    if expires > anchor + timedelta(days=ttl_days):
        raise PlanError(f"{claim_id}.expires_at不得晚于evidence_anchor_at+ttl_days。")
    if expires <= anchor:
        raise PlanError(f"{claim_id}.expires_at必须晚于evidence_anchor_at。")
    source_ids = record.get("supporting_source_ids")
    if not isinstance(source_ids, list) or not source_ids or len(source_ids) != len(set(source_ids)):
        raise PlanError(f"{claim_id}.supporting_source_ids必须是非空去重数组。")
    return record


def update_evidence_manifest(
    path: Path | str,
    *,
    sources: Mapping[str, Mapping[str, Any]] | None = None,
    claims: Mapping[str, Mapping[str, Any]] | None = None,
    query_links: Mapping[str, Sequence[str]] | None = None,
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    target = Path(path)
    manifest = read_json(target)
    if manifest.get("schema") != "discovery-call-evidence-manifest/v1":
        raise PlanError("evidence-manifest.json schema无效。")
    for key, value in (sources or {}).items():
        manifest["sources"][key] = validate_evidence_source_record(key, value)
    validation_time = updated_at or utc_now()
    for key, value in (claims or {}).items():
        manifest["claims"][key] = validate_evidence_claim_record(key, value, at=validation_time)
    for key, value in (query_links or {}).items():
        manifest["query_links"][key] = list(dict.fromkeys(value))
    manifest["updated_at"] = isoformat(updated_at or utc_now())
    atomic_write_json(target, manifest)
    return manifest


def parse_business_fields(values: Sequence[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for value in values:
        key, separator, content = value.partition("=")
        if not separator or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise PlanError(f"--business-field须为key=value：{value}")
        if key in fields:
            raise PlanError(f"--business-field重复：{key}")
        fields[key] = content
    return fields


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="离线生成discovery-call机器化研究计划、共享缓存、证据清单和运行指标。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate-config", help="验证business mode配置")
    validate_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    profile_parser = subparsers.add_parser("profile", help="输出一个business mode profile")
    profile_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    profile_parser.add_argument("--business-mode", choices=BUSINESS_MODES, required=True)

    plan_parser = subparsers.add_parser("plan", help="生成并持久化离线研究计划")
    plan_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    plan_parser.add_argument("--workspace", type=Path, required=True)
    plan_parser.add_argument(
        "--source-workspace",
        type=Path,
        required=True,
        help="build_candidate.py收据绑定的正式source workspace；不得与--workspace相同",
    )
    plan_parser.add_argument("--business-mode", choices=BUSINESS_MODES, required=True)
    plan_parser.add_argument("--context-id", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--customer-name", required=True)
    plan_parser.add_argument("--customer-id", required=True)
    plan_parser.add_argument("--organization-scope", required=True)
    plan_parser.add_argument(
        "--intake-input",
        required=True,
        help="结构化intake JSON；规划器会在创建runtime目录前重新计算门禁",
    )
    plan_parser.add_argument("--tenant-id")
    plan_parser.add_argument("--project-id")
    plan_parser.add_argument("--allowed-project-id", action="append", default=[])
    plan_parser.add_argument("--authorization-expires-at")
    plan_parser.add_argument("--authorization-owner")
    plan_parser.add_argument("--connector-id")
    plan_parser.add_argument("--authorized-root", action="append", default=[])
    plan_parser.add_argument("--allowed-dataset-alias", action="append", default=[])
    plan_parser.add_argument("--allowed-confidentiality", action="append", default=[])
    plan_parser.add_argument("--authorization-purpose")
    plan_parser.add_argument("--capability-receipt-id")
    plan_parser.add_argument("--authorization-actor-id", help="宿主认证的当前运行真人稳定actor_id")
    plan_parser.add_argument(
        "--capability-receipt-file",
        help="宿主签发的Ed25519能力收据普通文件；文件本身不会写入workspace",
    )
    plan_parser.add_argument("--module", action="append")
    plan_parser.add_argument("--alias", action="append", default=[])
    plan_parser.add_argument("--person", action="append", default=[])
    plan_parser.add_argument("--topic", action="append", default=[])
    plan_parser.add_argument("--project", action="append", default=[])
    plan_parser.add_argument("--query", action="append", default=[])
    plan_parser.add_argument("--business-field", action="append", default=[])
    plan_parser.add_argument(
        "--require-planning-ready",
        "--require-ready",
        dest="require_planning_ready",
        action="store_true",
        help="要求研究计划输入门禁通过；不表示最终成果ready_for_use",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        config = load_config(args.config)
        if args.command == "validate-config":
            print(json.dumps({"valid": True, "profiles": list(BUSINESS_MODES)}, ensure_ascii=False))
            return 0
        if args.command == "profile":
            print(json.dumps(profile_for(args.business_mode, config), ensure_ascii=False, indent=2))
            return 0
        planned_at = utc_now()
        intake_preflight, intake_values = require_ready_intake(
            args.intake_input,
            business_mode=args.business_mode,
            customer_name=args.customer_name,
            organization_scope=args.organization_scope,
            now=planned_at,
        )
        business_fields = parse_business_fields(args.business_field)
        for field, record in intake_values.items():
            if not isinstance(record, dict):
                continue
            values = record.get("values", [])
            if len(values) != 1 or not isinstance(values[0], str):
                continue
            if field in business_fields and normalized_text(business_fields[field]) != normalized_text(values[0]):
                raise PlanError(f"intake预检中的{field}与--business-field不一致。")
            if field not in {"customer_name", "organization_scope", "target_person", "target_role", "meeting_time"}:
                business_fields.setdefault(field, values[0])
        target_values = []
        for field in ("target_contact_level", "target_role", "target_person"):
            record = intake_values.get(field, {})
            values = record.get("values", []) if isinstance(record, dict) else []
            if len(values) == 1 and isinstance(values[0], str):
                target_values.append(values[0])
        if "target_contact_level" in business_fields and target_values and normalized_text(business_fields["target_contact_level"]) not in {normalized_text(value) for value in target_values}:
            raise PlanError("intake预检中的拜访对象与target_contact_level不一致。")
        if target_values:
            business_fields.setdefault("target_contact_level", target_values[0])
        intake_people = {
            normalized_text(value)
            for field in ("target_person",)
            for record in [intake_values.get(field, {})]
            for value in (record.get("values", []) if isinstance(record, dict) else [])
            if isinstance(value, str)
        }
        if args.person and not intake_people:
            raise PlanError("--person必须先由intake预检确认target_person；不得从角色或层级自行补造姓名。")
        if intake_people and any(normalized_text(person) not in intake_people for person in args.person):
            raise PlanError("--person与intake预检确认的目标人物不一致。")
        project_record = intake_values.get("project_id", {})
        project_values = project_record.get("values", []) if isinstance(project_record, dict) else []
        if project_record:
            if project_values != [args.project_id] and args.project_id:
                raise PlanError("--project-id与intake预检确认的项目范围不一致。")
            if len(project_values) == 1 and isinstance(project_values[0], str):
                args.project_id = args.project_id or project_values[0]
        elif args.project_id:
            raise PlanError("--project-id必须先写入同一份intake并通过预检。")
        plan = build_search_plan(
            business_mode=args.business_mode,
            context_id=args.context_id,
            run_id=args.run_id,
            customer_name=args.customer_name,
            customer_id=args.customer_id,
            organization_scope=args.organization_scope,
            project_id=args.project_id,
            tenant_id=args.tenant_id,
            allowed_project_ids=args.allowed_project_id,
            authorization_expires_at=args.authorization_expires_at,
            authorization_owner=args.authorization_owner,
            connector_id=args.connector_id,
            authorized_roots=args.authorized_root,
            allowed_dataset_aliases=args.allowed_dataset_alias,
            allowed_confidentiality=args.allowed_confidentiality,
            authorization_purpose=args.authorization_purpose,
            capability_receipt_id=args.capability_receipt_id,
            authorization_actor_id=args.authorization_actor_id,
            capability_receipt_file=args.capability_receipt_file,
            business_fields=business_fields,
            selected_modules=args.module,
            aliases=args.alias,
            people=args.person,
            topics=args.topic,
            projects=args.project,
            custom_queries=args.query,
            config=config,
            generated_at=planned_at,
            intake_preflight=intake_preflight,
        )
        if args.require_planning_ready and not plan["planning_ready"]:
            print(
                json.dumps(
                    {
                        "planning_ready": False,
                        "failed_gates": plan["gate_results"]["failed"],
                        "paths": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        paths = RuntimeWorkspace(
            args.workspace,
            source_workspace=args.source_workspace,
        ).materialize(
            plan, project_id=args.project_id
        )
        payload = {
            "planning_ready": plan["planning_ready"],
            "failed_gates": plan["gate_results"]["failed"],
            "queries": len(plan["queries"]),
            "batches": len(plan["batches"]),
            "paths": {key: str(value) for key, value in paths.items()},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (PlanError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
