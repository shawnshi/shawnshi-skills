from __future__ import annotations

import errno
import hashlib
import multiprocessing
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.common import SCRIPTS, load_module
from tests.common import runtime_tx as tx


def _lock_process(path: str, connection, timeout: float) -> None:
    """Spawned interpreter: never inherit the parent's lock/file descriptor."""
    try:
        try:
            with tx.PosixFileLock(Path(path), timeout=timeout):
                connection.send("acquired")
                if not connection.poll(10):
                    raise TimeoutError("parent did not release test lock")
                if connection.recv() != "release":
                    raise RuntimeError("invalid test lock command")
        except tx.LockTimeout:
            connection.send("timeout")
    finally:
        connection.close()


class PlatformSupportTests(unittest.TestCase):
    def start_lock_process(self, path: Path, timeout: float = 0.2):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_lock_process, args=(str(path), child, timeout))
        process.start()
        child.close()

        def cleanup():
            if process.is_alive():
                process.terminate()
            process.join(5)
            parent.close()
            process.close()

        self.addCleanup(cleanup)
        return process, parent

    def receive(self, connection):
        self.assertTrue(connection.poll(10), "spawned lock process timed out")
        return connection.recv()

    def assert_child_acquires(self, path: Path):
        process, connection = self.start_lock_process(path, timeout=2)
        self.assertEqual(self.receive(connection), "acquired")
        connection.send("release")
        process.join(5)
        self.assertEqual(process.exitcode, 0)

    def test_cross_process_lock_timeout_then_reacquire(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lock"
            with tx.PosixFileLock(path, timeout=2):
                process, connection = self.start_lock_process(path)
                self.assertEqual(self.receive(connection), "timeout")
                process.join(5)
                self.assertEqual(process.exitcode, 0)
            self.assert_child_acquires(path)

    def test_process_death_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lock"
            process, connection = self.start_lock_process(path, timeout=2)
            self.assertEqual(self.receive(connection), "acquired")
            with self.assertRaises(tx.LockTimeout):
                with tx.PosixFileLock(path, timeout=0.1):
                    self.fail("child owns the lock")
            process.terminate()
            process.join(5)
            self.assertIsNotNone(process.exitcode)
            self.assertNotEqual(process.exitcode, 0)
            self.assert_child_acquires(path)

    def test_lock_entry_fsync_failure_releases_handle_and_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lock"
            lock = tx.PosixFileLock(path)
            error = OSError(errno.EIO, "lock metadata fsync failed")
            with mock.patch.object(tx.os, "fsync", side_effect=error):
                with self.assertRaises(OSError) as caught:
                    lock.__enter__()
            self.assertIs(caught.exception, error)
            self.assertIsNone(lock._handle)
            self.assert_child_acquires(path)

    def test_non_contention_lock_error_is_not_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lock"
            lock = tx.PosixFileLock(path)
            api, name = (tx.msvcrt, "locking") if os.name == "nt" else (tx.fcntl, "flock")
            error = OSError(errno.EBADF, "bad lock descriptor")
            with mock.patch.object(api, name, side_effect=error):
                with self.assertRaises(OSError) as caught:
                    lock.__enter__()
            self.assertIs(caught.exception, error)
            self.assertIsNone(lock._handle)
            self.assert_child_acquires(path)

    def test_lock_body_failure_releases_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "lock"
            with self.assertRaisesRegex(RuntimeError, "^body failed$"):
                with tx.PosixFileLock(path):
                    raise RuntimeError("body failed")
            self.assert_child_acquires(path)

    def test_atomic_write_preserves_bytes_and_reports_replace_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "成果.md"
            raw = "中文\r\nLF\n".encode()
            tx.atomic_write_bytes(path, raw, mode=0o600)
            self.assertEqual(path.read_bytes(), raw)
            error = PermissionError(errno.EACCES, "replace denied")
            for mode in (0o600, 0o400):
                with self.subTest(mode=mode), mock.patch.object(tx.os, "replace", side_effect=error):
                    with self.assertRaises(PermissionError) as caught:
                        tx.atomic_write_bytes(path, b"after", mode=mode)
                self.assertIs(caught.exception, error)
                self.assertEqual(path.read_bytes(), raw)
                self.assertEqual(list(path.parent.iterdir()), [path])

    def test_native_open_target_replace_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "target.md"
            tx.atomic_write_bytes(path, b"before", mode=0o600)
            with path.open("rb") as reader:
                if os.name == "nt":
                    with self.assertRaises(PermissionError):
                        tx.atomic_write_bytes(path, b"after", mode=0o600)
                    self.assertEqual(path.read_bytes(), b"before")
                else:
                    tx.atomic_write_bytes(path, b"after", mode=0o600)
                    self.assertEqual(path.read_bytes(), b"after")
                self.assertEqual(reader.read(), b"before")
            tx.atomic_write_bytes(path, b"after", mode=0o600)
            self.assertEqual(path.read_bytes(), b"after")
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_native_permission_mode_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "target.md"
            try:
                tx.atomic_write_bytes(path, b"readonly", mode=0o400)
                if os.name == "nt":
                    self.assertTrue(path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
                    with self.assertRaises(PermissionError):
                        tx.atomic_write_bytes(path, b"not allowed", mode=0o600)
                    self.assertEqual(path.read_bytes(), b"readonly")
                else:
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
            finally:
                if path.exists():
                    path.chmod(stat.S_IREAD | stat.S_IWRITE)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def assert_native_second_target_rollback(self, workspace: Path, winerrors: tuple[int, ...]):
        first, second = workspace / "a.md", workspace / "b.md"
        before = {path: path.read_bytes() for path in (first, second)}
        modes = {path: stat.S_IMODE(path.stat().st_mode) for path in before}
        attributes = (
            {path: path.stat().st_file_attributes for path in before}
            if os.name == "nt" else {}
        )
        candidate = {first: b"a-after\r\n", second: b"b-after\n"}
        native_replace = os.replace
        native_errors = []
        second_attempts = []
        postflight_error = RuntimeError("POSIX replacement succeeded; test rollback")

        def observe_replace(source, destination):
            if Path(destination) == second:
                second_attempts.append(first.read_bytes())
            try:
                return native_replace(source, destination)
            except PermissionError as error:
                native_errors.append(error)
                raise

        def postflight(_workspace):
            self.assertNotEqual(os.name, "nt", "protected Windows replacement succeeded")
            self.assertEqual({path: path.read_bytes() for path in before}, candidate)
            raise postflight_error

        # Observe real os.replace; no injected permission errors or fake locks.
        expected_error = PermissionError if os.name == "nt" else RuntimeError
        with (
            tx.output_root_lock(workspace.parent, timeout=2),
            tx.workspace_lock(workspace, timeout=2),
            mock.patch.object(tx.os, "replace", side_effect=observe_replace),
            self.assertRaises(expected_error) as caught,
        ):
            tx.transactional_commit(
                workspace, candidate, operation="native_second_target_rollback",
                postflight=postflight,
            )
        self.assertEqual(second_attempts[0], candidate[first])
        if os.name == "nt":
            self.assertEqual(len(second_attempts), 1, "untouched target must not be replaced again")
            self.assertEqual(len(native_errors), 1)
            self.assertIs(caught.exception, native_errors[0])
            self.assertIn(caught.exception.winerror, winerrors)
        else:
            # POSIX permits replacement despite a read-only file or open reader.
            self.assertEqual(native_errors, [])
            self.assertIs(caught.exception, postflight_error)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), modes[path])
            if os.name == "nt":
                self.assertEqual(path.stat().st_file_attributes, attributes[path])
        self.assertFalse((workspace / tx.JOURNAL_NAME).exists())
        self.assertEqual(list(workspace.glob(f"{tx.TX_DIR_PREFIX}*")), [])
        self.assertEqual(
            {path.name for path in workspace.iterdir()},
            {"a.md", "b.md", tx.WORKSPACE_LOCK_NAME},
        )

    def test_native_second_readonly_target_rolls_back_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            first, second = workspace / "a.md", workspace / "b.md"
            tx.atomic_write_bytes(first, "甲-before\r\n".encode(), mode=0o600)
            tx.atomic_write_bytes(second, "乙-before\n".encode(), mode=0o400)
            try:
                if os.name == "nt":
                    self.assertTrue(second.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)
                self.assert_native_second_target_rollback(workspace, winerrors=(5,))
            finally:
                # Test-owned temporary fixture only, after protection assertions.
                second.chmod(stat.S_IREAD | stat.S_IWRITE)

    def test_native_second_open_target_rolls_back_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            first, second = workspace / "a.md", workspace / "b.md"
            tx.atomic_write_bytes(first, "甲-before\r\n".encode(), mode=0o600)
            raw = "乙-before\n".encode()
            tx.atomic_write_bytes(second, raw, mode=0o600)
            # The native Windows reader denies delete-sharing until it closes.
            with second.open("rb") as reader:
                # Windows may report access denied (5) or sharing violation (32).
                self.assert_native_second_target_rollback(workspace, winerrors=(5, 32))
                self.assertFalse(reader.closed)
                self.assertEqual(reader.read(), raw)
            tx.atomic_write_bytes(second, b"after-reader-closed", mode=0o600)
            self.assertEqual(second.read_bytes(), b"after-reader-closed")

    def test_directory_sync_validates_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tx.fsync_directory(root)
            path = root / "not-a-directory"
            path.write_bytes(b"file")
            with self.assertRaises(OSError):
                tx.fsync_directory(path)
            with self.assertRaises(FileNotFoundError):
                tx.fsync_directory(root / "missing")

    def test_validator_snapshot_hashes_exact_crlf_bytes(self):
        validator = load_module("platform_validate_outputs", SCRIPTS / "validate_outputs.py")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "成果.md"
            raw = (
                '---\r\nschema: "discovery-call-output/v2.5"\r\n'
                'artifact_type: "institution_research"\r\n---\r\n中文\r\n'
            ).encode()
            path.write_bytes(raw)
            issues = []
            documents = validator.load_documents(root, issues)
            self.assertEqual(issues, [])
            self.assertEqual(len(documents), 1)
            self.assertEqual(documents[0].text.encode("utf-8"), raw)
            snapshot = validator.capture_workspace_snapshot(root, documents)
            self.assertEqual(snapshot.file_states[path]["sha256"], hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    unittest.main()
