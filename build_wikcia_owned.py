"""Build a new Wikcia-owned transfer installer; never alters a prior release."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT))

CORE_OVERLAYS = [
    "wikcia_release.py",
    "hermes_cli/_launchers.py",
    "hermes_cli/_early_recovery.py",
    "hermes_cli/banner.py",
    "hermes_cli/main.py",
    "hermes_cli/main_install_repair.py",
    "hermes_cli/plugins_cmd_update.py",
    "hermes_cli/skills_hub.py",
    "hermes_cli/source_check.py",
    "hermes_cli/source_completion.py",
    "hermes_cli/update_cmd.py",
    "hermes_cli/venv_sync.py",
    "pm/cli.py",
]


def build(base, desktop, output, release_id):
    from bundle_branding import scan_data
    from installer import load_bundle, sha256

    base, desktop, output = map(lambda p: Path(p).resolve(), [base, desktop, output])
    manifest = load_bundle(base)
    if output.exists():
        raise ValueError("Preserve the previous release: output already exists")
    stage = output.with_name(output.name + ".building")
    if stage.exists():
        raise ValueError("An unfinished build requires inspection")
    stage.mkdir(parents=True)
    private = {"auth.json", ".env", "config.yaml", "state.db", "USER.md", "MEMORY.md"}
    archive_index = []

    def emit(z, name, data):
        if Path(name).name in private:
            raise ValueError("Private path refused: " + name)
        scan_data(name, data)
        z.writestr(name, data)
        archive_index.append(
            {
                "payload": Path(z.filename).name,
                "path": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )

    with (
        zipfile.ZipFile(base / "source.zip") as old,
        zipfile.ZipFile(
            stage / "source.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=5
        ) as new,
    ):
        for item in old.infolist():
            if item.is_dir() or item.filename in CORE_OVERLAYS:
                continue
            emit(new, item.filename, old.read(item))
        for name in CORE_OVERLAYS:
            emit(new, name, (HERE / "core" / name).read_bytes())
    desktop_names = []
    with zipfile.ZipFile(
        stage / "desktop.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=3
    ) as new:
        for path in sorted(desktop.rglob("*")):
            if not path.is_file():
                continue
            if path.is_symlink():
                raise ValueError("Linked Desktop payload refused")
            name = path.relative_to(desktop).as_posix()
            if any(
                x in path.parts for x in ["desktop-user-data", "__pycache__", "backups"]
            ):
                raise ValueError("Private Desktop folder")
            data = path.read_bytes()
            if name == "resources/install-stamp.json":
                stamp = json.loads(data)
                stamp.update(distribution="wikcia-studio", updateMechanism="external")
                data = (json.dumps(stamp, indent=2) + "\n").encode("utf-8")
            emit(new, name, data)
            desktop_names.append(name)
    # Preserve approved product modules/skills; give fresh recipients a Wikcia-only persona.
    with (
        zipfile.ZipFile(base / "seed.zip") as old,
        zipfile.ZipFile(
            stage / "seed.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=5
        ) as new,
    ):
        for item in old.infolist():
            if item.is_dir():
                continue
            data = old.read(item)
            if item.filename == "SOUL.md":
                data = (HERE / "WIKCIA-SOUL.md").read_bytes()
            emit(new, item.filename, data)
    shutil.copytree(
        base / "bootstrap",
        stage / "bootstrap",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for path in (HERE / "wrappers").iterdir():
        if path.is_file():
            shutil.copy2(path, stage / path.name)
    shutil.copytree(
        HERE / "control",
        stage / "control",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(HERE / "control/wikcia_setup.py", stage / "wikcia_setup.py")
    spec = importlib.util.spec_from_file_location(
        "recovery_build", HERE / "control/wikcia_recovery.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load recovery controller")
    recovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recovery)
    owned = []
    excluded = []
    for zname, prefix in [
        ("source.zip", "hermes-agent/"),
        ("desktop.zip", "Desktop/"),
        ("seed.zip", ""),
    ]:
        with zipfile.ZipFile(stage / zname) as z:
            for name in z.namelist():
                if name.endswith("/"):
                    continue
                relative = prefix + name
                try:
                    recovery._owned(stage, relative)
                except recovery.RecoveryError:
                    excluded.append(relative)
                    continue
                owned.append(relative)
    owned += [
        "wikcia_entry.py",
        "standalone/ownership.py",
        "bin/wikcia.cmd",
        "bin/wikcia-desktop.cmd",
        "bin/wikcia-setup.cmd",
        "bin/wikcia",
        "launch.py",
        "installer.py",
        "install_engine.py",
        "asset_setup.py",
        "wikcia_setup.py",
    ]
    (stage / "wikcia-owned-files.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "release_id": release_id,
                "files": sorted(set(owned)),
                "excluded_mutable_or_nonapp": sorted(set(excluded)),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for name in ["source", "desktop", "seed"]:
        p = stage / (name + ".zip")
        manifest["payloads"][name] = {
            "file": p.name,
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        }
    manifest["release_id"] = release_id
    manifest["update_owner"] = "Wikcia Studio"
    manifest["upstream_updates_allowed"] = False
    manifest["recovery"] = {
        "included": True,
        "mode": "automatic-launch-time-same-release-app-file-repair",
        "checkpoint_created": "after actual local core health check on recipient",
        "user_data_restored": False,
        "limitations": "Not a runtime-crash watchdog or cross-version database rollback; cannot defeat administrative tampering or storage loss.",
    }
    manifest["installer_release"] = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "base_release": base.name,
        "scope": "Wikcia-owned native Desktop, source/runtime, approved component recipes, seed, update guards and offline recovery",
        "credential_policy": "Recipient-owned accounts; no source credentials or consent grants",
        "core_overlays": CORE_OVERLAYS,
    }
    manifests = []
    for p in sorted(stage.rglob("*")):
        if p.is_file() and p.name not in {
            "manifest.json",
            "source.zip",
            "desktop.zip",
            "seed.zip",
        }:
            rel = p.relative_to(stage).as_posix()
            scan_data(rel, p.read_bytes())
            manifests.append(
                {"file": rel, "sha256": sha256(p), "bytes": p.stat().st_size}
            )
    manifest["installer_files"] = manifests
    (stage / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    load_bundle(stage)
    for name in ["source.zip", "desktop.zip", "seed.zip"]:
        with zipfile.ZipFile(stage / name) as z:
            if z.testzip():
                raise ValueError("Payload CRC failed: " + name)
    stage.rename(output)
    index = HERE / "evidence/payload-file-index.json"
    index.write_text(json.dumps(archive_index, indent=2), encoding="utf-8")
    result = {
        "release_id": release_id,
        "output": str(output),
        "owned_static_files": len(set(owned)),
        "excluded_mutable_or_nonapp": excluded,
        "source_overlays": CORE_OVERLAYS,
        "payloads": manifest["payloads"],
        "desktop_source": str(desktop),
        "desktop_original_asar_sha256": sha256(desktop / "resources/app.asar"),
        "prior_release_preserved": True,
    }
    (HERE / "evidence/build-receipt.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "excluded_mutable_or_nonapp"},
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["base", "desktop", "output"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    a = parser.parse_args()
    build(a.base, a.desktop, a.output, a.release_id)
