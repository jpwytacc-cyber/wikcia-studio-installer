"""Installation-owned paths for Wikcia. Hermes remains an internal framework."""
from dataclasses import dataclass
import json
import ntpath
import os
from pathlib import Path


@dataclass(frozen=True)
class Installation:
    root: Path
    source: Path
    python: Path
    desktop: Path
    version: str


def load_installation(root):
    root = Path(root).resolve()
    marker = root / 'wikcia-product.json'
    if not marker.is_file():
        raise RuntimeError('Wikcia installation marker is missing; no Hermes fallback is allowed.')
    data = json.loads(marker.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or data.get('product') != 'wikcia-studio':
        raise ValueError('Not a supported Wikcia installation')
    paths = {}
    for field in ['source', 'python', 'desktop']:
        value = data.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError('Missing Wikcia path: ' + field)
        path = (root / value).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError('Wikcia path is outside its installation: ' + field)
        required = path / 'hermes_cli/main.py' if field == 'source' else path
        if not required.is_file():
            raise RuntimeError('Wikcia ' + field + ' is missing; repair this installation instead of falling back to Hermes.')
        paths[field] = path
    return Installation(root=root, version=str(data.get('version', 'unknown')), **paths)


def owned_environment(installation, inherited=None):
    env = dict(os.environ if inherited is None else inherited)
    root = installation.root
    # Clear path/ownership overrides, not approvals or unrelated provider policy.
    for key in ['PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'HERMES_DATA_DIR_SUFFIX', 'HERMES_DESKTOP_DEV_SERVER', 'HERMES_DESKTOP_REMOTE_URL', 'HERMES_DESKTOP_TMPDIR']:
        env.pop(key, None)
    for key in list(env):
        if key.startswith(('HERMES_SESSION_', 'HERMES_PARENT_', 'HERMES_RPC_', 'HERMES_BROWSER_CONTROL_')):
            env.pop(key)
    for key in ['HERMES_PROFILE', 'HERMES_UI_SESSION_ID', 'HERMES_KERNEL_DIR', 'HERMES_SPAWN', 'HERMES_GATEWAY_SESSION', 'HERMES_CRON_SESSION', 'HERMES_INTERACTIVE', 'HERMES_QUIET', 'HERMES_DESKTOP', 'HERMES_SERVE_HEADLESS']:
        env.pop(key, None)
    local = Path(env.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
    legacy = ntpath.normcase(ntpath.normpath(str(local / 'hermes')))
    old_paths = []
    for name in list(env):
        if name.casefold() == 'path':
            old_paths.extend(env.pop(name).split(';'))
    keep = []
    for entry in old_paths:
        normalized = ntpath.normcase(ntpath.normpath(entry))
        if entry and normalized != legacy and not normalized.startswith(legacy + '\\'):
            keep.append(entry)
    tools = root / 'tools'
    managed = [str(root / 'bin'), str(installation.source / '.hermes/bin')]
    facts = tools / 'facts.json'
    if facts.is_file():
        packages = json.loads(facts.read_text(encoding='utf-8')).get('packages', {})
        for name, record in packages.items():
            entry = record.get('entry', '')
            if not entry or Path(entry).name != entry:
                continue
            folder = tools / entry
            relative = 'cmd' if name == 'git' else 'bin' if name in {'ffmpeg', 'chromium'} else ''
            managed.append(str(folder / relative))
    scratch = root / 'cache/scratch'
    scratch.mkdir(parents=True, exist_ok=True)
    env.update(
        PATH=';'.join(dict.fromkeys([*managed, *keep])),
        HERMES_HOME=str(root), HERMES_REAL_HOME=str(root), HERMES_RUNTIME_DIR=str(tools),
        HERMES_WEB_DIST=str(installation.source / 'hermes_cli/web_dist'),
        HERMES_INSTALL_ROOT=str(installation.source), HERMES_SHARED_AUTH_DIR=str(root / 'shared'),
        HERMES_GATEWAY_LOCK_DIR=str(root / 'gateway-locks'), HERMES_CLI_PROG='wikcia',
        HERMES_NO_GLOBAL_INTEGRATION='1', HERMES_DESKTOP_ISOLATED_BACKEND='1',
        HERMES_DESKTOP_HERMES_ROOT=str(installation.source), HERMES_DESKTOP_PYTHON=str(installation.python),
        HERMES_DESKTOP_USER_DATA_DIR=str(root / 'desktop-user-data'),
        HERMES_DESKTOP_DASHBOARD_WEB_DIST=str(installation.source / 'hermes_cli/web_dist'),
        TMPDIR=str(scratch), TMP=str(scratch), TEMP=str(scratch),
        PYTHONUTF8='1', PYTHONIOENCODING='utf-8', WIKCIA_INSTALLATION_ROOT=str(root),
    )
    return env


def product_update_status(installation):
    return {'product': 'Wikcia Studio', 'owner': 'Wikcia Studio', 'version': installation.version, 'installation': str(installation.root), 'mechanism': 'external', 'upstream_updates_allowed': False, 'online_version_checked': False, 'message': 'Install updates from a verified Wikcia standalone release. Automatic upstream Hermes updates are deliberately disabled.'}
