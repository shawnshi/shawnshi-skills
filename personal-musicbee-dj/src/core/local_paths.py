"""Filesystem checks, not a network firewall or an OS sandbox."""
import os
from pathlib import Path


def local_path(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('Only absolute local paths are allowed; network paths are excluded')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
        api.argtypes, api.restype = [wintypes.LPCWSTR], wintypes.UINT
        # This must precede stat/open: a mapped drive can otherwise initiate SMB access.
        if api(path.anchor) not in {2, 3, 5, 6}:
            raise ValueError('Remote or indeterminate Windows drive denied')
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, 'is_junction') and part.is_junction()):
            raise ValueError('Symlink/junction paths are excluded')
        if os.name == 'nt':
            import stat
            info = part.lstat()
            if getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Reparse-point paths are excluded')
    return path


def local_regular_file(path):
    path = local_path(path)
    if not path.is_file():
        raise FileNotFoundError('File is missing or is not a regular file')
    return path
