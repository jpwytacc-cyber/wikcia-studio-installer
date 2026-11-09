"""Wikcia-owned installer integration. No inference, auth copying or global changes."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile


def _load(path):
    spec=importlib.util.spec_from_file_location('wikcia_recovery_setup',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stage_control(bundle, root, release_id):
    bundle,root=Path(bundle).resolve(),Path(root).resolve()
    source=bundle/'control'
    (root/'standalone').mkdir(parents=True,exist_ok=True)
    (root/'recovery').mkdir(parents=True,exist_ok=True)
    shutil.copy2(source/'entry.py',root/'wikcia_entry.py')
    shutil.copy2(source/'ownership.py',root/'standalone/ownership.py')
    shutil.copy2(source/'wikcia_recovery.py',root/'recovery/controller.py')
    shutil.copy2(source/'wikcia_boot.py',root/'recovery/launch.py')
    # Recovery stays bootable if the application's bootstrap or PM environment breaks.
    shutil.copytree(root/'bootstrap/python',root/'recovery/runtime',dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pdb','site-packages'))
    python='bootstrap/python/python.exe'
    facts=root/'tools/facts.json'
    if facts.is_file():
        entry=json.loads(facts.read_text(encoding='utf-8')).get('packages',{}).get('python',{}).get('entry')
        if entry and Path(entry).name==entry and (root/'tools'/entry/'python.exe').is_file():
            python='tools/'+entry+'/python.exe'
    marker={'schema':1,'product':'wikcia-studio','version':release_id,'source':'hermes-agent',
            'python':python,'desktop':'Desktop/Wikcia Studio.exe','default_profile':'default',
            'update_owner':'Wikcia Studio','update_mechanism':'external','shared_hermes_fallback':False}
    existing=root/'wikcia-product.json'
    if existing.exists():
        prior=json.loads(existing.read_text(encoding='utf-8'))
        if prior.get('product')!='wikcia-studio':raise RuntimeError('Refusing unrelated product marker')
    existing.write_text(json.dumps(marker,indent=2),encoding='utf-8')
    folder=root/'bin';folder.mkdir(exist_ok=True)
    for name,prefix in [('wikcia',''),('wikcia-desktop','desktop '),('wikcia-setup','setup ')]:
        command='@echo off\r\nsetlocal\r\n"%~dp0..\\recovery\\runtime\\python.exe" -I "%~dp0..\\recovery\\launch.py" '+prefix+'%*\r\nexit /b %errorlevel%\r\n'
        (folder/(name+'.cmd')).write_bytes(command.encode('ascii'))
    bash='#!/usr/bin/env bash\nset -e\nBASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"\nSCRIPT="$(cygpath -w "$BASE/recovery/launch.py")"\nexec "$BASE/recovery/runtime/python.exe" -I "$SCRIPT" "$@"\n'
    (folder/'wikcia').write_text(bash,encoding='utf-8',newline='\n')
    return marker


def publish_owned_entrypoints(root):
    root=Path(root)
    folder=root/'bin';folder.mkdir(exist_ok=True)
    for name,prefix in [('wikcia',''),('wikcia-desktop','desktop '),('wikcia-setup','setup ')]:
        text='@echo off\r\nsetlocal\r\n"%~dp0..\\recovery\\runtime\\python.exe" -I "%~dp0..\\recovery\\launch.py" '+prefix+'%*\r\nexit /b %errorlevel%\r\n'
        (folder/(name+'.cmd')).write_bytes(text.encode('ascii'))


def initialize_recovery(root, manifest):
    root=Path(root).resolve()
    controller=_load(root/'recovery/controller.py')
    if (root/'RELEASE_LOCK.json').exists():
        return controller.status(root)
    owned=json.loads((root/'wikcia-owned-files.json').read_text(encoding='utf-8'))['files']
    # Include the actually prepared runtime/tool closure, not another user's environment.
    for folder in ['tools','installs','bootstrap']:
        for p in (root/folder).rglob('*'):
            if p.is_file() and not p.is_symlink():
                rel=p.relative_to(root).as_posix()
                if any(part.startswith('.') for part in p.relative_to(root).parts):continue
                try:controller._owned(root,rel)
                except controller.RecoveryError:continue
                owned.append(rel)
    owned=sorted(set(owned))
    # Select the real owned dependency environment through normal bootstrap;
    # call the core directly to avoid recursive launch-time recovery locks.
    code='import sys,runpy;sys.path.insert(0,'+repr(str(root/'hermes-agent'))+');import hermes_bootstrap;sys.argv=["wikcia","--version"];runpy.run_module("hermes_cli.main",run_name="__main__")'
    health=[str(root/'bootstrap/python/python.exe'),'-I','-c',code]
    return controller.initialize(root,owned,manifest.get('release_id','wikcia-owned'),health_command=health)
