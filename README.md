# Wikcia Studio Installer

Distribution repository for **Wikcia Studio** — the native AI creative and automation assistant built on a customized Hermes Agent foundation.

This repository is the source of truth for Wikcia Studio releases. The installer (`INSTALL-WIKCIA.cmd` / `setup.ps1`) connects here to download verified payloads and the release manifest.

## What this repo contains

- Installer entry points: `INSTALL-WIKCIA.cmd`, `setup.ps1`
- Installer engine: `installer.py`, `install_engine.py`, `asset_setup.py`, `launch.py`
- Wikcia-owned release lock and recovery: `core/wikcia_release.py`, `control/wikcia_recovery.py`, `control/wikcia_boot.py`
- Interface contract: `FEATURES.json`, `FIRST-RUN.txt`
- Wikcia persona/operating prompt: `WIKCIA-SOUL.md`
- Release manifest with pinned SHA-256 hashes: `manifest.json`
- Regression tests: `tests/`

## What this repo does NOT contain

- Large binary payloads (`source.zip`, `desktop.zip`, `seed.zip`) — distributed as GitHub Release assets
- The bundled Python runtime (`bootstrap/`) — downloaded at setup time from pinned URLs
- Credentials, sessions, private state, or user data

## How the installer uses this repository

1. Clone or download this repository.
2. Run `INSTALL-WIKCIA.cmd` (Windows) or `setup.ps1` (PowerShell).
3. The installer reads `manifest.json` for pinned payload URLs and SHA-256 hashes.
4. Payloads are downloaded from GitHub Release assets and verified against their hashes before installation.
5. Wikcia-owned release lock prevents upstream Hermes updates; launch-time recovery restores verified application files.

## Release policy

- **No automatic upstream Hermes updates.** Updates are owned by Wikcia Studio only.
- **Same-release self-healing.** Launch-time recovery checks explicitly checkpointed application files against a verified checkpoint.
- **Recipient-owned accounts.** No credentials, subscriptions, or inference-consent grants are included. You authenticate your own model providers.

## Security

This is a **private** repository. Do not change visibility without explicit authorization. Credentials and secrets must never be committed.

## Tagline

"Imagine anything. Make it real."
