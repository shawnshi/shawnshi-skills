import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackboard import append_signal
from hub_utils import load_json
from run_contract import RunContractError
from supplement_agent import assemble_result


class RuntimeStabilityTests(unittest.TestCase):
    def test_absent_json_retains_optional_default(self):
        with tempfile.TemporaryDirectory() as directory:
            default = {"optional": True}
            self.assertIs(load_json(Path(directory) / "absent.json", default), default)

    def test_corrupt_json_is_not_empty_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"unfinished":', encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                load_json(path, {})

    def test_read_permission_error_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("{}", encoding="utf-8")
            with patch.object(Path, "read_text", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    load_json(path, {})

    def test_corrupt_blackboard_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blackboard.json"
            path.write_bytes(b'{"signals":[')
            before = path.read_bytes()
            with self.assertRaises(json.JSONDecodeError):
                append_signal({"event_id": "new"}, blackboard_path=path)
            self.assertEqual(path.read_bytes(), before)

    def test_nonobject_requests_have_contract_errors_not_attribute_errors(self):
        from semantic_agent import _load_packet
        from supplement_agent import _load_bound_packet
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            for value in ([], None, True, 1):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value):
                    with self.assertRaises(RunContractError):
                        _load_bound_packet(path, "tech")
                    with self.assertRaises(RunContractError):
                        _load_packet(path)

    def test_nonobject_draft_is_rejected_before_binding_or_broker_io(self):
        for draft in (None, [], "bad", 1):
            with self.subTest(draft=draft), patch("supplement_agent._load_bound_packet") as read:
                with self.assertRaisesRegex(RunContractError, "must be an object"):
                    assemble_result("absent.json", "tech", draft)
                read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
