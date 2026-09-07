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
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SKILL_ROOT / "config" / "business-modes.json"
RUNTIME_DIRNAME = "runtime"
SEARCH_PLAN_NAME = "search-plan.json"
SOURCE_CACHE_NAME = "source-cache.json"
EVIDENCE_MANIFEST_NAME = "evidence-manifest.json"
RUN_METRICS_NAME = "run-metrics.json"

BUSINESS_MODES = ("briefing", "standard_visit", "strategic_account", "letter")
MODULES = ("institution", "leader", "internal", "strategy", "letter")
TTL_CLASSES = ("institution", "leader", "procurement", "internal")
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
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
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
    return bool(
        text
        and text.casefold() not in UNRESOLVED
        and not re.search(r"\{\{[^{}]+\}\}", text)
    )


def stable_id(value: Any) -> bool:
    return bool(ID_RE.fullmatch(normalized_text(value)))


def normalize_query(value: str) -> str:
    text = normalized_text(value).casefold()
    text = re.sub(r"[\u3000\s]+", " ", text)
    text = re.sub(r"[，。；：、,.!?！？;:()（）\[\]{}<>《》\"'“”‘’]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_locator(locator: str) -> str:
    value = normalized_text(locator)
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise PlanError(f"来源URL无效：{value}：{exc}") from exc
    if not parsed.scheme or not parsed.netloc:
        return value.casefold()
    try:
        host = (parsed.hostname or "").casefold()
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError as exc:
        raise PlanError(f"来源URL端口无效：{value}：{exc}") from exc
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return urlunsplit((parsed.scheme.casefold(), host + port, path, query, ""))


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
    if not isinstance(contract, dict) or not {
        "tenant_id",
        "customer_id",
        "project_id",
    } <= set(contract):
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
        if (
            not isinstance(modules, list)
            or not modules
            or len(set(modules)) != len(modules)
        ):
            raise PlanError(f"profiles.{mode}.modules必须为非空去重数组。")
        if not set(modules + optional) <= set(MODULES) or set(modules) & set(optional):
            raise PlanError(f"profiles.{mode}模块集合无效或重叠。")
        route_required = {
            "visit_prep": "strategy",
            "strategy": "strategy",
            "letter": "letter",
        }[profile["route"]]
        if route_required not in modules:
            raise PlanError(f"profiles.{mode}缺少route必需模块{route_required}。")
        if not set(modules) & {"institution", "leader", "internal"}:
            raise PlanError(f"profiles.{mode}缺少研究载体。")
        query_budget = profile["query_budget"]
        expected_query_keys = {
            "public_max",
            "internal_max",
            "batch_size",
            "parallelism",
        }
        if (
            not isinstance(query_budget, dict)
            or set(query_budget) != expected_query_keys
        ):
            raise PlanError(f"profiles.{mode}.query_budget字段无效。")
        if not all(isinstance(query_budget[key], int) for key in expected_query_keys):
            raise PlanError(f"profiles.{mode}.query_budget必须为整数。")
        if query_budget["public_max"] < 1 or query_budget["internal_max"] < 0:
            raise PlanError(f"profiles.{mode}.query_budget上限无效。")
        if (
            not 1 <= query_budget["batch_size"] <= 10
            or not 1 <= query_budget["parallelism"] <= 8
        ):
            raise PlanError(f"profiles.{mode}.batch_size/parallelism无效。")
        _positive_range(profile["source_budget"], f"profiles.{mode}.source_budget")
        _positive_range(profile["output_pages"], f"profiles.{mode}.output_pages")
        turn = profile["turn_budget"]
        if not isinstance(turn, dict) or set(turn) != {
            "formal_max",
            "questions_per_turn_max",
        }:
            raise PlanError(f"profiles.{mode}.turn_budget字段无效。")
        if (
            not 0 <= turn["formal_max"] <= 3
            or not 1 <= turn["questions_per_turn_max"] <= 3
        ):
            raise PlanError(f"profiles.{mode}.turn_budget范围无效。")
        ttl = profile["ttl_days"]
        if not isinstance(ttl, dict) or set(ttl) != set(TTL_CLASSES):
            raise PlanError(
                f"profiles.{mode}.ttl_days必须细分institution/leader/procurement/internal。"
            )
        if not all(isinstance(ttl[key], int) and ttl[key] > 0 for key in TTL_CLASSES):
            raise PlanError(f"profiles.{mode}.ttl_days必须为正整数。")
        fields = profile["required_business_fields"]
        if (
            not isinstance(fields, list)
            or not fields
            or len(fields) != len(set(fields))
        ):
            raise PlanError(f"profiles.{mode}.required_business_fields无效。")
        auth = profile["authorization_requirements"]
        if not isinstance(auth, dict) or "customer_id" not in auth.get(
            "stable_ids", []
        ):
            raise PlanError(f"profiles.{mode}必须要求稳定customer_id。")
        if set(auth.get("internal_stable_ids", [])) != {
            "tenant_id",
            "customer_id",
            "project_id",
        }:
            raise PlanError(f"profiles.{mode}内部授权必须绑定tenant/customer/project。")
        if auth.get("project_allowlist_required_for_internal") is not True:
            raise PlanError(f"profiles.{mode}内部授权必须要求project allowlist。")
        if auth.get("authorization_expiry_required_for_internal") is not True:
            raise PlanError(f"profiles.{mode}内部授权必须有到期时间。")
        gate = profile["planning_gate"]
        if (
            not isinstance(gate, dict)
            or not gate.get("required")
            or not isinstance(gate.get("conditional"), dict)
        ):
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
            if template.get("scope") not in {
                "customer",
                "alias",
                "person",
                "topic",
                "project",
            }:
                raise PlanError(f"profiles.{mode} query scope无效。")
            if not isinstance(template.get("priority"), int) or not normalized_text(
                template.get("template")
            ):
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
    recipient_status = business_fields.get("recipient_identity_status")
    if recipient_status is not None and recipient_status not in (
        "confirmed",
        "unconfirmed",
        "conflicted",
    ):
        raise PlanError(
            "recipient_identity_status只允许confirmed/unconfirmed/conflicted。"
        )
    recipient_confirmed = is_resolved(recipient) and recipient_status == "confirmed"
    target_resolved = bool(
        [person for person in people if is_resolved(person)]
    ) or is_resolved(business_fields.get("target_contact_level"))
    internal_ids_stable = all(
        stable_id(authorization.get(key))
        for key in ("tenant_id", "customer_id", "project_id")
    )
    checks = {
        "business_fields_complete": all(
            is_resolved(business_fields.get(key)) for key in required_fields
        ),
        "stable_customer_id": stable_id(authorization.get("customer_id")),
        "stable_project_id": stable_id(project_id),
        "route_depth_compatible": (
            profile.get("route"),
            profile.get("depth"),
        )
        in set(EXPECTED_COMPATIBILITY.values()),
        "query_budget_valid": profile["query_budget"]["public_max"] > 0
        and profile["query_budget"]["batch_size"] > 0,
        "output_contract_resolved": profile["output_pages"]["max"]
        >= profile["output_pages"]["min"],
        "target_identity_or_role_resolved": target_resolved,
        "recipient_identity_and_role_confirmed": recipient_confirmed,
        "tenant_customer_project_ids_stable": internal_ids_stable,
        "project_authorized": stable_id(project_id) and project_id in allowed_projects,
        "authorization_current": auth_current,
    }
    if "internal" not in selected_modules:
        checks.update(
            {
                "tenant_customer_project_ids_stable": True,
                "project_authorized": True,
                "authorization_current": True,
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
    checks = _gate_checks(
        profile, selected_modules, business_fields, authorization, people, now
    )
    names = list(profile["planning_gate"]["required"])
    conditionals = profile["planning_gate"]["conditional"]
    for trigger, gate_names in conditionals.items():
        module = trigger.removesuffix("_selected")
        if module in selected_modules:
            names.extend(gate_names)
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
        return [
            {"subject": item, "person": "", "topic": "", "project": ""}
            for item in subjects
            if is_resolved(item)
        ]
    if scope == "alias":
        return [
            {"subject": alias, "person": "", "topic": "", "project": ""}
            for alias in aliases
            if is_resolved(alias)
        ]
    if scope == "person":
        return [
            {"subject": customer_name, "person": person, "topic": "", "project": ""}
            for person in people
            if is_resolved(person)
        ]
    if scope == "topic":
        return [
            {"subject": customer_name, "person": "", "topic": topic, "project": ""}
            for topic in topics
            if is_resolved(topic)
        ]
    if scope == "project":
        return [
            {"subject": customer_name, "person": "", "topic": "", "project": project}
            for project in projects
            if is_resolved(project)
        ]
    return []


def _query_entry(
    channel: str, purpose: str, priority: int, query: str, sequence: int
) -> dict[str, Any]:
    normalized = normalize_query(query)
    cache_key = hashlib.sha256(f"{channel}\n{normalized}".encode()).hexdigest()
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
                template["channel"],
                template["id"],
                template["priority"],
                query,
                sequence,
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


def batch_queries(
    queries: Sequence[Mapping[str, Any]], batch_size: int
) -> list[dict[str, Any]]:
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
    business_fields: Mapping[str, Any] | None = None,
    selected_modules: Sequence[str] | None = None,
    aliases: Sequence[str] = (),
    people: Sequence[str] = (),
    topics: Sequence[str] = (),
    projects: Sequence[str] = (),
    custom_queries: Sequence[str | Mapping[str, Any]] = (),
    config: Mapping[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    if not CONTEXT_RE.fullmatch(context_id):
        raise PlanError("context_id格式无效。")
    if not RUN_RE.fullmatch(run_id):
        raise PlanError("run_id格式无效。")
    effective_config = dict(config or load_config())
    validate_config(effective_config)
    profile = profile_for(business_mode, effective_config)
    modules = list(selected_modules or profile["modules"])
    if (
        not modules
        or len(modules) != len(set(modules))
        or not set(modules) <= set(MODULES)
    ):
        raise PlanError("selected_modules无效。")
    if not set(profile["modules"]) <= set(modules):
        raise PlanError("selected_modules不能移除business_mode默认模块。")
    if not set(modules) <= set(
        profile["modules"] + profile.get("optional_modules", [])
    ):
        raise PlanError("selected_modules包含business_mode未授权模块。")
    now = generated_at or utc_now()
    fields = dict(business_fields or {})
    fields.setdefault("customer_name", customer_name)
    fields.setdefault("organization_scope", organization_scope)
    authorization = {
        "tenant_id": tenant_id,
        "customer_id": customer_id,
        "project_id": project_id,
        "allowed_project_ids": list(allowed_project_ids),
        "authorization_expires_at": authorization_expires_at,
    }
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
    return {
        "schema": "discovery-call-search-plan/v1",
        "context_id": context_id,
        "run_id": run_id,
        "business_mode": business_mode,
        "route": profile["route"],
        "depth": profile["depth"],
        "customer_id": customer_id,
        "organization_scope": organization_scope,
        "selected_modules": modules,
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


@dataclass
class SourceCache:
    path: Path
    ttl_days: Mapping[str, int]
    clock: Callable[[], datetime] = utc_now
    max_entries: int = 5000
    max_bytes: int = 8 * 1024 * 1024
    max_batch: int = 256

    def __post_init__(self) -> None:
        for name in ("max_entries", "max_bytes", "max_batch"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise PlanError(f"{name}必须为正整数。")

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": "discovery-call-source-cache/v1",
            "updated_at": isoformat(self.clock()),
            "entries": {},
        }

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise PlanError("source-cache.json超过字节上限；请显式拆分或清理缓存。")
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PlanError(f"无法读取缓存：{self.path}: {exc}") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema") != "discovery-call-source-cache/v1"
            or not isinstance(value.get("entries"), dict)
        ):
            raise PlanError("source-cache.json结构无效。")
        if len(value["entries"]) > self.max_entries:
            raise PlanError("source-cache.json超过条目上限；请显式拆分或清理缓存。")
        for key, entry in value["entries"].items():
            if not isinstance(entry, dict) or not isinstance(
                entry.get("expires_at"), str
            ):
                raise PlanError(f"source-cache.json条目{key}结构无效。")
            parse_timestamp(entry["expires_at"])
        return value

    def save(self, value: Mapping[str, Any]) -> None:
        if (
            not isinstance(value.get("entries"), dict)
            or len(value["entries"]) > self.max_entries
        ):
            raise PlanError("缓存写入超过条目上限或entries无效。")
        serialized = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        # Match atomic_write_json's text-mode newline translation on Windows.
        encoded = serialized.replace("\n", os.linesep).encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise PlanError("缓存写入超过字节上限；原文件未改变。")
        atomic_write_json(self.path, value)

    def lookup(
        self,
        locator: str,
        *,
        at: datetime | None = None,
        expected_content_sha256: str | None = None,
    ) -> dict[str, Any] | None:
        return self.lookup_many(
            [locator], at=at, expected_content_sha256=expected_content_sha256
        )[0]

    def lookup_many(
        self,
        locators: Sequence[str],
        *,
        at: datetime | None = None,
        expected_content_sha256: str | None = None,
    ) -> list[dict[str, Any] | None]:
        """One bounded disk snapshot per batch; no stale cross-batch memory cache.

        Cache writes are owned by the main flow, not parallel research modules.
        Results preserve input order and cannot mutate the snapshot.
        """
        if isinstance(locators, str) or len(locators) > self.max_batch:
            raise PlanError(f"缓存查询每批最多{self.max_batch}项。")
        now = at or self.clock()
        isoformat(now)
        keys = [
            hashlib.sha256(canonical_locator(locator).encode("utf-8")).hexdigest()
            for locator in locators
        ]
        entries = self.load()["entries"]
        results: list[dict[str, Any] | None] = []
        for key in keys:
            entry = entries.get(key)
            if (
                not entry
                or parse_timestamp(entry["expires_at"]) <= now
                or (
                    expected_content_sha256
                    and entry.get("content_sha256") != expected_content_sha256
                )
            ):
                results.append(None)
            else:
                results.append(copy.deepcopy(entry))
        return results

    def put(
        self,
        locator: str,
        content: str | bytes,
        *,
        ttl_class: str,
        metadata: Mapping[str, Any] | None = None,
        fetched_at: datetime | None = None,
    ) -> dict[str, Any]:
        if ttl_class not in TTL_CLASSES:
            raise PlanError(f"未知ttl_class：{ttl_class}")
        if ttl_class not in self.ttl_days or self.ttl_days[ttl_class] < 1:
            raise PlanError(f"缺少有效TTL：{ttl_class}")
        now = fetched_at or self.clock()
        canonical = canonical_locator(locator)
        key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        payload = content.encode("utf-8") if isinstance(content, str) else content
        digest = hashlib.sha256(payload).hexdigest()
        entry = {
            "cache_key": key,
            "locator": locator,
            "canonical_locator": canonical,
            "source_fingerprint": "sha256:" + digest,
            "content_sha256": digest,
            "fetched_at": isoformat(now),
            "expires_at": isoformat(now + timedelta(days=self.ttl_days[ttl_class])),
            "ttl_class": ttl_class,
            "metadata": dict(metadata or {}),
        }
        cache = self.load()
        # Evict expired entries first; capacity eviction is deterministic by expiry/key.
        # Never silently remove invalid entries: load() validates before this point.
        cache["entries"] = {
            k: v
            for k, v in cache["entries"].items()
            if parse_timestamp(v["expires_at"]) > now
        }
        cache["entries"][key] = entry
        if len(cache["entries"]) > self.max_entries:
            victims = sorted(
                (k for k in cache["entries"] if k != key),
                key=lambda k: (parse_timestamp(cache["entries"][k]["expires_at"]), k),
            )
            for victim in victims[: len(cache["entries"]) - self.max_entries]:
                del cache["entries"][victim]
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
        counters: dict[str, int | None] = dict.fromkeys(self.COUNTERS, 0)
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

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace).resolve()
        self.runtime = self.workspace / RUNTIME_DIRNAME
        self.runtime.mkdir(parents=True, exist_ok=True)

    def materialize(
        self,
        plan: Mapping[str, Any],
        *,
        project_id: str | None = None,
        generated_at: datetime | None = None,
    ) -> dict[str, Path]:
        now = generated_at or parse_timestamp(str(plan["generated_at"]))
        search_path = self.runtime / SEARCH_PLAN_NAME
        cache_path = self.runtime / SOURCE_CACHE_NAME
        evidence_path = self.runtime / EVIDENCE_MANIFEST_NAME
        metrics_path = self.runtime / RUN_METRICS_NAME
        # Check every existing identity before any write. Replanning is not a
        # run migration and must not relabel evidence or reset execution history.
        contracts = (
            (
                search_path,
                "discovery-call-search-plan/v1",
                ("customer_id", "organization_scope"),
            ),
            (evidence_path, "discovery-call-evidence-manifest/v1", ("customer_id",)),
            (metrics_path, "discovery-call-run-metrics/v1", ()),
        )
        existing: dict[Path, dict[str, Any]] = {}
        for path, schema, identity_fields in contracts:
            if not path.exists():
                continue
            value = read_json(path)
            if not isinstance(value, dict) or value.get("schema") != schema:
                raise PlanError(f"既有规划文件schema无效：{path.name}")
            for key in ("context_id", "run_id", "business_mode", *identity_fields):
                if value.get(key) != plan[key]:
                    raise PlanError(
                        f"既有规划文件{path.name}的{key}不一致；禁止覆盖或复用错身份。"
                    )
            existing[path] = value
        if evidence_path in existing:
            evidence = existing[evidence_path]
            if evidence.get("project_id") != project_id:
                raise PlanError(
                    "既有evidence-manifest.json的project_id不一致；禁止覆盖。"
                )
            if any(
                not isinstance(evidence.get(key), dict)
                for key in ("sources", "claims", "query_links", "connector_audit")
            ):
                raise PlanError("既有evidence-manifest.json证据结构无效。")
        if metrics_path in existing:
            counters = existing[metrics_path].get("counters")
            # run-metrics.schema.json: exact keys, nonnegative integers; only tokens may be null.
            if not isinstance(counters, dict) or set(counters) != set(
                RunMetrics.COUNTERS
            ):
                raise PlanError("既有run-metrics.json counters字段无效。")
            for key, count in counters.items():
                if count is None and key in {"input_tokens", "output_tokens"}:
                    continue
                if type(count) is not int or count < 0:
                    raise PlanError(
                        f"既有run-metrics.json counters.{key}必须为非负整数。"
                    )
        if cache_path.exists():
            if not existing:
                raise PlanError(
                    "既有source-cache.json缺少可核对的context/run；禁止猜测复用。"
                )
            SourceCache(cache_path, plan["budgets"]["ttl_days"]).load()
        atomic_write_json(search_path, plan)
        if not cache_path.exists():
            atomic_write_json(
                cache_path,
                {
                    "schema": "discovery-call-source-cache/v1",
                    "updated_at": isoformat(now),
                    "entries": {},
                },
            )
        if evidence_path not in existing:
            self._initialize_evidence(evidence_path, plan, project_id, now)
        if metrics_path not in existing:
            metrics = RunMetrics(
                metrics_path,
                str(plan["context_id"]),
                str(plan["run_id"]),
                str(plan["business_mode"]),
                now,
            )
            metrics.save(metrics.initial(len(plan["queries"])))
        return {
            "search_plan": search_path,
            "source_cache": cache_path,
            "evidence_manifest": evidence_path,
            "run_metrics": metrics_path,
        }

    @staticmethod
    def _initialize_evidence(
        evidence_path: Path,
        plan: Mapping[str, Any],
        project_id: str | None,
        now: datetime,
    ) -> None:
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
                    "status": "not_applicable",
                    "connector_id": None,
                    "call_id": None,
                    "called_at": None,
                    "tenant_id": None,
                    "customer_id": plan["customer_id"],
                    "project_id": project_id,
                    "allowed_project_ids": [],
                    "authorization_owner": None,
                    "authorization_expires_at": None,
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
        manifest["sources"][key] = copy.deepcopy(dict(value))
    for key, value in (claims or {}).items():
        manifest["claims"][key] = copy.deepcopy(dict(value))
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
        fields[key] = content
    return fields


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="离线生成discovery-call机器化研究计划、共享缓存、证据清单和运行指标。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate-config", help="验证business mode配置"
    )
    validate_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    profile_parser = subparsers.add_parser(
        "profile", help="输出一个business mode profile"
    )
    profile_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    profile_parser.add_argument(
        "--business-mode", choices=BUSINESS_MODES, required=True
    )

    plan_parser = subparsers.add_parser("plan", help="生成并持久化离线研究计划")
    plan_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    plan_parser.add_argument("--workspace", type=Path, required=True)
    plan_parser.add_argument("--business-mode", choices=BUSINESS_MODES, required=True)
    plan_parser.add_argument("--context-id", required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--customer-name", required=True)
    plan_parser.add_argument("--customer-id", required=True)
    plan_parser.add_argument("--organization-scope", required=True)
    plan_parser.add_argument("--tenant-id")
    plan_parser.add_argument("--project-id")
    plan_parser.add_argument("--allowed-project-id", action="append", default=[])
    plan_parser.add_argument("--authorization-expires-at")
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
            print(
                json.dumps(
                    {"valid": True, "profiles": list(BUSINESS_MODES)},
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "profile":
            print(
                json.dumps(
                    profile_for(args.business_mode, config),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
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
            business_fields=parse_business_fields(args.business_field),
            selected_modules=args.module,
            aliases=args.alias,
            people=args.person,
            topics=args.topic,
            projects=args.project,
            custom_queries=args.query,
            config=config,
        )
        paths = RuntimeWorkspace(args.workspace).materialize(
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
        if args.require_planning_ready and not plan["planning_ready"]:
            return 1
        return 0
    except (PlanError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
