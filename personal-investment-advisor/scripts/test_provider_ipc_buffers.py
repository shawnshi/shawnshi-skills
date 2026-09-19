"""Synthetic buffer and spawned-process regressions; no live providers."""

import io
import pickle
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import provider_runtime as runtime


def large_frame_provider():
    values = np.arange(20_000, dtype=np.float64)
    frame = pd.DataFrame({"close": values, "volume": values * 2})
    frame.attrs["origin"] = "synthetic-test-only"
    return frame


class CappedWriterBufferTests(unittest.TestCase):
    def test_protocol4_and_5_large_frame_match_standard_serialization(self):
        payload = {"status": "ok", "data": large_frame_provider()}
        for protocol in (4, 5):
            with self.subTest(protocol=protocol):
                stream = io.BytesIO()
                writer = runtime._CappedWriter(stream, 2 * 1024 * 1024)
                pickle.dump(payload, writer, protocol=protocol)
                self.assertEqual(stream.getvalue(), pickle.dumps(payload, protocol=protocol))
                self.assertEqual(writer.remaining, 2 * 1024 * 1024 - stream.tell())

    def test_bytes_exact_limit_and_overflow(self):
        stream = io.BytesIO()
        writer = runtime._CappedWriter(stream, 2)
        self.assertEqual(writer.write(b"ab"), 2)
        self.assertEqual(writer.remaining, 0)
        with self.assertRaisesRegex(ValueError, "provider_ipc_size_limit"):
            writer.write(b"c")
        self.assertEqual(stream.getvalue(), b"ab")
        self.assertEqual(writer.remaining, 0)

    def test_typed_memoryview_is_counted_in_bytes(self):
        data = memoryview(np.arange(4, dtype=np.int64))
        stream = io.BytesIO()
        writer = runtime._CappedWriter(stream, 8)
        with self.assertRaisesRegex(ValueError, "provider_ipc_size_limit"):
            writer.write(data)
        self.assertEqual(stream.getvalue(), b"")
        self.assertEqual(writer.remaining, 8)
        self.assertEqual(data.nbytes, 32)
        data.release()

    def test_typed_memoryview_success_uses_byte_capacity(self):
        data = memoryview(np.arange(4, dtype=np.int64))
        stream = io.BytesIO()
        writer = runtime._CappedWriter(stream, data.nbytes)
        self.assertEqual(writer.write(data), data.nbytes)
        self.assertEqual(writer.remaining, 0)
        self.assertEqual(stream.getvalue(), data.tobytes())
        self.assertEqual(data.nbytes, 32)
        data.release()

    def test_pickle_buffer_exact_limit_and_caller_remains_usable(self):
        array = np.arange(10_000, dtype=np.float64)
        data = pickle.PickleBuffer(array)
        stream = io.BytesIO()
        writer = runtime._CappedWriter(stream, array.nbytes)
        self.assertEqual(writer.write(data), array.nbytes)
        self.assertEqual(writer.remaining, 0)
        self.assertEqual(stream.getvalue(), array.tobytes())
        with data.raw() as view:
            self.assertEqual(view.nbytes, array.nbytes)
        data.release()

    def test_oversized_pickle_buffer_rejected_before_write(self):
        data = pickle.PickleBuffer(np.arange(10_000, dtype=np.float64))
        stream = io.BytesIO()
        writer = runtime._CappedWriter(stream, 4)
        with self.assertRaisesRegex(ValueError, "provider_ipc_size_limit"):
            writer.write(data)
        self.assertEqual(stream.getvalue(), b"")
        self.assertEqual(writer.remaining, 4)
        data.release()

    def test_fortran_array_matches_standard_serialization(self):
        data = np.asfortranarray(np.arange(10_000).reshape(100, 100))
        stream = io.BytesIO()
        pickle.dump(data, runtime._CappedWriter(stream, 2 * 1024 * 1024), protocol=5)
        self.assertEqual(stream.getvalue(), pickle.dumps(data, protocol=5))

    def test_fortran_pickle_buffer_direct_write(self):
        array = np.asfortranarray(np.arange(10_000).reshape(100, 100))
        data = pickle.PickleBuffer(array)
        stream = io.BytesIO()
        writer = runtime._CappedWriter(stream, array.nbytes)
        self.assertEqual(writer.write(data), array.nbytes)
        self.assertEqual(writer.remaining, 0)
        self.assertEqual(stream.getvalue(), array.tobytes(order="F"))
        data.release()

    def test_noncontiguous_pickle_buffer_preserves_failure(self):
        data = pickle.PickleBuffer(np.arange(20, dtype=np.float64)[::2])
        stream = io.BytesIO()
        writer = runtime._CappedWriter(stream, 1024)
        with self.assertRaises(BufferError):
            writer.write(data)
        self.assertEqual(stream.getvalue(), b"")
        self.assertEqual(writer.remaining, 1024)
        data.release()


class SpawnedProviderBufferTests(unittest.TestCase):
    def test_large_dataframe_crosses_actual_owned_process_boundary(self):
        outcome = runtime.run_provider(large_frame_provider, timeout_seconds=20, max_attempts=1)
        self.assertEqual(outcome["status"], "ok", outcome)
        self.assertEqual(outcome["attempts"], 1)
        expected = large_frame_provider()
        pd.testing.assert_frame_equal(outcome["data"], expected)
        self.assertEqual(outcome["data"].attrs, expected.attrs)

    def test_owned_child_oversize_is_ipc_error_not_no_data(self):
        with patch.object(runtime, "MAX_IPC_BYTES", 65536):
            outcome = runtime.run_provider(large_frame_provider, timeout_seconds=20, max_attempts=1)
        self.assertEqual(outcome["status"], "error", outcome)
        self.assertEqual(outcome["phase"], "ipc_write", outcome)
        self.assertEqual(outcome["error"], "provider_ipc_size_limit", outcome)
        self.assertEqual(outcome["attempts"], 1)
        self.assertFalse(outcome["retryable"])


if __name__ == "__main__":
    unittest.main()
