"""Bind the reviewed adapter to the actual, explicitly selected sync runner.

Runs only when GARMIN_A_SYNC_TEST_PYTHON names a runner interpreter. The child
uses a throw-away token placeholder and mocked transports: no real account,
token, configuration, database or network access.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import sync_health_data as sync

PROGRAM = r'''
import ast, json, pathlib, sys, tempfile, types
from unittest.mock import Mock, patch
import importlib.metadata as metadata
sys.path.insert(0, __SCRIPTS__)
import sync_health_data as sync
from garmindb.download import Download
from garminconnect import Garmin

out = {"versions": {"garmindb": metadata.version("garmindb"),
                    "garminconnect": metadata.version("garminconnect")}}
out["gate"] = sync.SUPPORTED_PACKAGE_VERSIONS
out["pin"] = [r for r in (metadata.requires("garmindb") or [])
              if r.lower().startswith("garminconnect")]

cli = pathlib.Path(sys.executable).parent / "garmindb_cli.py"
tree = ast.parse(cli.read_text(encoding="utf-8"), filename=str(cli))
methods = [m for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GarminDbMain"
           for m in n.body if isinstance(m, ast.FunctionDef) and m.name == "__get_date_and_days"]
out["date_method_count"] = len(methods)
out["date_method_sha256"] = (__import__("hashlib").sha256(
    ast.dump(methods[0], include_attributes=False).encode("utf-8")).hexdigest()
    if len(methods) == 1 else None)

nodes = [n for n in ast.walk(ast.parse(sync._DATE_ADAPTER_CODE))
         if isinstance(n, (ast.FunctionDef, ast.ClassDef))
         and n.name in {"token_only_login", "monitoring_login",
                        "_guard_sync_auth_requests", "_SyncAuthBlocked"}]
nodes.sort(key=lambda n: n.lineno)
ns = {"pathlib": pathlib, "HTTPAdapter": lambda **k: types.SimpleNamespace(**k)}
exec(compile(ast.Module(body=nodes, type_ignores=[]), "<bounded-login>", "exec"), ns)

with tempfile.TemporaryDirectory() as root:
    token = pathlib.Path(root) / "garmin_tokens.json"
    token.write_text("{}", encoding="utf-8")
    config = types.SimpleNamespace(
        get_token_store_file=lambda: str(token),
        get_garmin_base_domain=lambda: "garmin.com",
        get_user=Mock(side_effect=AssertionError("config username read")),
        get_password=Mock(side_effect=AssertionError("config password read")),
        get_fit_files_dir=Mock(side_effect=AssertionError("profile write")),
    )
    downloader = Download(config)
    downloader.garmin.login = types.MethodType(ns["token_only_login"], downloader.garmin)
    with patch.object(Download, "save_json_to_file", side_effect=AssertionError("profile write")) as save, \
            patch.object(type(downloader.garmin).__mro__[0], "login", downloader.garmin.login), \
            patch("garminconnect.client.Client.load") as load, \
            patch("garminconnect.client.Client.connectapi",
                  return_value={"displayName": "synthetic", "fullName": "must-not-retain"}), \
            patch("garminconnect.client.Client.login",
                  side_effect=AssertionError("password login")):
        out["bounded_login_ok"] = ns["monitoring_login"](downloader) is True
        load.assert_called_once_with(str(token))
    out["save_calls"] = save.call_count
    out["display_name"] = downloader.display_name
    out["full_name"] = downloader.full_name

wrapper = Garmin(retry_attempts=0)
native = wrapper.client
native.di_token = "synthetic-placeholder"
native.di_refresh_token = "synthetic-placeholder"
native.di_client_id = "synthetic-placeholder"
for status in (429, 403):
    network = Mock(return_value=types.SimpleNamespace(status_code=status, json=lambda: {}, headers={}))
    native._http_post = network
    ns["_guard_sync_auth_requests"](native)
    try:
        native._refresh_session()
    except ns["_SyncAuthBlocked"] as blocked:
        out["refresh_%d" % status] = [blocked.category, network.call_count]
    else:
        out["refresh_%d" % status] = ["SWALLOWED", network.call_count]
print(json.dumps(out))
'''


class SyncRunnerCompatibilityTests(unittest.TestCase):
    def test_selected_runner_matches_the_bound_pair_and_stops_on_restriction(self):
        interpreter = os.environ.get("GARMIN_A_SYNC_TEST_PYTHON")
        if not interpreter:
            self.skipTest("explicit sync runner interpreter not selected")
        # An explicitly selected but unusable runner is a configuration failure,
        # never a silent skip that would hide drift from CI output.
        self.assertTrue(Path(interpreter).is_file(),
                        "GARMIN_A_SYNC_TEST_PYTHON is set but not a file")
        program = PROGRAM.replace(
            "__SCRIPTS__", json.dumps(str(Path(__file__).parent)))
        with tempfile.TemporaryDirectory() as root:
            result = subprocess.run(
                [interpreter, "-I", "-B", "-c", program], capture_output=True,
                text=True, timeout=60, cwd=root,
                env={"SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                     "PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(data["versions"], data["gate"])
        self.assertEqual(data["pin"], [f"garminconnect=={data['gate']['garminconnect']}"])
        self.assertEqual(data["date_method_count"], 1)
        self.assertEqual(data["date_method_sha256"], sync.UPSTREAM_DATE_METHOD_SHA256)
        self.assertTrue(data["bounded_login_ok"])
        self.assertEqual(data["save_calls"], 0)
        self.assertEqual(data["display_name"], "synthetic")
        self.assertIsNone(data["full_name"])
        self.assertEqual(data["refresh_429"], ["rate_limited", 1])
        self.assertEqual(data["refresh_403"], ["provider_blocked", 1])


if __name__ == "__main__":
    unittest.main()
