"""Native installation operations; no inference, account copying or service auto-start."""
import os
import subprocess
from pathlib import Path


def run(argv, cwd, log, env=None, capture=False, timeout=3600):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as stream:
        stream.write('\nCOMMAND ' + subprocess.list2cmdline([str(a) for a in argv]) + '\n')
        stream.flush()
        if capture:
            result = subprocess.run([str(a) for a in argv], check=False, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            stream.write(result.stdout)
        else:
            result = subprocess.run([str(a) for a in argv], check=False, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        stream.write('\nEXIT ' + str(result.returncode) + '\n')
    if result.returncode:
        raise RuntimeError('Command failed (exit ' + str(result.returncode) + '); see ' + str(log))
    return result.stdout if capture else ''


def isolated_env(root):
    root = Path(root).resolve()
    env = os.environ.copy()
    for name in list(env):
        if name.startswith(('HERMES_', '__HERMES')) or name in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}:
            env.pop(name, None)
    env.update(HERMES_HOME=str(root), HERMES_RUNTIME_DIR=str(root / 'tools'),
               HERMES_NO_GLOBAL_INTEGRATION='1',
               HERMES_SHARED_AUTH_DIR=str(root / 'shared'), HERMES_GATEWAY_LOCK_DIR=str(root / 'gateway-locks'),
               HERMES_INSTALL_ROOT=str(root / 'hermes-agent'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    paths = [str(root / 'bootstrap/uv')]
    for pattern in ['git*/cmd', 'node-*', 'ffmpeg*/bin', 'ripgrep-*']:
        paths.extend(str(p) for p in (root / 'tools').glob(pattern) if p.is_dir())
    env['PATH'] = os.pathsep.join(paths) + os.pathsep + env.get('PATH', '')
    return env


def reuse_existing_tools(root, manifest, log):
    import json
    import shutil
    original = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'hermes/tools'
    destination = root / 'tools'
    if not (original / 'facts.json').is_file():
        return
    destination.mkdir(parents=True, exist_ok=True)
    facts = json.loads((original / 'facts.json').read_text(encoding='utf-8'))
    pins = json.loads((root / 'hermes-agent/pm/lock.json').read_text(encoding='utf-8')).get('packages', {})
    selected = {}
    for name, record in facts.get('packages', {}).items():
        entry = record.get('entry')
        if not entry or Path(entry).name != entry or name not in pins:
            continue
        if str(record.get('version')) != str(pins[name].get('version')):
            continue
        source = original / entry
        target = destination / entry
        if not source.is_dir():
            continue
        if not target.exists():
            print('Reusing existing verified tool files: ' + name, flush=True)
            shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        selected[name] = record
    if selected and not (destination / 'facts.json').exists():
        facts['packages'] = selected
        (destination / 'facts.json').write_text(json.dumps(facts, indent=2), encoding='utf-8')


def install_core(root, manifest, log):
    root = Path(root)
    repo = root / 'hermes-agent'
    python = root / 'bootstrap/python/python.exe'
    if not python.is_file():
        raise RuntimeError('Bundled Python is missing. Extract the complete ZIP before installation.')
    reuse_existing_tools(root, manifest, log)
    env = isolated_env(root)
    env['PYTHONPATH'] = str(repo)
    args = [python, '-m', 'pm.cli', 'install']
    for extra in manifest.get('core_extras', []):
        args += ['--extra', extra]
    print('Preparing Wikcia runtime and missing native tools. Details: ' + str(log), flush=True)
    run(args, repo, log, env=env)
    disabled_ui = validate_desktop_plugins(root, manifest, strict=True)
    # PM's own publisher owns interpreter binding and dependency leases.
    run([python, '-m', 'hermes_cli._launchers', '--help'], repo, log, env=env, capture=True)
    publish_entrypoints(root)
    cli = root / 'bin/wikcia.cmd'
    run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(cli), '--version'], root, log, env=isolated_env(root), capture=True)
    for plugin in manifest.get('plugins', []):
        run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(cli), 'plugins', 'enable', plugin], root, log, env=isolated_env(root))
    for plugin in manifest.get('plugins', []):
        run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(cli), 'plugins', 'doctor', plugin, '--ci'], root, log, env=isolated_env(root))
    return {'status': 'installed', 'cli': str(cli), 'desktop': str(root / 'Desktop/Wikcia Studio.exe'), 'disabled_legacy_ui': disabled_ui, 'functional_chat': 'authentication required on recipient computer'}


