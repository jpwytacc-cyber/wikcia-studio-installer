"""Independent launch-time recovery gate, before the application's imports."""
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import controller


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in [['recovery'], ['health']]:
        action = args[1] if len(args) > 1 else 'status'
        if action not in {'status', 'check', 'repair'}:
            raise controller.RecoveryError('Use recovery status, check or repair')
        return controller.main(['--root', str(ROOT), action, '--json'])
    if (ROOT/'RELEASE_LOCK.json').is_file():
        result = controller.ensure_healthy(ROOT)
        if result['status'] == 'RECOVERED':
            print('Wikcia restored its verified application files before launch.', file=sys.stderr)
    else:
        print('Wikcia recovery is not initialized; complete the approved installer.', file=sys.stderr)
    executable = ROOT/'bootstrap/python/python.exe'
    if not executable.is_file():
        raise controller.RecoveryError('Application bootstrap is missing; run recovery repair')
    env = dict(os.environ)
    for name in ['PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV']:
        env.pop(name, None)
    return subprocess.call([str(executable), '-I', str(ROOT/'wikcia_entry.py'), *args], cwd=ROOT, env=env)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, controller.RecoveryError) as error:
        result = {'status': 'SAFE_MODE', 'message': str(error)}
        try:
            controller._atomic_json(HERE/'last-launch-failure.json', result)
        except OSError:
            pass
        print(json.dumps(result), file=sys.stderr)
        raise SystemExit(2)
