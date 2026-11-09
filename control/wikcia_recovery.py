"""Wikcia offline same-release integrity recovery; standard library only.

Never backs up or restores recipient databases, credentials or projects. This is
launch-time app-file healing, not an administrator/malware defense or an arbitrary
old-version database rollback. Checkpoint creation is an explicit trusted action.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import uuid

ALLOWED_ROOTS = {
    "hermes-agent",
    "Desktop",
    "plugins",
    "desktop-plugins",
    "skills",
    "standalone",
    "bin",
    "bootstrap",
    "tools",
    "installs",
    "agents",
    "software",
}
ALLOWED_FILES = {
    "wikcia_entry.py",
    "launch.py",
    "install_engine.py",
    "installer.py",
    "asset_setup.py",
    "wikcia_setup.py",
    "lpx-product.json",
}
PRIVATE = {
    "auth.json",
    ".env",
    "config.yaml",
    "state.db",
    "USER.md",
    "MEMORY.md",
    "sessions",
    "memories",
    "projects",
    "lpx-data",
    "lead-intelligence",
    "vault",
    "mcp-tokens",
    "mcp-tokens",
    "desktop-user-data",
    "shared",
    "logs",
    "cache",
    "backups",
    "outputs",
    "__pycache__",
    ".git",
}


class RecoveryError(RuntimeError):
    pass


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoveryError(
            "Recovery metadata is missing or invalid: " + Path(path).name
        ) from exc


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _no_links(path, root):
    root = Path(root).absolute()
    path = Path(path).absolute()
    if ".." in path.parts or not path.is_relative_to(root):
        raise RecoveryError("Recovery path escapes its installation")
    current = root
    for part in [None, *path.relative_to(root).parts]:
        if part is not None:
            current /= part
        if current.is_symlink() or (
            hasattr(current, "is_junction") and current.is_junction()
        ):
            raise RecoveryError("Recovery refuses symbolic links and junctions")
    return path


def _root(root):
    root = Path(root).absolute()
    _no_links(root, root)
    marker = _json(root / "wikcia-product.json")
    if marker.get("product") != "wikcia-studio" or marker.get("schema") != 1:
        raise RecoveryError("Not a supported Wikcia installation")
    _no_links(root / "recovery", root)
    return root


def _owned(root, relative):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise RecoveryError("Expected a relative portable app path")
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith("/") or ".." in parts or "." in parts:
        raise RecoveryError("Unsafe recovery path")
    if parts[0] not in ALLOWED_ROOTS and relative not in ALLOWED_FILES:
        raise RecoveryError("Path is not application-owned: " + relative)
    private_names = {name.casefold() for name in PRIVATE}
    if any(
        p.casefold() in private_names
        or p.casefold().startswith(".env")
        or p.casefold().startswith("auth.json")
        for p in parts
    ):
        raise RecoveryError("Private or mutable state is excluded from recovery")
    if Path(relative).suffix.lower() in {
        ".db",
        ".sqlite",
        ".sqlite3",
        ".wal",
        ".shm",
        ".log",
        ".pyc",
    }:
        raise RecoveryError("Mutable database/log/cache is excluded from recovery")
    return _no_links(root / relative, root)


@contextmanager
def _lock(root):
    folder = _no_links(root / "recovery", root)
    folder.mkdir(exist_ok=True)
    path = _no_links(folder / "controller.lock", root)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RecoveryError(
                "RECOVERY_BUSY: another controller owns this installation"
            ) from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _health(command, root):
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(x, str) for x in command)
    ):
        raise RecoveryError("A trusted explicit local health command is required")
    if not Path(command[0]).is_absolute() or not Path(command[0]).is_file():
        raise RecoveryError(
            "Health executable must be an explicit existing absolute path"
        )
    try:
        environment = dict(os.environ)
        for name in [
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            "HERMES_PROFILE",
            "HERMES_SESSION_ID",
            "HERMES_PARENT_SESSION_ID",
        ]:
            environment.pop(name, None)
        environment.update(
            HERMES_HOME=str(root),
            HERMES_INSTALL_ROOT=str(root / "hermes-agent"),
            HERMES_RUNTIME_DIR=str(root / "tools"),
            HERMES_CLI_PROG="wikcia",
            HERMES_NO_GLOBAL_INTEGRATION="1",
            PYTHONUTF8="1",
        )
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            timeout=60,
            env=environment,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecoveryError("Local recovery health command could not complete") from exc
    if result.returncode != 0:
        raise RecoveryError(
            "Local recovery health command failed (exit " + str(result.returncode) + ")"
        )
    return {
        "exit_code": result.returncode,
        "output_sha256": hashlib.sha256(result.stdout).hexdigest(),
    }


def initialize(root, files, release_id, health_command=None):
    root = _root(root)
    if not isinstance(release_id, str) or not release_id or len(release_id) > 120:
        raise RecoveryError("Invalid release identity")
    files = sorted(set(files))
    if not files:
        raise RecoveryError("No application files were selected")
    with _lock(root):
        lockfile = root / "RELEASE_LOCK.json"
        if lockfile.exists():
            raise RecoveryError(
                "A checkpoint already exists; explicit staged upgrade is required"
            )
        paths = [(relative, _owned(root, relative)) for relative in files]
        if any(not p.is_file() for _, p in paths):
            raise RecoveryError("Cannot baseline missing application files")
        health = _health(health_command, root)
        checkpoint = root / "recovery/checkpoints" / uuid.uuid4().hex
        _no_links(checkpoint, root)
        objects = checkpoint / "objects"
        objects.mkdir(parents=True)
        entries = []
        for relative, path in paths:
            hashed = digest(path)
            target = objects / hashed
            if not target.exists():
                shutil.copy2(path, target)
            if digest(target) != hashed:
                raise RecoveryError("Checkpoint copy failed integrity verification")
            entries.append(
                {"path": relative, "sha256": hashed, "bytes": path.stat().st_size}
            )
        manifest = {
            "schema": 1,
            "release_id": release_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "marker_sha256": digest(root / "wikcia-product.json"),
            "files": entries,
            "health_command": health_command,
            "initial_health": health,
            "recovery_mode": "same-release-owned-file-repair-no-user-data-rollback",
        }
        _atomic_json(checkpoint / "manifest.json", manifest)
        _atomic_json(
            lockfile,
            {
                "schema": 1,
                "product": "wikcia-studio",
                "release_id": release_id,
                "upstream_updates_allowed": False,
                "checkpoint": checkpoint.relative_to(root).as_posix(),
                "manifest_sha256": digest(checkpoint / "manifest.json"),
            },
        )
        return {
            "status": "CHECKPOINT_VERIFIED",
            "release_id": release_id,
            "files": len(entries),
        }


def _checkpoint(root):
    lockfile = _no_links(root / "RELEASE_LOCK.json", root)
    lock = _json(lockfile)
    if lock.get("schema") != 1 or lock.get("product") != "wikcia-studio":
        raise RecoveryError("Invalid release lock")
    relative = lock.get("checkpoint", "")
    if (
        not isinstance(relative, str)
        or not relative.startswith("recovery/checkpoints/")
        or ".." in PurePosixPath(relative).parts
        or "\\" in relative
        or ":" in relative
    ):
        raise RecoveryError("Unsafe checkpoint location")
    checkpoint = _no_links(root / relative, root)
    manifest_path = _no_links(checkpoint / "manifest.json", root)
    if digest(manifest_path) != lock.get("manifest_sha256"):
        raise RecoveryError("Checkpoint manifest integrity failed")
    manifest = _json(manifest_path)
    if manifest.get("schema") != 1 or manifest.get("release_id") != lock.get(
        "release_id"
    ):
        raise RecoveryError("Checkpoint release identity mismatch")
    if digest(root / "wikcia-product.json") != manifest.get("marker_sha256"):
        raise RecoveryError(
            "Release marker changed; automatic cross-release/schema rollback is refused"
        )
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise RecoveryError("Checkpoint contains no app files")
    if len({e["path"] for e in entries}) != len(entries):
        raise RecoveryError("Duplicate recovery paths")
    for entry in entries:
        _owned(root, entry["path"])
        hashed = entry.get("sha256", "")
        if len(hashed) != 64 or any(c not in "0123456789abcdef" for c in hashed):
            raise RecoveryError("Invalid object digest")
        _no_links(checkpoint / "objects" / hashed, root)
    return checkpoint, manifest


def _inspect(root):
    checkpoint, manifest = _checkpoint(root)
    damaged = []
    for entry in manifest["files"]:
        path = _owned(root, entry["path"])
        if (
            not path.is_file()
            or path.stat().st_size != entry["bytes"]
            or digest(path) != entry["sha256"]
        ):
            damaged.append(entry)
    return checkpoint, manifest, damaged


def status(root):
    root = _root(root)
    if not (root / "RELEASE_LOCK.json").is_file():
        return {"status": "RECOVERY_NOT_READY", "files": 0}
    _, manifest, damaged = _inspect(root)
    return {
        "status": "DEGRADED" if damaged else "HEALTHY",
        "release_id": manifest["release_id"],
        "files": len(manifest["files"]),
        "damaged": [e["path"] for e in damaged],
        "scope": manifest["recovery_mode"],
    }


def ensure_healthy(root):
    root = _root(root)
    with _lock(root):
        checkpoint, manifest, damaged = _inspect(root)
        journal_path = _no_links(root / "recovery/transaction.json", root)
        previous = _json(journal_path) if journal_path.exists() else {}
        if previous.get("status") == "SAFE_MODE":
            raise RecoveryError(
                "SAFE_MODE: previous repair failed; manual inspection is required"
            )
        if not damaged:
            if previous.get("status") == "REPAIRING":
                # A crash after byte replacement must not skip the owed health gate.
                previous.update(
                    status="RECOVERED", health=_health(manifest["health_command"], root)
                )
                _atomic_json(journal_path, previous)
            return {"status": "HEALTHY", "files": len(manifest["files"])}
        # Verify ALL needed source bytes before the first destination mutation.
        for entry in damaged:
            original = checkpoint / "objects" / entry["sha256"]
            if not original.is_file() or digest(original) != entry["sha256"]:
                raise RecoveryError(
                    "Checkpoint payload is corrupt; no destination was changed"
                )
        incident = (
            previous.get("incident")
            if previous.get("status") == "REPAIRING"
            else uuid.uuid4().hex
        )
        quarantine = _no_links(root / "recovery/quarantine" / incident, root)
        quarantine.mkdir(parents=True, exist_ok=True)
        journal = {
            "schema": 1,
            "incident": incident,
            "status": "REPAIRING",
            "release_id": manifest["release_id"],
            "files": [e["path"] for e in damaged],
        }
        _atomic_json(journal_path, journal)
        try:
            for entry in damaged:
                destination = _owned(root, entry["path"])
                source = checkpoint / "objects" / entry["sha256"]
                saved = quarantine / entry["path"]
                if destination.is_file() and not saved.exists():
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, saved)
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(
                    destination.name + ".wikcia-repair-" + uuid.uuid4().hex
                )
                try:
                    shutil.copy2(source, temporary)
                    if digest(temporary) != entry["sha256"]:
                        raise RecoveryError(
                            "Staged repair failed integrity verification"
                        )
                    _owned(root, entry["path"])
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            _, _, remaining = _inspect(root)
            if remaining:
                raise RecoveryError("Post-repair integrity check failed")
            health = _health(manifest["health_command"], root)
            journal.update(status="RECOVERED", health=health)
            _atomic_json(journal_path, journal)
            return {
                "status": "RECOVERED",
                "repaired": [e["path"] for e in damaged],
                "release_id": manifest["release_id"],
                "health": health,
            }
        except Exception as exc:
            journal.update(status="SAFE_MODE", error_type=type(exc).__name__)
            _atomic_json(journal_path, journal)
            raise RecoveryError(
                "SAFE_MODE: repair did not complete; preserved diagnostics and user data"
            ) from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("action", choices=["status", "check", "repair"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = (
            status(args.root) if args.action == "status" else ensure_healthy(args.root)
        )
        code = 0 if result["status"] in {"HEALTHY", "RECOVERED"} else 1
    except (OSError, ValueError, KeyError, TypeError, RecoveryError) as exc:
        result = {"status": "SAFE_MODE", "message": str(exc)}
        code = 2
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