def validate_desktop_plugins(root, manifest, strict=False):
    import json
    import shutil
    rows = []
    node = tool(root, 'node')
    for name in manifest.get('plugins', []):
        candidates = [root / 'desktop-plugins' / name / 'plugin.js', root / 'plugins' / name / 'desktop/plugin.js']
        for path in candidates:
            if not path.is_file():
                continue
            checked = subprocess.run([node, '--input-type=module', '--check'], input=path.read_text(encoding='utf-8'), check=False, capture_output=True, text=True, encoding='utf-8', timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if checked.returncode == 0:
                continue
            if strict:
                raise RuntimeError('Desktop plugin is invalid: '+name+'; installation cannot be marked complete. '+checked.stderr[:800])
            from installer import sha256
            stem = 'legacy' if 'desktop-plugins' in path.parts else 'package'
            destination = root / 'disabled-ui-sources' / name / (stem + '-' + sha256(path)[:16] + '.js')
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                path.unlink()  # duplicate of the already-preserved failing source
            else:
                shutil.move(str(path), str(destination))
            row = {'plugin': name, 'reason': 'Pre-existing JavaScript syntax error; backend plugin remains installed', 'preserved_source': str(destination), 'syntax_error': checked.stderr[:1500]}
            rows.append(row)
            print('LEGACY PANEL DISABLED: ' + name + ' (source retained; backend available)', flush=True)
    if rows:
        (root / 'install-logs').mkdir(parents=True, exist_ok=True)
        (root / 'install-logs/disabled-legacy-panels.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    return rows


def publish_entrypoints(root):
    from wikcia_setup import publish_owned_entrypoints
    return publish_owned_entrypoints(root)


def install_component(component, root, manifest, log):
    from installer import download, extract_zip
    root = Path(root)
    kind = component['kind']
    if kind in {'python', 'python-source', 'comfyui'}:
        return install_python(component, root, manifest, log)
    if kind in {'npm', 'npm-source'}:
        return install_node(component, root, manifest, log)
    if kind == 'winget':
        return install_winget(component, root, log)
    folder = root / component['destination']
    if kind not in {'portable', 'portable-7z'}:
        raise ValueError('Unsupported component kind: ' + kind)
    suffix = '.7z' if kind == 'portable-7z' else '.zip'
    archive = download(component['url'], root / 'downloads' / (component['id'] + suffix), component['sha256'])
    if kind == 'portable-7z':
        # Windows 11 includes libarchive tar; no Store/winget/7-Zip installation required.
        tar = Path(os.environ.get('SYSTEMROOT', 'C:/Windows')) / 'System32/tar.exe'
        listing = run([tar, '-tf', archive], root, log, capture=True)
        for name in listing.splitlines():
            parts = name.replace('\\', '/').split('/')
            destination = (folder / name).resolve()
            if not destination.is_relative_to(folder.resolve()) or any(p == '..' or ':' in p for p in parts):
                raise ValueError('Unsafe native archive entry: ' + name)
        verbose = run([tar, '-tvf', archive], root, log, capture=True)
        if any(line and line[0] not in {'-', 'd'} for line in verbose.splitlines()):
            raise ValueError('Native archive contains unsupported link/special entries')
        folder.mkdir(parents=True, exist_ok=True)
        run([tar, '-xf', archive, '-C', folder], root, log)
    else:
        extract_zip(archive, folder)
    matches = sorted(folder.rglob(component['expected']))
    if not matches:
        raise RuntimeError('Expected component executable missing: ' + component['id'])
    executable = matches[0]
    gui = next(folder.rglob(component.get('gui', component['expected'])), None)
    return {'executable': str(executable), 'installation_path': str(executable.parent),
            'gui_executable': str(gui) if gui else None, 'version': component.get('version'),
            'functional_test': 'not run'}


def tool(root, name):
    import shutil
    if name == 'uv':
        candidate = root / 'bootstrap/uv/uv.exe'
        if candidate.is_file():
            return str(candidate)
    preferred = 'cmd/git.exe' if name == 'git' else name + '.exe'
    candidates = list((root / 'tools').glob(name + '*/' + preferred))
    if not candidates:
        candidates = list((root / 'tools').glob(name + '*/**/' + name + '.exe'))
    if candidates:
        return str(candidates[0])
    found = shutil.which(name)
    if found:
        return found
    raise RuntimeError('Required tool not available: ' + name)


def clone(component, folder, root, log):
    import re
    from urllib.parse import urlsplit
    parsed = urlsplit(component['repository'])
    if parsed.scheme != 'https' or parsed.hostname not in {'github.com', 'codeberg.org'} or parsed.username or parsed.password:
        raise ValueError('Repository must be an allowlisted public HTTPS source')
    revision = component['revision']
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('An exact repository commit is required')
    git = tool(root, 'git')
    env = isolated_env(root)
    args = [git, '-c', 'credential.helper=', '-c', 'credential.interactive=false']
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / '.git').is_dir():
        try:
            current = run(args + ['rev-parse', '--verify', 'HEAD'], folder, log, env=env, capture=True).strip()
        except RuntimeError:
            current = None  # interrupted fetch/checkout in this installer-owned directory
        if current and current != revision:
            raise RuntimeError('Existing repository revision differs; refusing to overwrite: ' + str(folder))
        if current and any((folder / name).is_file() for name in ['pyproject.toml', 'setup.py', 'package.json', 'main.py']):
            return
        origin = run(args + ['config', '--get', 'remote.origin.url'], folder, log, env=env, capture=True).strip()
        if origin != component['repository']:
            raise RuntimeError('Existing repository origin differs; not overwriting')
    else:
        if any(folder.iterdir()):
            raise RuntimeError('Nonempty source directory has no Git identity; not overwriting: ' + str(folder))
        run(args + ['init'], folder, log, env=env)
        run(args + ['remote', 'add', 'origin', component['repository']], folder, log, env=env)
    run(args + ['fetch', '--depth', '1', 'origin', revision], folder, log, env=env, timeout=1200)
    if component['id'] == 'searxng':
        # Git validates every index name before sparse filtering on Windows.
        # Export the pinned tree instead and omit only Linux :socket templates.
        import zipfile

        from installer import download, extract_zip
        archives = root / 'downloads'
        archives.mkdir(parents=True, exist_ok=True)
        pin = component['source_archive']
        archive = download(pin['url'], archives / 'searxng-source.zip', pin['sha256'])
        safe_archive = archives / 'searxng-source-windows.zip'
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(safe_archive, 'w') as output:
            for entry in source.infolist():
                name = entry.filename.partition('/')[2]
                if not name or entry.is_dir() or ((entry.external_attr >> 16) & 0o170000) == 0o120000:
                    continue
                if name.startswith('utils/templates/') and name.endswith(':socket'):
                    continue
                output.writestr(name, source.read(entry))
        extract_zip(safe_archive, folder, preserve=True)
        run(args + ['update-ref', 'HEAD', revision], folder, log, env=env)
    else:
        run(args + ['checkout', '--detach', 'FETCH_HEAD'], folder, log, env=env)
    actual = run(args + ['rev-parse', 'HEAD'], folder, log, env=env, capture=True).strip()
    if actual != revision:
        raise RuntimeError('Repository revision verification failed')


def install_python(component, root, manifest, log):
    folder = root / component['destination']
    if component['kind'] in {'python-source', 'comfyui'}:
        clone(component, folder, root, log)
    folder.mkdir(parents=True, exist_ok=True)
    uv = tool(root, 'uv')
    env = isolated_env(root)
    env['UV_PYTHON_INSTALL_DIR'] = str(root / 'software/python')
    env['UV_CACHE_DIR'] = str(root / 'cache/uv')
    env['HF_HUB_OFFLINE'] = '1'
    env['TRANSFORMERS_OFFLINE'] = '1'
    python = folder / '.venv/Scripts/python.exe'
    if not python.is_file():
        run([uv, 'python', 'install', component['python']], root, log, env=env)
        run([uv, 'venv', '--python', component['python'], str(folder / '.venv')], root, log, env=env)
    if component['kind'] == 'python-source':
        # SearXNG setup imports searx before declaring dependencies.
        run([uv, 'pip', 'install', '--python', str(python), '-r', str(folder / 'requirements.txt'), 'setuptools', 'wheel'], folder, log, env=env)
        packages = ['--no-build-isolation', '-e', str(folder)]
    elif component['kind'] == 'comfyui':
        packages = ['-r', str(folder / 'requirements.txt')]
    else:
        packages = component['packages']
    run([uv, 'pip', 'install', '--python', str(python), *packages], folder, log, env=env)
    if component.get('module'):
        code = 'import importlib; importlib.import_module(' + repr(component['module']) + '); print("IMPORT_OK")'
        output = run([python, '-c', code], folder, log, env=env, capture=True, timeout=240)
        if 'IMPORT_OK' not in output:
            raise RuntimeError('Installed Python component import did not complete')
    if component['id'] == 'searxng':
        import secrets
        config = folder / 'config/settings.yml'
        if not config.exists():
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text('use_default_settings: true\nserver:\n  bind_address: "127.0.0.1"\n  port: 8088\n  secret_key: "' + secrets.token_hex(32) + '"\nsearch:\n  formats:\n    - html\n    - json\n', encoding='utf-8')
    executable = folder / 'main.py' if component['kind'] == 'comfyui' else python
    return {'executable': str(executable), 'python_executable': str(python), 'installation_path': str(folder), 'version': component.get('version'), 'functional_test': 'Python import passed' if component.get('module') else 'not run', 'model_downloads': False}


def node_runtime(root, manifest, log):
    from installer import download, extract_zip
    folder = root / 'software/node24'
    node = next(folder.glob('*/node.exe'), None) if folder.exists() else None
    if not node:
        archive = download(manifest['node24']['url'], root / 'downloads/node24.zip', manifest['node24']['sha256'])
        extract_zip(archive, folder)
        node = next(folder.glob('*/node.exe'), None)
    if not node:
        raise RuntimeError('Compatible Node 24 runtime missing')
    env = isolated_env(root)
    env['PATH'] = str(node.parent) + os.pathsep + str(Path(tool(root, 'git')).parent) + os.pathsep + env.get('PATH', '')
    npm = [str(node), str(node.parent / 'node_modules/npm/bin/npm-cli.js')]
    run([node, '--version'], root, log, env=env, capture=True)
    return npm, env


def apply_repository_patch(component, folder, root, log):
    if not component.get('patch'):
        return
    patch = (root / component['patch']).resolve()
    if not patch.is_relative_to(root.resolve()) or not patch.is_file():
        raise RuntimeError('Verified repository patch is missing')
    git = tool(root, 'git')
    env = isolated_env(root)
    try:
        run([git, 'apply', '--reverse', '--check', str(patch)], folder, log, env=env, capture=True)
        return  # the exact patch is already present
    except RuntimeError:
        pass
    run([git, 'apply', '--check', str(patch)], folder, log, env=env)
    run([git, 'apply', str(patch)], folder, log, env=env)


def install_node(component, root, manifest, log):
    folder = root / component['destination']
    npm, env = node_runtime(root, manifest, log)
    if component['kind'] == 'npm-source':
        clone(component, folder, root, log)
        apply_repository_patch(component, folder, root, log)
        command = 'ci' if (folder / 'package-lock.json').is_file() else 'install'
        run(npm + [command, '--no-audit', '--no-fund'], folder, log, env=env)
        run(npm + ['run', 'build'], folder, log, env=env)
    else:
        folder.mkdir(parents=True, exist_ok=True)
        run(npm + ['install', '--prefix', str(folder), '--no-audit', '--no-fund', component['package']], folder, log, env=env)
    executable = folder / component['package_path']
    if not executable.is_file():
        raise RuntimeError('Installed Node entry point missing: ' + component['id'])
    installation = executable.parent.parent if component['kind'] == 'npm' else executable.parent
    return {'executable': str(executable), 'installation_path': str(installation), 'functional_test': 'build passed' if component['kind'] == 'npm-source' else 'entry point present; inference not tested'}


def discover(root, seed_archive=None):
    import sys
    source=root/'plugins/wikcia-apps'
    if source.is_dir():
        sys.path.insert(0,str(source))
    elif seed_archive:
        sys.path.insert(0,str(seed_archive)+'/plugins/wikcia-apps')
    else:
        raise RuntimeError('Application discovery source is missing')
    from hub.discovery import scan
    rows, evidence = scan(root, scan_system=True)
    return {row['id']: row for row in rows}, evidence


def install_winget(component, root, log):
    import shutil
    winget = shutil.which('winget')
    if not winget:
        raise RuntimeError('Windows App Installer/winget is missing; install App Installer from Microsoft Store and rerun this installer.')
    run([winget, 'install', '--exact', '--id', component['winget'], '--source', 'winget', '--silent', '--disable-interactivity', '--accept-package-agreements', '--accept-source-agreements'], root, log, timeout=3600)
    rows, _ = discover(root)
    row = rows.get(component['id'], {})
    if not row.get('executable') or not Path(row['executable']).is_file():
        raise RuntimeError('Package manager completed, but the application executable was not found; check ' + str(log))
    return {k: row.get(k) for k in ['executable', 'gui_executable', 'installation_path', 'version', 'python_executable']}


def prepare_browser(component, details, root, manifest, log):
    """Playwright's package install does not install its browser binaries."""
    if component['id'] == 'crawl4ai':
        python = details.get('python_executable') or details['executable']
        run([python, '-m', 'playwright', 'install', 'chromium'], root, log, env=isolated_env(root), timeout=1800)
    elif component['id'] == 'playwright-node':
        package = Path(details['executable'])
        cli = package.parent / 'cli.js'
        if not cli.is_file():
            raise RuntimeError('Playwright browser installer is missing: ' + str(cli))
        npm, env = node_runtime(root, manifest, log)
        run([npm[0], str(cli), 'install', 'chromium'], root, log, env=env, timeout=1800)


def install_extra_suite(root, manifest, want=None):
    import json

    from installer import plan_components
    discovered, _evidence = discover(root)
    plan = plan_components(manifest['components'], root, discovered)
    (root / 'component-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    maps = {}
    previous = root / 'installed-components.json'
    if previous.exists():
        maps = json.loads(previous.read_text(encoding='utf-8'))
    maps.update({'wikcia': {'executable': str(root / 'hermes-agent/pyproject.toml'), 'installation_path': str(root / 'hermes-agent')}, 'wikcia-cli': {'executable': str(root / 'bin/wikcia.cmd'), 'installation_path': str(root / 'bin')}, 'wikcia-desktop': {'executable': str(root / 'Desktop/Wikcia Studio.exe'), 'gui_executable': str(root / 'Desktop/Wikcia Studio.exe'), 'installation_path': str(root / 'Desktop')}})
    reports = []
    for component, action in zip(manifest['components'], plan):
        aid = component['id']
        if want is not None and aid not in want:
            print('SKIP ' + component['name'], flush=True)
            reports.append({'id': aid, 'name': component['name'], 'status': 'skipped', 'repository': component.get('repository')})
            continue
        print(('REUSE ' if action['action'] == 'reuse' else 'DOWNLOAD/INSTALL ') + component['name'], flush=True)
        row = {'id': aid, 'name': component['name'], 'status': 'failed', 'repository': component.get('repository')}
        try:
            if action['action'] == 'reuse':
                details = {k: action['existing'].get(k) for k in ['executable', 'installation_path', 'gui_executable', 'python_executable', 'version']}
                row.update(status='reused', functional_test='not run')
            else:
                details = install_component(component, root, manifest, root / 'install-logs' / (aid + '.log'))
                row.update(status='installed', functional_test=details.get('functional_test', 'not run'))
            prepare_browser(component, details, root, manifest, root / 'install-logs' / (aid + '-browser.log'))
            if aid=='comfyui':
                python=details.get('python_executable') or str(Path(details['installation_path'])/'.venv/Scripts/python.exe')
                available=run([python,'-c','import json,torch;print(json.dumps({"cuda":torch.cuda.is_available()}))'],root,root/'install-logs/comfyui-hardware.log',env=isolated_env(root),capture=True,timeout=60)
                details['python_executable']=python
                details['cpu_only']=not json.loads(available)['cuda']
            maps[aid] = details
            if aid == 'crawl4ai':
                maps['playwright'] = details.copy()
            row['location'] = details.get('installation_path')
            previous.write_text(json.dumps(maps, indent=2), encoding='utf-8')
        except Exception as exc:  # noqa: BLE001 -- record this component's failure and continue independent installs
            row['error'] = str(exc)
            print('NEEDS ATTENTION: ' + aid + ': ' + str(exc), flush=True)
        reports.append(row)
        (root / 'component-progress.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    cli = root / 'bin/wikcia.cmd'
    run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(cli), 'apps', 'discover', '--json'], root, root / 'install-logs/hub-discovery.log', env=isolated_env(root))
    return reports


def configure_product(root, manifest):
    import json
    root=Path(root).resolve()
    required=['software/design-station/server.mjs','software/design-station/website.mjs','software/design-station/hermes/lpx_swarm/router.py','software/wikcia-lead-intelligence/wlie/engine.py','software/wikcia-lead-intelligence/wlie/browser_worker.cjs','plugins/love-and-pixels/studio/generate.mjs','plugins/love-and-pixels/studio/site-build.mjs']
    missing=[name for name in required if not (root/name).is_file()]
    if missing:
        raise RuntimeError('Required product source is missing: '+', '.join(missing))
    roles=list((root/'agents').rglob('*.json'))
    expected=manifest.get('product_contract',{}).get('roles',23)
    if len(roles)<expected:
        raise RuntimeError('Required agent role cards are missing')
    node=Path(tool(root,'node'))
    metadata={'station':'software/design-station','node':node.relative_to(root).as_posix() if node.is_relative_to(root) else str(node)}
    (root/'lpx-product.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    models=[row['model'] for row in manifest.get('local_models',[])]
    selected=next((name for name in models if ':9b' in name),models[0] if models else None)
    if selected:
        cli=root/'bin/wikcia.cmd'
        for key,value in [('local_url','http://127.0.0.1:11434/v1'),('local_model',selected)]:
            run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',str(cli),'config','set','plugins.entries.hermes-prime.settings.'+key,value],root,root/'install-logs/product-configuration.log',env=isolated_env(root))
    return {'roles':len(roles),'station':metadata['station'],'local_worker_model':selected,'accounts':'Recipient authentication required; no source credentials or consent grants copied'}


def integrate_windows(root, shortcuts=True, user_path=True):
    root = Path(root).resolve()
    sandbox_parts = {'acceptance', 'acceptance-home', 'test-home', 'ui-parity'}
    if (any(part.casefold() in sandbox_parts for part in root.parts)
            or (root / '.wikcia-no-global-integration').is_file()
            or os.environ.get('HERMES_NO_GLOBAL_INTEGRATION') == '1'):
        return {'status': 'skipped', 'reason': 'sandbox-home'}
    if user_path:
        import winreg
        folder = str(root / 'bin')
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            try:
                current, kind = winreg.QueryValueEx(key, 'Path')
            except FileNotFoundError:
                current, kind = '', winreg.REG_EXPAND_SZ
            if folder.lower() not in [p.rstrip('\\/').lower() for p in current.split(';')]:
                winreg.SetValueEx(key, 'Path', 0, kind, current.rstrip(';') + ';' + folder)
        import ctypes
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(0xffff, 0x001a, 0, 'Environment', 2, 5000, ctypes.byref(result))
    if shortcuts:
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        script = "$ErrorActionPreference='Stop'; $w=New-Object -ComObject WScript.Shell; "
        script += "$menu=Join-Path ([Environment]::GetFolderPath('Programs')) 'Wikcia Studio'; New-Item -ItemType Directory -Force -Path $menu | Out-Null; "
        targets = [("Wikcia Studio", root / 'recovery/runtime/pythonw.exe', '-I "' + str(root / 'recovery/launch.py') + '" desktop'), ("Wikcia CLI", Path(os.environ.get('COMSPEC', 'C:/Windows/System32/cmd.exe')), '/k ""' + str(root / 'bin/wikcia.cmd') + '""')]
        for name, target, arguments in targets:
            for directory in ["[Environment]::GetFolderPath('Desktop')", '$menu']:
                script += "$s=$w.CreateShortcut((Join-Path (" + directory + ') ' + quote(name + '.lnk') + ')); $s.TargetPath=' + quote(target) + '; $s.Arguments=' + quote(arguments) + '; $s.WorkingDirectory=' + quote(Path.home()) + '; $s.IconLocation=' + quote(str(root / 'Desktop/Wikcia Studio.exe') + ',0') + '; $s.Save(); '
        powershell = Path(os.environ.get('SYSTEMROOT', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        run([powershell, '-NoProfile', '-NonInteractive', '-Command', script], root, root / 'install-logs/shortcuts.log')
