"""Windows file policy and limited-token evidence; never enables privileges.

Native contracts: Microsoft Get/SetNamedSecurityInfoW, AccessCheck,
GetTokenInformation(TokenLinkedToken), DuplicateToken, ImpersonateLoggedOnUser.
Uses the already-installed pywin32 bindings; missing bindings fail closed.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
from functools import wraps

import pywintypes

import win32api
import win32con
import win32file
import win32security as security

SECURITY_PARTS = 7  # owner, primary group, DACL (SACL is not silently claimed)
MODIFY = 0x1301BF


class CapabilityError(RuntimeError):
    pass


def native_errors(function):
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except pywintypes.error as exc:
            raise CapabilityError(f"Windows native error: {exc.args}") from exc
    return checked


@native_errors
def descriptor(path: Path) -> str:
    sd = security.GetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, SECURITY_PARTS)
    if sd.GetSecurityDescriptorDacl() is None:
        raise CapabilityError("null DACL is not an acceptable report policy")
    return security.ConvertSecurityDescriptorToStringSecurityDescriptor(sd, 1, SECURITY_PARTS)


@native_errors
def apply(path: Path, policy: str) -> None:
    # Reapplying an already exact inherited policy can add AUTO_INHERITED
    # control bits. Preserve the OS-created descriptor without a setter call.
    if descriptor(path) == policy:
        return
    sd = security.ConvertStringSecurityDescriptorToSecurityDescriptor(policy, 1)
    protected = sd.GetSecurityDescriptorControl()[0] & security.SE_DACL_PROTECTED
    flags = SECURITY_PARTS | (security.PROTECTED_DACL_SECURITY_INFORMATION if protected
                              else security.UNPROTECTED_DACL_SECURITY_INFORMATION)
    security.SetNamedSecurityInfo(str(path), security.SE_FILE_OBJECT, flags,
        sd.GetSecurityDescriptorOwner(), sd.GetSecurityDescriptorGroup(),
        sd.GetSecurityDescriptorDacl(), None)
    if descriptor(path) != policy:
        raise CapabilityError("owner/group/DACL/protection fidelity unavailable")


@native_errors
def parent_owner_policy(parent: Path, inherited_file: Path) -> str:
    """Use the OS's file inheritance result, but the confirmed parent's owner/group."""
    parent_sd = security.ConvertStringSecurityDescriptorToSecurityDescriptor(descriptor(parent), 1)
    sd = security.ConvertStringSecurityDescriptorToSecurityDescriptor(descriptor(inherited_file), 1)
    sd.SetSecurityDescriptorOwner(parent_sd.GetSecurityDescriptorOwner(), False)
    sd.SetSecurityDescriptorGroup(parent_sd.GetSecurityDescriptorGroup(), False)
    return security.ConvertSecurityDescriptorToStringSecurityDescriptor(sd, 1, SECURITY_PARTS)


@native_errors
def limited_token():
    token = security.OpenProcessToken(win32api.GetCurrentProcess(),
                                      win32con.TOKEN_QUERY | win32con.TOKEN_DUPLICATE)
    try:
        kind = security.GetTokenInformation(token, security.TokenElevationType)
        if kind == 2:
            linked = security.GetTokenInformation(token, security.TokenLinkedToken)
            if security.GetTokenInformation(linked, security.TokenElevation):
                linked.Close()
                raise CapabilityError("linked token is elevated")
            return linked, False
        if security.GetTokenInformation(token, security.TokenElevation):
            raise CapabilityError("non-elevated user token unavailable")
        return security.DuplicateToken(token, security.SecurityIdentification), True
    finally:
        token.Close()


class GenericMapping(ctypes.Structure):
    _fields_ = [(n, wintypes.DWORD) for n in ("read", "write", "execute", "all")]


@native_errors
def effective_access(path: Path, expected: bytes) -> dict:
    """Native limited-token AccessCheck, separately labelled host-token file IO.

    Identification-level linked tokens cannot impersonate for file IO. On an
    elevated host, actual_non_elevated_open remains false, never a fake pass.
    """
    token, host_is_limited = limited_token()
    try:
        sd = security.ConvertStringSecurityDescriptorToSecurityDescriptor(descriptor(path), 1)
        raw = ctypes.create_string_buffer(bytes(sd))
        mapping = GenericMapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        api = ctypes.WinDLL("advapi32", use_last_error=True).AccessCheck
        api.argtypes = [ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD,
                        ctypes.POINTER(GenericMapping), ctypes.c_void_p,
                        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                        ctypes.POINTER(wintypes.BOOL)]
        api.restype = wintypes.BOOL
        privileges = ctypes.create_string_buffer(4096)
        size, granted, allowed = wintypes.DWORD(4096), wintypes.DWORD(), wintypes.BOOL()
        if not api(raw, int(token), MODIFY, ctypes.byref(mapping), privileges,
                   ctypes.byref(size), ctypes.byref(granted), ctypes.byref(allowed)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not allowed.value or granted.value & MODIFY != MODIFY:
            raise CapabilityError("limited-token AccessCheck denied read/write/modify")
        sid = security.ConvertSidToStringSid(security.GetTokenInformation(token, security.TokenUser)[0])
        handle = win32file.CreateFile(str(path), win32con.GENERIC_READ | win32con.GENERIC_WRITE | win32con.DELETE,
            7, None, win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
        try:
            data = win32file.ReadFile(handle, len(expected) + 1)[1]
            if data != expected:
                raise CapabilityError("host-token read content mismatch")
        finally:
            handle.Close()
        return {"sid": sid, "limited_token_accesscheck": "read/write/modify",
                "host_token_content_read": True, "actual_non_elevated_open": host_is_limited}
    finally:
        token.Close()
