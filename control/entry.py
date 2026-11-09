"""Wikcia-owned entrypoint. Never resolves a command through ambient PATH."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main(argv=None):
    from standalone.ownership import (
        load_installation,
        owned_environment,
        product_update_status,
    )

    args = list(sys.argv[1:] if argv is None else argv)
    installation = load_installation(ROOT)
    env = owned_environment(installation)
    if args in [["installation"], ["--installation-info"]]:
        print(
            json.dumps(
                {
                    "product": "Wikcia Studio",
                    "root": str(ROOT),
                    "source": str(installation.source),
                    "python": str(installation.python),
                    "profile_home": env["HERMES_HOME"],
                    "desktop_state": env["HERMES_DESKTOP_USER_DATA_DIR"],
                    "update_owner": "Wikcia Studio",
                    "hermes_fallback": False,
                },
                indent=2,
            )
        )
        return 0
    if args[:1] == ["update"]:
        if any(arg not in {"--check", "--json", "--help", "-h"} for arg in args[1:]):
            print(
                "Wikcia updates require a verified standalone release; Hermes self-update flags are not accepted.",
                file=sys.stderr,
            )
            return 2
        status = product_update_status(installation)
        if "--json" in args:
            print(json.dumps(status, indent=2))
        else:
            print("Wikcia Studio " + installation.version)
            print("Update owner: Wikcia Studio")
            print(status["message"])
            print("No online latest-version check was performed.")
        return 0
    if args[:1] in [["desktop"], ["gui"]]:
        subprocess.Popen(
            [str(installation.desktop), "--profile", "default", *args[1:]],
            env=env,
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return 0
    code = (
        "import sys,runpy; sys.path.insert(0,"
        + repr(str(installation.source))
        + "); import hermes_bootstrap; runpy.run_module('hermes_cli.main',run_name='__main__',alter_sys=True)"
    )
    return subprocess.call(
        [str(installation.python), "-I", "-c", code, *args], env=env, cwd=Path.home()
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print("Wikcia startup failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
