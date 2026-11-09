"""Prepare branded entrypoints after the supported installer built an own-root runtime."""
import argparse
import json
from pathlib import Path
import shutil


def prepare(root):
    root = Path(root).resolve()
    source = Path(__file__).resolve().parent
    facts = json.loads((root / 'tools/facts.json').read_text(encoding='utf-8'))
    python = Path('tools') / facts['packages']['python']['entry'] / 'python.exe'
    marker = {'schema': 1, 'product': 'wikcia-studio', 'version': '0.22.2-wikcia.1', 'source': 'hermes-agent', 'python': python.as_posix(), 'desktop': 'Desktop/Wikcia Studio.exe', 'default_profile': 'default', 'update_owner': 'Wikcia Studio', 'update_mechanism': 'external', 'shared_hermes_fallback': False}
    if not (root / python).is_file():
        raise RuntimeError('The product-owned Python is not installed')
    package = root / 'standalone'
    package.mkdir(exist_ok=True)
    shutil.copy2(source / 'ownership.py', package / 'ownership.py')
    shutil.copy2(source / 'entry.py', root / 'wikcia_entry.py')
    (root / 'wikcia-product.json').write_text(json.dumps(marker, indent=2), encoding='utf-8')
    (root / 'bin').mkdir(exist_ok=True)
    batch = '@echo off\r\nsetlocal\r\n"%~dp0..\\bootstrap\\python\\python.exe" -I "%~dp0..\\wikcia_entry.py" %*\r\nexit /b %errorlevel%\r\n'
    (root / 'bin/wikcia.cmd').write_bytes(batch.encode('ascii'))
    bash = '#!/usr/bin/env bash\nset -e\nBASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"\nSCRIPT="$(cygpath -w "$BASE/wikcia_entry.py")"\nexec "$BASE/bootstrap/python/python.exe" -I "$SCRIPT" "$@"\n'
    (root / 'bin/wikcia').write_text(bash, encoding='utf-8', newline='\n')
    (root / 'bin/wikcia').chmod(0o755)
    print('Prepared product-owned Wikcia launchers:', root / 'bin')
    return marker


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    prepare(parser.parse_args().root)
