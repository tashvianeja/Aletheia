from __future__ import annotations

import importlib
import sys
from pathlib import Path


def secure_path(path: Path) -> None:
    """Restrict existing application data to the current OS account."""
    if sys.platform != "win32":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    security = importlib.import_module("win32security")
    api = importlib.import_module("win32api")
    constants = importlib.import_module("ntsecuritycon")
    token = security.OpenProcessToken(api.GetCurrentProcess(), 0x0008)  # TOKEN_QUERY
    try:
        sid = security.GetTokenInformation(token, security.TokenUser)[0]
    finally:
        token.Close()
    acl = security.ACL()
    inheritance = (
        security.OBJECT_INHERIT_ACE | security.CONTAINER_INHERIT_ACE if path.is_dir() else 0
    )
    acl.AddAccessAllowedAceEx(security.ACL_REVISION, inheritance, constants.FILE_ALL_ACCESS, sid)
    security.SetNamedSecurityInfo(
        str(path),
        security.SE_FILE_OBJECT,
        security.DACL_SECURITY_INFORMATION | security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        acl,
        None,
    )
