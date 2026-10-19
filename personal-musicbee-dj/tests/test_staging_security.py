"""New-file security must be explicit, exclusive, and never touch source permissions."""
import ctypes
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import tag_writer as writer


class Function:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


def fake_kernel(monkeypatch, source, fail=False):
    observed = {}
    raw = b"source descriptor bytes"

    def create(name, access, share, attributes, disposition, flags, template):
        attr = attributes._obj
        observed.update(name=name, access=access, share=share, disposition=disposition,
                        descriptor=ctypes.string_at(attr.lpSecurityDescriptor, len(raw)),
                        inherit=bool(attr.bInheritHandle), attr_size=attr.nLength)
        path = Path(name.removeprefix("\\\\?\\"))
        if fail or path.exists():
            ctypes.set_last_error(5)
            return ctypes.c_void_p(-1).value
        path.write_bytes(b"")
        return 123

    def close(handle):
        observed["closed_handle"] = handle
        return True

    native_kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class KernelProxy:
        CreateFileW = Function(create)
        CloseHandle = Function(close)

        def __getattr__(self, name):
            return getattr(native_kernel, name)

    monkeypatch.setattr(writer, "windows_security_descriptor", lambda path: raw)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: KernelProxy())
    return observed, raw


@pytest.mark.skipif(writer.os.name != "nt", reason="Windows ABI")
def test_create_new_with_exact_source_descriptor(tmp_path, monkeypatch):
    source = tmp_path / "original.flac"
    source.write_bytes(b"original payload")
    observed, raw = fake_kernel(monkeypatch, source)
    stage = writer.staging_file(source)
    assert stage.parent == source.parent and stage != source and stage.stat().st_size == 0
    assert observed["descriptor"] == raw and observed["disposition"] == 1
    assert observed["access"] == 0xC0000000 and observed["share"] == 0
    assert not observed["inherit"] and observed["closed_handle"] == 123
    assert source.read_bytes() == b"original payload"
    stage.unlink()


@pytest.mark.skipif(writer.os.name != "nt", reason="Windows ABI")
def test_create_denied_does_not_fallback(tmp_path, monkeypatch):
    source = tmp_path / "original.flac"
    source.write_bytes(b"original payload")
    fake_kernel(monkeypatch, source, fail=True)
    with pytest.raises(PermissionError):
        writer.staging_file(source)
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.skipif(writer.os.name != "nt", reason="Windows ABI")
def test_existing_collision_never_overwritten(tmp_path, monkeypatch):
    source = tmp_path / "original.flac"
    source.write_bytes(b"original payload")
    other = tmp_path / ".music-tag-stage-collision.flac"
    other.write_bytes(b"unrelated bytes")
    fake_kernel(monkeypatch, source)
    monkeypatch.setattr(writer.uuid, "uuid4", lambda: SimpleNamespace(hex="collision"))
    with pytest.raises(PermissionError):
        writer.staging_file(source)
    assert other.read_bytes() == b"unrelated bytes"
    assert source.read_bytes() == b"original payload"


@pytest.mark.skipif(writer.os.name != "nt", reason="Windows ABI")
def test_digest_contract_not_canonicalized(monkeypatch):
    raw = b"exact descriptor, including existing flags/order"
    monkeypatch.setattr(writer, "windows_security_descriptor", lambda path: raw)
    assert writer.security_digest("unused") == hashlib.sha256(raw).hexdigest()


def test_arbitrary_staging_purpose_rejected(tmp_path):
    source = tmp_path / "original.flac"
    source.write_bytes(b"original payload")
    with pytest.raises(ValueError, match="Invalid staging purpose"):
        writer.staging_file(source, prefix="../other")
    assert list(tmp_path.iterdir()) == [source]
