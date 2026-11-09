"""Standalone verification of the Wikcia Studio release manifest.

Run from a checked-out copy of this repository:
    python tests/verify_release_manifest.py

Checks structure, pinned payload hashes, and release-lock policy only — no
network access, no installation, no credentials touched.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest.json"
PAYLOADS = ("source.zip", "desktop.zip", "seed.zip", "bootstrap.zip")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    errors = []
    if not MANIFEST.is_file():
        print("FAIL: manifest.json is missing")
        return 1
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    if manifest.get("product") != "Wikcia Studio":
        errors.append("manifest product is not Wikcia Studio")
    if manifest.get("update_owner") != "Wikcia Studio":
        errors.append("update owner is not Wikcia Studio")
    if manifest.get("upstream_updates_allowed") is not False:
        errors.append("upstream updates are not disabled")

    payloads = manifest.get("payloads", {})
    for name in PAYLOADS:
        entry = payloads.get(name)
        if not isinstance(entry, dict):
            errors.append(f"payload {name} missing")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            errors.append(f"payload {name} sha256 not pinned")
        if not isinstance(entry.get("bytes"), int) or entry["bytes"] <= 0:
            errors.append(f"payload {name} bytes not recorded")

    if errors:
        print("FAIL")
        for error in errors:
            print(" -", error)
        return 1
    print("PASS: manifest.json is release-locked and payloads are pinned")
    return 0


import re  # noqa: E402  (kept local to avoid unused-import lint noise)

if __name__ == "__main__":
    sys.exit(main())
