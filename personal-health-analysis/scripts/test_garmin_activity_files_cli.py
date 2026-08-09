import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from garmin_capabilities import issue_capability, require_capability


SCRIPT_PATH = Path(__file__).with_name("garmin_activity_files.py")
# Independent known FIT-integrity vector derived from Garmin's published CRC
# algorithm: 14-byte header, three data bytes, and a two-byte file CRC.
VALID_FIT = bytes.fromhex("0e200000030000002e464954dc9001020310a1")


def load_module():
    auth_stub = types.SimpleNamespace(
        get_client=Mock(side_effect=AssertionError("network client must not load"))
    )
    with (
        patch.dict(sys.modules, {"garmin_auth": auth_stub}),
        patch.object(Path, "mkdir") as mkdir,
    ):
        spec = importlib.util.spec_from_file_location(
            "garmin_activity_files_under_test", SCRIPT_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, mkdir


class GarminActivityFilesCliTests(unittest.TestCase):
    def setUp(self):
        self.module, self.import_mkdir = load_module()

    def run_main(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = self.module.main(argv)
        return exit_code, json.loads(stdout.getvalue())

    def test_module_import_does_not_create_directories(self):
        self.import_mkdir.assert_not_called()

    def test_local_parse_never_initializes_network_client(self):
        with (
            patch.object(self.module, "_get_client") as get_client,
            patch.object(
                self.module,
                "parse_gpx_file",
                return_value={"points": [], "total_points": 0},
            ),
        ):
            exit_code, payload = self.run_main(["parse", "--file", "sample.gpx"])
        self.assertEqual(exit_code, self.module.EXIT_OK)
        self.assertEqual(payload["total_points"], 0)
        get_client.assert_not_called()

    def test_download_requires_network_authorization_and_explicit_output(self):
        with patch.object(self.module, "_get_client") as get_client:
            exit_code, payload = self.run_main(
                ["download", "--activity-id", "123", "--output-dir", "activity-out"]
            )
            self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
            self.assertEqual(payload["status"], "network_authorization_required")
            get_client.assert_not_called()

            exit_code, payload = self.run_main(
                ["download", "--activity-id", "123", "--allow-network"]
            )
            self.assertEqual(exit_code, self.module.EXIT_AUTHORIZATION)
            self.assertEqual(payload["status"], "health_data_authorization_required")
            get_client.assert_not_called()

    def test_download_rejects_report_archive(self):
        with tempfile.TemporaryDirectory() as temp_root:
            report_dir = Path(temp_root) / "reports"
            with (
                patch.dict(
                    os.environ, {"GARMIN_REPORT_DIR": str(report_dir)}, clear=True
                ),
                patch.object(self.module, "_get_client") as get_client,
            ):
                exit_code, payload = self.run_main(
                    [
                        "download",
                        "--activity-id",
                        "123",
                        "--allow-network",
                        "--allow-health-data",
                        "--allow-download",
                        "--output-dir",
                        str(report_dir),
                    ]
                )
            self.assertEqual(exit_code, self.module.EXIT_USAGE)
            self.assertEqual(payload["error"], "report_directory_forbidden")
            get_client.assert_not_called()

    def test_direct_download_requires_both_explicit_capabilities(self):
        with tempfile.TemporaryDirectory() as temp_root:
            output_dir = Path(temp_root) / "raw-activity"
            client = Mock()

            denied_network = self.module.download_activity_file(
                client, 123, "fit", output_dir
            )
            self.assertEqual(
                denied_network["error"], "network_authorization_required"
            )
            client.download_activity.assert_not_called()
            self.assertFalse(output_dir.exists())

            request = {
                "activity_id": 123,
                "format": "fit",
                "output_dir": str(output_dir.resolve()),
            }
            denied_download = self.module.download_activity_file(
                client,
                123,
                "fit",
                output_dir,
                network_capability=issue_capability(
                    scope="network", operation="activity_download", request=request
                ),
                health_data_capability=issue_capability(
                    scope="health_data", operation="activity_download", request=request
                ),
                request=request,
            )
            self.assertEqual(
                denied_download["error"], "download_authorization_required"
            )
            client.download_activity.assert_not_called()
            self.assertFalse(output_dir.exists())

            client.ActivityDownloadFormat = types.SimpleNamespace(
                ORIGINAL="original",
                GPX="gpx",
                TCX="tcx",
            )
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as zipped:
                zipped.writestr("synthetic.fit", VALID_FIT)
            client.download_activity.return_value = archive.getvalue()
            allowed = self.module.download_activity_file(
                client,
                123,
                "fit",
                output_dir,
                network_capability=issue_capability(
                    scope="network", operation="activity_download", request=request
                ),
                health_data_capability=issue_capability(
                    scope="health_data", operation="activity_download", request=request
                ),
                download_capability=issue_capability(
                    scope="download", operation="activity_download", request=request
                ),
                request=request,
            )
            self.assertNotIn("error", allowed)
            downloaded = Path(allowed["file"])
            self.assertEqual(downloaded.read_bytes(), VALID_FIT)
            client.download_activity.assert_called_once_with(
                123,
                dl_fmt="original",
            )

    def test_direct_client_initialization_requires_both_capabilities(self):
        auth_client = object()
        auth_stub = types.SimpleNamespace(get_client=Mock(return_value=auth_client))
        with patch.dict(sys.modules, {"garmin_auth": auth_stub}):
            with self.assertRaisesRegex(PermissionError, "network_authorization_required"):
                self.module._get_client()
            auth_stub.get_client.assert_not_called()

            network_capability = issue_capability(
                scope="network", operation="activity_download"
            )
            with self.assertRaisesRegex(PermissionError, "health_data_authorization_required"):
                self.module._get_client(network_capability=network_capability)
            auth_stub.get_client.assert_not_called()

            health_data_capability = issue_capability(
                scope="health_data", operation="activity_download"
            )
            download_capability = issue_capability(
                scope="download", operation="activity_download"
            )
            self.assertIs(
                self.module._get_client(
                    network_capability=network_capability,
                    health_data_capability=health_data_capability,
                    download_capability=download_capability,
                ),
                auth_client,
            )
            auth_stub.get_client.assert_called_once_with(
                network_capability=network_capability,
                operation="activity_download",
                request=None,
            )

            with self.assertRaisesRegex(PermissionError, "network_authorization_required"):
                self.module._get_client(
                    network_capability=True,
                    health_data_capability=health_data_capability,
                    download_capability=download_capability,
                )

    def test_original_zip_requires_one_safe_fit_member(self):
        unsafe = io.BytesIO()
        with zipfile.ZipFile(unsafe, "w") as zipped:
            zipped.writestr("../escape.fit", b"fit")
        with self.assertRaisesRegex(ValueError, "activity_archive_unsafe_path"):
            self.module._extract_single_fit(unsafe.getvalue())

        multiple = io.BytesIO()
        with zipfile.ZipFile(multiple, "w") as zipped:
            zipped.writestr("one.fit", b"one")
            zipped.writestr("two.fit", b"two")
        with self.assertRaisesRegex(ValueError, "activity_archive_requires_single_fit"):
            self.module._extract_single_fit(multiple.getvalue())

    def test_single_fit_member_must_pass_signature_size_and_crc_checks(self):
        self.module._validate_fit_payload(VALID_FIT)

        corrupt_signature = bytearray(VALID_FIT)
        corrupt_signature[8:12] = b".BAD"
        with self.assertRaisesRegex(ValueError, "activity_fit_signature_invalid"):
            self.module._validate_fit_payload(bytes(corrupt_signature))

        corrupt_size = bytearray(VALID_FIT)
        corrupt_size[4:8] = (4).to_bytes(4, "little")
        with self.assertRaisesRegex(
            ValueError, "activity_fit_declared_size_mismatch"
        ):
            self.module._validate_fit_payload(bytes(corrupt_size))

        corrupt_crc = bytearray(VALID_FIT)
        corrupt_crc[-1] ^= 0x01
        with self.assertRaisesRegex(ValueError, "activity_fit_file_crc_invalid"):
            self.module._validate_fit_payload(bytes(corrupt_crc))

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("synthetic.fit", b"synthetic-fit-data")
        with self.assertRaisesRegex(ValueError, "activity_fit_header_invalid"):
            self.module._extract_single_fit(archive.getvalue())

    def test_authorized_download_uses_explicit_absolute_output(self):
        with tempfile.TemporaryDirectory() as temp_root:
            client = object()
            with (
                patch.object(
                    self.module, "_get_client", return_value=client
                ) as get_client,
                patch.object(
                    self.module,
                    "download_activity_file",
                    return_value={
                        "file": str((Path(temp_root) / "activity.fit").resolve()),
                        "activity_id": 123,
                        "format": "fit",
                    },
                ) as download,
            ):
                exit_code, payload = self.run_main(
                    [
                        "download",
                        "--activity-id",
                        "123",
                        "--allow-network",
                        "--allow-health-data",
                        "--allow-download",
                        "--output-dir",
                        temp_root,
                    ]
                )
            self.assertEqual(exit_code, self.module.EXIT_OK)
            self.assertTrue(Path(payload["file"]).is_absolute())
            get_client.assert_called_once()
            network_capability = get_client.call_args.kwargs["network_capability"]
            health_data_capability = get_client.call_args.kwargs["health_data_capability"]
            download_capability = get_client.call_args.kwargs["download_capability"]
            request = get_client.call_args.kwargs["request"]
            require_capability(
                network_capability,
                scope="network",
                operation="activity_download",
                request=request,
            )
            require_capability(
                health_data_capability,
                scope="health_data",
                operation="activity_download",
                request=request,
            )
            require_capability(
                download_capability,
                scope="download",
                operation="activity_download",
                request=request,
            )
            download.assert_called_once_with(
                client,
                123,
                "fit",
                Path(temp_root).resolve(),
                network_capability=network_capability,
                health_data_capability=health_data_capability,
                download_capability=download_capability,
                request=request,
            )


if __name__ == "__main__":
    unittest.main()
