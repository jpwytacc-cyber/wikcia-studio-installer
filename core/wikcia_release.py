"""Wikcia's immutable distribution policy; no shared installation is consulted.

This file belongs to the Wikcia source payload. Removing environment overrides
cannot enable an upstream updater. Internal Hermes APIs and licenses remain.
"""

from pathlib import Path
import sys

MESSAGE = "This Wikcia build is release-locked. Use an approved Wikcia release through the staged upgrade workflow."


def locked(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    # This fork is owned by Wikcia independently of mutable user settings.
    return (root / "wikcia_release.py").is_file()


def require_release_owner(operation="upstream update", root=None):
    if locked(root):
        print(MESSAGE + " Blocked: " + operation, file=sys.stderr)
        raise SystemExit(2)


def update_status(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    return {
        "product": "Wikcia Studio",
        "owner": "Wikcia Studio",
        "supported": False,
        "mechanism": "external",
        "reason": "wikcia-release-locked",
        "upstream_updates_allowed": False,
        "online_version_checked": False,
        "hermesRoot": str(root),
        "message": MESSAGE,
    }
