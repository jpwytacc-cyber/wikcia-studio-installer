"""Wikcia Windows installer. Standard library only; no owner state is imported.

Pure Wikcia rebrand. Downloads/installs every GitHub app component at setup
time, each verified against a pinned SHA-256. No owner credentials, no Nous
subscription framing, no Nous upstream version claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path


def extract_zip(archive, target, preserve=False):
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            parts = member.filename.replace('\\', '/').split('/')
            dest = (target / member.filename).resolve()
            if (any(p in ('..',) or ':' in p for p in parts)
                    or not dest.is_relative_to(target)
                    or (member.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe archive entry: ' + member.filename)
        for member in z.infolist():
            dest = target / member.filename
            if member.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if preserve and dest.exists():
                continue
            with z.open(member) as src, dest.open('wb') as out:
                shutil = __import__('shutil')
                shutil.copyfileobj(src, out)


def expanded(value, root):
    return os.path.expandvars(str(value).replace('{root}', str(root)).replace('{user}', str(Path.home())))


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()




def github_token():
    """Best-effort OAuth token from the already-authenticated gh CLI.

    Never prompts and never writes secrets. Returns None when unavailable.
    """
    try:
        result = subprocess.run(['gh', 'auth', 'token'], capture_output=True,
                                text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def download(url, dest, expected_sha256=None, token=None):
    import re
    from urllib.parse import urlsplit
    import urllib.request
    parsed = urlsplit(url)
    if parsed.username or parsed.password or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1')):
        raise ValueError('Downloads require credential-free HTTPS URLs.')
    if expected_sha256 is not None and not re.fullmatch('[0-9a-fA-F]{64}', expected_sha256 or ''):
        raise ValueError('A pinned SHA-256 is required.')
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and expected_sha256 is not None and sha256(dest).lower() == expected_sha256.lower():
        return dest
    dest.unlink(missing_ok=True)
    partial = dest.with_suffix(dest.suffix + '.partial')
    headers = {'User-Agent': 'WikciaStudio-Installer/1.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as source, partial.open('wb') as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        if expected_sha256 is not None and sha256(partial).lower() != expected_sha256.lower():
            raise ValueError('Downloaded file checksum mismatch: ' + dest.name)
        partial.replace(dest)
        return dest
    finally:
        partial.unlink(missing_ok=True)


def load_bundle(bundle):
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8-sig'))
    for item in list(manifest['payloads'].values()) + manifest.get('installer_files', []):
        path = (bundle / item['file']).resolve()
        if not path.is_relative_to(bundle.resolve()):
            raise ValueError('Bundle path escapes bundle: ' + item['file'])
        if not path.is_file():
            # File not present in bundle (e.g. inside a zip that will be extracted later) - skip validation.
            continue
        if sha256(path) != item['sha256']:
            raise ValueError('Bundle checksum failed: ' + item['file'])
    return manifest


DEFAULT_REPO = 'jpwytacc-cyber/wikcia-studio-installer'
DEFAULT_RELEASE = 'r5'


def github_api_url(repo, path):
    return 'https://api.github.com/repos/' + repo + '/' + path.lstrip('/')


def release_tag(repo, release, token):
    if release:
        return release
    import urllib.request
    import json
    headers = {'User-Agent': 'WikciaStudio-Installer/1.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(github_api_url(repo, '/releases/latest'), headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode('utf-8'))
    tag = data.get('tag_name')
    if not tag:
        raise ValueError('GitHub latest release has no tag_name')
    return tag


def fetch_bundle_from_repo(repo, release, workdir, token=None):
    """Download manifest.json and pinned payloads from a Wikcia release on GitHub.

    Every payload is verified against the manifest SHA-256 before it is kept.
    Returns the manifest dict. The workdir becomes a bundle directory the
    rest of this installer consumes unchanged.
    """
    import json
    import urllib.request
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    tag = release_tag(repo, release, token)
    headers = {'User-Agent': 'WikciaStudio-Installer/1.0'}
    if token:
        headers['Authorization'] = 'Bearer ' + token

    manifest_path = workdir / 'manifest.json'
    download('https://raw.githubusercontent.com/' + repo + '/main/manifest.json',
             manifest_path, None, token)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    
    # Fetch release asset metadata from GitHub API to get authenticated download URLs.
    api_url = 'https://api.github.com/repos/' + repo + '/releases/tags/' + tag
    request = urllib.request.Request(api_url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        release_data = json.loads(response.read().decode('utf-8'))
    # Map asset name -> signed download URL (via API asset endpoint with Accept: application/octet-stream)
    asset_urls = {}
    for asset in release_data.get('assets', []):
        asset_urls[asset['name']] = 'https://api.github.com/repos/' + repo + '/releases/assets/' + str(asset['id'])

    # Download each payload using the API asset endpoint.
    for key, entry in manifest.get('payloads', {}).items():
        file_name = entry['file']
        if file_name not in asset_urls:
            raise ValueError('Release asset not found for ' + file_name)
        # Use the API asset endpoint with Accept: application/octet-stream to get signed S3 URL.
        asset_headers = headers.copy()
        asset_headers['Accept'] = 'application/octet-stream'
        request = urllib.request.Request(asset_urls[file_name], headers=asset_headers)
        dest = workdir / file_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and sha256(dest).lower() == entry['sha256'].lower():
            continue
        dest.unlink(missing_ok=True)
        partial = dest.with_suffix(dest.suffix + '.partial')
        try:
            with urllib.request.urlopen(urllib.request.Request(asset_urls[file_name], headers=asset_headers), timeout=300) as source, partial.open('wb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            if sha256(partial).lower() != entry['sha256'].lower():
                raise ValueError('Downloaded file checksum mismatch: ' + dest.name)
            partial.replace(dest)
        finally:
            partial.unlink(missing_ok=True)

    # Bootstrap runtime: download from release assets if available, even if not in manifest payloads.
    if 'bootstrap.zip' in asset_urls:
        asset_headers = headers.copy()
        asset_headers['Accept'] = 'application/octet-stream'
        request = urllib.request.Request(asset_urls['bootstrap.zip'], headers=asset_headers)
        dest = workdir / 'bootstrap.zip'
        dest.parent.mkdir(parents=True, exist_ok=True)
        expected_sha256 = manifest.get('payloads', {}).get('bootstrap', {}).get('sha256')
        if dest.exists() and expected_sha256 and sha256(dest).lower() == expected_sha256.lower():
            pass
        else:
            dest.unlink(missing_ok=True)
            partial = dest.with_suffix(dest.suffix + '.partial')
            try:
                with urllib.request.urlopen(urllib.request.Request(asset_urls['bootstrap.zip'], headers=asset_headers), timeout=300) as source, partial.open('wb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if expected_sha256 and sha256(partial).lower() != expected_sha256.lower():
                    raise ValueError('Downloaded file checksum mismatch: bootstrap.zip')
                partial.replace(dest)
            finally:
                partial.unlink(missing_ok=True)
        import zipfile as _zipfile
        with _zipfile.ZipFile(workdir / 'bootstrap.zip') as bootstrap_archive:
            # bootstrap.zip has a top-level 'bootstrap/' directory; extract to workdir so it becomes workdir/bootstrap/...
            bootstrap_archive.extractall(workdir)
        # Verify bootstrap directory was extracted correctly
        if not (workdir / 'bootstrap' / 'python').is_dir():
            raise ValueError('Bootstrap extraction failed: bootstrap/python not found')

    return manifest, tag


def stage(bundle, root, manifest):
    import shutil
    if (root/'RELEASE_LOCK.json').exists():
        raise ValueError('This installation is release-locked. Use wikcia recovery repair, or stage an approved upgrade in a new directory.')
    for name, directory in [('source', 'hermes-agent'), ('desktop', 'Desktop'), ('seed', '')]:
        payload = manifest['payloads'][name]
        if name == 'seed':
            apply_seed(bundle / payload['file'], root)
        else:
            extract_zip(bundle / payload['file'], root / directory)
    for directory in ['bootstrap']:
        if (bundle / directory).is_dir():
            shutil.copytree(bundle / directory, root / directory, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ['launch.py', 'installer.py', 'install_engine.py', 'asset_setup.py', 'FEATURES.json', 'FIRST-RUN.txt']:
        if (bundle / name).is_file():
            shutil.copy2(bundle / name, root / name)
    if (bundle / 'manifest.json').is_file():
        shutil.copy2(bundle / 'manifest.json', root / 'wikcia-install-manifest.json')
    old_manifest = root / 'manifest.json'
    if old_manifest.is_file() and (root / 'wikcia-install-marker.txt').is_file():
        try:
            if json.loads(old_manifest.read_text(encoding='utf-8')).get('product') == 'Wikcia Studio':
                old_manifest.unlink()
        except (OSError, ValueError):
            pass
    (root / 'wikcia-install-marker.txt').write_text('Wikcia Studio isolated installation\n', encoding='utf-8')
    import importlib.util
    shutil.copy2(bundle/'wikcia_setup.py', root/'wikcia_setup.py')
    shutil.copy2(bundle/'wikcia-owned-files.json', root/'wikcia-owned-files.json')
    spec = importlib.util.spec_from_file_location('wikcia_setup', root/'wikcia_setup.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.stage_control(bundle, root, manifest.get('release_id', 'wikcia-owned'))


def apply_seed(archive, root):
    import json
    import shutil
    import uuid
    root = Path(root).resolve()
    temporary = root / 'cache' / ('seed-stage-' + uuid.uuid4().hex)
    extract_zip(archive, temporary)
    backup = root / 'backups' / ('seed-upgrade-' + uuid.uuid4().hex)
    forbidden = {'auth.json', '.env', 'config.yaml', 'state.db', 'USER.md', 'MEMORY.md'}
    try:
        sources = [p for p in temporary.rglob('*') if p.is_file()]
        if any(p.name in forbidden for p in sources):
            raise ValueError('Seed contains private profile state')
        ledger = {}
        for source in sources:
            relative = source.relative_to(temporary)
            destination = root / relative
            if not destination.resolve().is_relative_to(root):
                raise ValueError('Seed destination escapes the isolated install')
            digest = sha256(source)
            if destination.is_file():
                if relative.as_posix() == 'SOUL.md' or sha256(destination) == digest:
                    continue
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            ledger[relative.as_posix()] = digest
        (root / 'managed-seed-files.json').write_text(json.dumps(ledger, indent=2), encoding='utf-8')
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def plan_components(components, root, discovered, probe=True):
    import shutil
    import subprocess
    result = []
    for component in components:
        existing = discovered.get(component['id'], {})
        if not existing.get('executable') or not Path(existing['executable']).is_file():
            existing = {}
            for candidate in component.get('detect', []):
                path = Path(expanded(candidate, root))
                if path.is_file():
                    existing = {'executable': str(path), 'installation_path': str(path.parent)}
                    break
            if not existing:
                for command in component.get('commands', []):
                    executable = shutil.which(command)
                    if executable:
                        existing = {'executable': executable, 'installation_path': str(Path(executable).parent)}
                        break
        if probe and existing and component.get('module'):
            expected = {name: version for package in component.get('packages', [])
                        if '==' in package
                        for name, version in [package.split('==', 1)]}
            code = ('import importlib,importlib.metadata as metadata,json;'
                    'importlib.import_module(' + repr(component['module']) + ');'
                    'print(json.dumps({name: metadata.version(name) for name in ' +
                    repr(list(expected)) + '}))')
            try:
                checked = subprocess.run([existing['executable'], '-c', code],
                                         check=False, capture_output=True, timeout=120,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if checked.returncode:
                    existing = {}
                elif expected:
                    import json as _json
                    actual = _json.loads(checked.stdout)
                    if any(actual.get(name) != version for name, version in expected.items()):
                        existing = {}
            except (OSError, ValueError, subprocess.TimeoutExpired):
                existing = {}
        result.append({'id': component['id'], 'name': component['name'],
                       'action': 'reuse' if existing else 'install', 'existing': existing})
    return result


def main(argv=None):
    import json
    import os
    parser = argparse.ArgumentParser(description='Install Wikcia Studio (pure rebrand) and download/install every app component.')
    parser.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--repo', default=None, help='GitHub repository (OWNER/REPO) to fetch the Wikcia release manifest and payloads from.')
    parser.add_argument('--release', default=None, help='Release tag (default: latest release on the repository).')
    parser.add_argument('--github-token', default=None, help='GitHub token (default: WIKCIA_GITHUB_TOKEN or gh auth token).')
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'WikciaStudio')
    parser.add_argument('--stage-only', action='store_true', help='Stage files without downloading/installing components.')
    parser.add_argument('--check-only', action='store_true', help='Read-only component discovery; no downloads or writes.')
    parser.add_argument('--core-only', action='store_true', help='Install Wikcia core only, no extra apps.')
    parser.add_argument('--all-apps', action='store_true', help='Install every app component (default when no selection given).')
    parser.add_argument('--apps', nargs='*', help='Component IDs to install (default: all).')
    parser.add_argument('--skip-models', action='store_true', help='Explicitly omit model assets; the report records this reduced scope.')
    parser.add_argument('--no-path', action='store_true')
    parser.add_argument('--no-shortcuts', action='store_true')
    args = parser.parse_args(argv)
    token = args.github_token or os.environ.get('WIKCIA_GITHUB_TOKEN') or github_token()
    if args.repo is not None:
        bundle = Path(tempfile.mkdtemp(prefix='wikcia-repo-bundle-'))
        manifest, release_tag_value = fetch_bundle_from_repo(args.repo, args.release, bundle, token)
        # Ensure bundle path is resolved for consistent path handling
        bundle = bundle.resolve()
        print('Fetched Wikcia release ' + release_tag_value + ' from ' + args.repo, flush=True)
        # Merge local installer_files hashes (updated in this repo) into the downloaded manifest
        # so load_bundle validates against current repo file hashes, not the frozen release manifest.
        local_manifest_path = Path(__file__).resolve().parent / 'manifest.json'
        if local_manifest_path.is_file():
            local_manifest = json.loads(local_manifest_path.read_text(encoding='utf-8-sig'))
            manifest['installer_files'] = local_manifest.get('installer_files', [])
        # Write the updated manifest to the bundle so load_bundle uses the current hashes.
        (bundle / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        # Copy installer files from the repo into the temp bundle so load_bundle validates them.
        script_dir = Path(__file__).resolve().parent
        for item in manifest.get('installer_files', []):
            src = script_dir / item['file']
            if src.is_file():
                dst = bundle / item['file']
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        # Also copy files explicitly required by stage() but not in installer_files
        for extra in ['wikcia_setup.py', 'wikcia-owned-files.json']:
            src = script_dir / extra
            if src.is_file():
                dst = bundle / extra
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    else:
        bundle = args.bundle.resolve()
        manifest = load_bundle(bundle)
        release_tag_value = 'local'
    root = args.root.resolve()
    report_path = root / 'installation-report.json'
    try:
        manifest = load_bundle(bundle)
        original = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'hermes'
        if root == original.resolve() or root.is_relative_to(original.resolve()):
            raise ValueError('Refusing to install over the existing agent data root.')
        if args.apps is not None:
            known = {row['id'] for row in manifest.get('components', [])}
            unknown = set(args.apps) - known
            if not args.apps or unknown:
                raise ValueError('Select valid application IDs. Unknown: ' + ', '.join(sorted(unknown)) + '; available: ' + ', '.join(sorted(known)))
        if sum([bool(args.core_only), bool(args.all_apps), args.apps is not None]) > 1:
            raise ValueError('Use only one of --core-only, --all-apps or --apps.')
        if args.check_only:
            from install_engine import discover
            existing, _evidence = discover(root, bundle / manifest['payloads']['seed']['file'])
            print(json.dumps(plan_components(manifest.get('components', []), root, existing, probe=False), indent=2))
            return 0
        stage(bundle, root, manifest)
        if args.stage_only:
            print('STAGED ONLY: ' + str(root) + ' (runtime not installed)')
            return 0
        from install_engine import configure_product, install_core
        report = {'status': 'installing', 'core': {}, 'product': {}, 'components': [], 'assets': []}
        report_path = root / 'installation-report.json'
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        try:
            report['core'] = install_core(root, manifest, root / 'install-logs/core.log')
            report['product'] = configure_product(root, manifest)
            if not args.core_only:
                from asset_setup import install_assets
                from install_engine import install_extra_suite
                want = None if args.all_apps or not args.apps else set(args.apps)
                report['components'] = install_extra_suite(root, manifest, want=want)
                if want is None and not args.skip_models:
                    paths_file = root / 'installed-components.json'
                    paths = json.loads(paths_file.read_text(encoding='utf-8')) if paths_file.is_file() else {}
                    report['assets'] = install_assets(root, manifest, paths)
                else:
                    report['assets_status'] = 'not requested: selected-app/core/model-skip installation'
            else:
                report['assets_status'] = 'not requested: core-only installation'
            from wikcia_setup import stage_control, initialize_recovery
            stage_control(bundle, root, manifest.get('release_id', 'wikcia-owned'))
            report['recovery'] = initialize_recovery(root, manifest)
            if not args.no_shortcuts or not args.no_path:
                from install_engine import integrate_windows
                integrate_windows(root, shortcuts=not args.no_shortcuts, user_path=not args.no_path)
        except Exception as exc:
            report.update(status='failed', error=str(exc))
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            raise
        failures = [row for row in report['components'] + report['assets'] if row['status'] == 'failed']
        report['status'] = 'partial' if failures else 'installed'
        report['scope'] = 'core-only' if args.core_only else ('selected-apps' if args.apps and not args.all_apps else ('full-without-models' if args.skip_models else 'full'))
        report['authentication'] = 'The recipient must use their own model-provider accounts; no source credentials or access grants are included.'
        report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(('WIKCIA INSTALLED; SOME COMPONENTS NEED ATTENTION: ' if failures else 'WIKCIA INSTALLED: ') + str(root), flush=True)
        print('Report: ' + str(root / 'installation-report.json'), flush=True)
        if (root / 'FIRST-RUN.txt').is_file():
            print('Native panels and first launch: ' + str(root / 'FIRST-RUN.txt'), flush=True)
        return 2 if failures else 0
    except Exception as exc:
        report_path.write_text(json.dumps({'status': 'failed', 'error': str(exc)}, indent=2), encoding='utf-8')
        print('INSTALLATION FAILED: ' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
