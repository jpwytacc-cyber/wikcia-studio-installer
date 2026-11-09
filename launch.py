"""Installed Wikcia CLI and native Desktop entry point."""
import os
import subprocess
import sys
from pathlib import Path

from install_engine import isolated_env


def desktop_environment(root, python):
    root = Path(root).resolve()
    env = isolated_env(root)
    env.update(HERMES_DESKTOP_HERMES_ROOT=str(root / 'hermes-agent'),
               HERMES_DESKTOP_PYTHON=str(python), HERMES_DESKTOP_ISOLATED_BACKEND='1',
               HERMES_DESKTOP_USER_DATA_DIR=str(root / 'desktop-user-data'),
               HERMES_DESKTOP_DASHBOARD_WEB_DIST=str(root / 'hermes-agent/hermes_cli/web_dist'))
    return env


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent
    return subprocess.call([str(root/'recovery/runtime/python.exe'), '-I', str(root/'recovery/launch.py'), *args], cwd=root)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # pythonw has no stdout; keep a local diagnostic rather than silently failing.
        root = Path(__file__).resolve().parent
        (root / 'launch-error.txt').write_text(type(exc).__name__ + ': ' + str(exc), encoding='utf-8')
        raise
