from __future__ import annotations

import hmac
import os
import secrets
import stat
from pathlib import Path


def ensure_token(path: Path) -> str:
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            _tighten(path)
            return token
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    _tighten(path)
    return token


def read_token(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def check_token(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def is_user_only(path: Path) -> bool:
    if os.name == "nt":
        return _windows_user_only(path)
    return (path.stat().st_mode & 0o777) == (stat.S_IRUSR | stat.S_IWUSR)


def _tighten(path: Path) -> None:
    if os.name == "nt":
        _tighten_windows(path)
        return
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _tighten(path)


def _windows_dlls():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD
    advapi32.CopySid.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.CopySid.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAccessAllowedAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    advapi32.AddAccessAllowedAce.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAclInformation.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    return kernel32, advapi32


def _current_user_sid():
    import ctypes
    from ctypes import wintypes

    kernel32, advapi32 = _windows_dlls()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        length = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(length))
        buffer = ctypes.create_string_buffer(length.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, length, ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())

        class SidAndAttributes(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        source = SidAndAttributes.from_buffer(buffer).Sid
        sid_length = advapi32.GetLengthSid(source)
        copy = ctypes.create_string_buffer(sid_length)
        if not advapi32.CopySid(sid_length, copy, source):
            raise ctypes.WinError(ctypes.get_last_error())
        return copy
    finally:
        kernel32.CloseHandle(token)


def _tighten_windows(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    _kernel32, advapi32 = _windows_dlls()
    sid = _current_user_sid()
    sid_length = advapi32.GetLengthSid(ctypes.addressof(sid))
    class Acl(ctypes.Structure):
        _fields_ = [
            ("AclRevision", ctypes.c_ubyte),
            ("Sbz1", ctypes.c_ubyte),
            ("AclSize", wintypes.WORD),
            ("AceCount", wintypes.WORD),
            ("Sbz2", wintypes.WORD),
        ]

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = [
            ("AceType", ctypes.c_ubyte),
            ("AceFlags", ctypes.c_ubyte),
            ("AceSize", wintypes.WORD),
            ("Mask", wintypes.DWORD),
            ("SidStart", wintypes.DWORD),
        ]

    acl_size = ctypes.sizeof(Acl) + ctypes.sizeof(AccessAllowedAce) + sid_length - ctypes.sizeof(wintypes.DWORD)
    acl = ctypes.create_string_buffer(acl_size)
    if not advapi32.InitializeAcl(acl, acl_size, 2):
        raise ctypes.WinError(ctypes.get_last_error())
    # Read, write, and delete the token file. Inherited access from the parent directory is removed.
    mask = 0x120089 | 0x120116 | 0x00010000
    if not advapi32.AddAccessAllowedAce(acl, 2, mask, ctypes.addressof(sid)):
        raise ctypes.WinError(ctypes.get_last_error())
    protected_dacl = 0x4 | 0x80000000
    status = advapi32.SetNamedSecurityInfoW(str(path), 1, protected_dacl, None, None, acl, None)
    if status != 0:
        raise ctypes.WinError(status)


def _windows_user_only(path: Path) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32, advapi32 = _windows_dlls()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(str(path), 1, 0x4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if status != 0:
        raise ctypes.WinError(status)
    try:
        if not dacl.value:
            return False

        class AclSizeInformation(ctypes.Structure):
            _fields_ = [
                ("AceCount", wintypes.DWORD),
                ("AclBytesInUse", wintypes.DWORD),
                ("AclBytesFree", wintypes.DWORD),
            ]

        class AceHeader(ctypes.Structure):
            _fields_ = [
                ("AceType", ctypes.c_ubyte),
                ("AceFlags", ctypes.c_ubyte),
                ("AceSize", wintypes.WORD),
            ]

        info = AclSizeInformation()
        if not advapi32.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.AceCount != 1:
            return False
        ace = ctypes.c_void_p()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace)):
            raise ctypes.WinError(ctypes.get_last_error())
        header = AceHeader.from_address(ace.value)
        if header.AceType != 0 or header.AceFlags & 0x10:
            return False
        user_sid = _current_user_sid()
        return bool(advapi32.EqualSid(ace.value + 8, ctypes.addressof(user_sid)))
    finally:
        if descriptor.value:
            kernel32.LocalFree(descriptor)
