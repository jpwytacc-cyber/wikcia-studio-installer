"""Install the model assets present in the source system without copying accounts."""
import hashlib
import zipfile
from pathlib import Path


def model_plan(pins, installed):
    existing={row.get('name') or row.get('model'):row for row in installed}
    return [{**pin,'action':'reuse' if pin['model'] in existing else 'pull', 'existing_digest':existing.get(pin['model'],{}).get('digest')} for pin in pins]


def verify_translation_archive(path, expected_model_sha256):
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            parts=member.filename.replace('\\','/').split('/')
            if member.filename.startswith(('/', '\\')) or any(x=='..' or ':' in x for x in parts) or ((member.external_attr>>16)&0o170000)==0o120000:
                raise ValueError('Unsafe translation model archive')
        candidates=[m for m in archive.infolist() if m.filename.endswith('/model/model.bin') or m.filename=='model/model.bin']
        if len(candidates)!=1:
            raise ValueError('Translation archive must contain exactly one model')
        digest=hashlib.sha256()
        with archive.open(candidates[0]) as source:
            for block in iter(lambda:source.read(4*1024*1024),b''):
                digest.update(block)
        if digest.hexdigest()!=expected_model_sha256:
            raise ValueError('Translation model content checksum mismatch')


def _ollama_json(path, body=None, timeout=10):
    import json
    import urllib.request
    request=urllib.request.Request('http://127.0.0.1:11434'+path, data=json.dumps(body).encode() if body is not None else None, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=timeout) as response:
        return json.load(response)


def ensure_ollama(root, paths):
    try:
        return _ollama_json('/api/tags')['models']
    except (OSError,ValueError,KeyError):
        import os
        import shutil
        import subprocess
        import time
        executable=paths.get('ollama',{}).get('executable') or shutil.which('ollama')
        if not executable:
            candidate=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Ollama/ollama.exe'
            executable=str(candidate) if candidate.is_file() else None
        if not executable:
            raise RuntimeError('Ollama executable was not found after installation')
        (root/'install-logs').mkdir(parents=True,exist_ok=True)
        with (root/'install-logs/ollama-start.log').open('ab') as log:
            subprocess.Popen([executable,'serve'],env={**os.environ,'OLLAMA_HOST':'127.0.0.1:11434'},stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(40):
            time.sleep(.5)
            try:
                return _ollama_json('/api/tags')['models']
            except (OSError,ValueError,KeyError):
                pass
        raise RuntimeError('Ollama did not become ready on loopback')


def _free_space(root, required):
    import shutil
    if shutil.disk_usage(root).free < required + 2*1024**3:
        raise RuntimeError('Insufficient free disk space for the missing model; existing files were not removed')


def _translation_packages(python, root):
    import json

    from install_engine import isolated_env, run
    code='import argostranslate.package as p,json;print(json.dumps([{\"from\":x.from_code,\"to\":x.to_code,\"version\":str(x.package_version),\"file\":str(next(x.package_path.rglob(\"model.bin\"),\"\"))} for x in p.get_installed_packages()]))'
    return json.loads(run([python,'-c',code],root,root/'install-logs/translation-assets.log',env=isolated_env(root),capture=True,timeout=60))


def _install_translation(pin, python, root):
    import shutil
    import urllib.request

    from install_engine import isolated_env, run
    path=root/'downloads/translation-models'/(pin['from']+'_'+pin['to']+'_'+pin['version']+'.argosmodel')
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.is_file():
        errors=[]
        for url in pin['links']:
            if not url.startswith('https://'):
                continue
            try:
                partial=path.with_suffix('.partial')
                offset=partial.stat().st_size if partial.is_file() else 0
                headers={'User-Agent':'WikciaStudio-Installer/1.0','Accept-Encoding':'identity'}
                if offset:
                    headers['Range']='bytes='+str(offset)+'-'
                request=urllib.request.Request(url,headers=headers)
                with urllib.request.urlopen(request,timeout=120) as source:
                    resumed=offset and source.status==206 and source.headers.get('Content-Range','').startswith('bytes '+str(offset)+'-')
                    with partial.open('ab' if resumed else 'wb') as output:
                        shutil.copyfileobj(source,output,1024*1024)
                partial.replace(path)
                break
            except OSError as exc:
                errors.append(type(exc).__name__)
        if not path.is_file():
            raise RuntimeError('Translation model download failed: '+','.join(errors))
    verify_translation_archive(path,pin['model_sha256'])
    run([python,'-c','import argostranslate.package,sys;argostranslate.package.install_from_path(sys.argv[1])',path],root,root/'install-logs/translation-assets.log',env=isolated_env(root),timeout=300)
    found=_translation_packages(python,root)
    match=next((r for r in found if (r['from'],r['to'],r['version'])==(pin['from'],pin['to'],pin['version'])),None)
    if not match:
        raise RuntimeError('Translation model installation could not be read back')
    from installer import sha256
    if not Path(match['file']).is_file() or sha256(match['file'])!=pin['model_sha256']:
        raise RuntimeError('Installed translation model checksum did not match')
    path.unlink(missing_ok=True)
    return match


def install_assets(root, manifest, paths):
    import json
    import shutil

    from install_engine import isolated_env, run
    from installer import download, sha256
    root=Path(root).resolve()
    root.mkdir(parents=True,exist_ok=True)
    rows=[]
    def save(row):
        rows.append(row)
        (root/'asset-progress.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    if manifest.get('local_models'):
        try:
            existing=ensure_ollama(root,paths)
        except Exception as exc:  # noqa: BLE001 -- persist this asset failure and continue independent assets
            existing=[]
            server_error=str(exc)
        else:
            server_error=None
        for pin in model_plan(manifest['local_models'],existing):
            row={'id':'ollama:'+pin['model'],'status':'failed'}
            try:
                if server_error:
                    raise RuntimeError(server_error)
                print(('REUSE MODEL ' if pin['action']=='reuse' else 'DOWNLOAD MODEL ')+pin['model'],flush=True)
                if pin['action']=='pull':
                    _free_space(root,pin['bytes'])
                    executable=paths.get('ollama',{}).get('executable') or shutil.which('ollama')
                    if not executable:
                        raise RuntimeError('Ollama CLI is required to download models')
                    run([executable,'pull',pin['model']],root,root/'install-logs/ollama-models.log',env=isolated_env(root),timeout=14400)
                    current=_ollama_json('/api/tags')['models']
                    actual=next((x for x in current if x.get('name')==pin['model']),None)
                    if not actual or actual.get('digest')!=pin['digest']:
                        raise RuntimeError('Downloaded model does not match the recorded source manifest digest')
                row.update(status='reused' if pin['action']=='reuse' else 'installed',digest=pin.get('existing_digest') or pin['digest'])
            except Exception as exc:  # noqa: BLE001 -- persist this asset failure and continue independent assets
                row['error']=str(exc)
            save(row)
    checkpoint=manifest.get('checkpoint')
    if checkpoint:
        row={'id':checkpoint['id'],'status':'failed'}
        try:
            folder=Path(paths.get('comfyui',{}).get('installation_path') or root/'software/comfyui')
            destination=folder/'models/checkpoints'/checkpoint['file']
            print('CHECK IMAGE MODEL '+checkpoint['file'],flush=True)
            if destination.is_file() and sha256(destination)==checkpoint['sha256']:
                row.update(status='reused',file=str(destination))
            else:
                if destination.exists():
                    destination=folder/'models/checkpoints'/('wikcia-'+checkpoint['sha256'][:12]+'.ckpt')
                _free_space(root,checkpoint['bytes'])
                url='https://huggingface.co/'+checkpoint['repository']+'/resolve/'+checkpoint['revision']+'/'+checkpoint['file']
                download(url,destination,checkpoint['sha256'])
                row.update(status='installed',file=str(destination))
        except Exception as exc:  # noqa: BLE001 -- persist this asset failure and continue independent assets
            row['error']=str(exc)
        save(row)
    pins=manifest.get('translation_models',[])
    if pins:
        python=paths.get('libretranslate',{}).get('python_executable') or paths.get('libretranslate',{}).get('executable')
        try:
            installed=_translation_packages(python,root) if python and Path(python).is_file() else []
        except Exception:  # noqa: BLE001 -- unavailable translation inventory is retried by the installer
            installed=[]
        for pin in pins:
            row={'id':'translation:'+pin['from']+'-'+pin['to']+'@'+pin['version'],'status':'failed'}
            try:
                if not python or not Path(python).is_file():
                    raise RuntimeError('LibreTranslate runtime is unavailable')
                matching=next((x for x in installed if (x['from'],x['to'],x['version'])==(pin['from'],pin['to'],pin['version'])),None)
                if matching and Path(matching['file']).is_file() and sha256(matching['file'])==pin['model_sha256']:
                    row['status']='reused'
                else:
                    print('DOWNLOAD TRANSLATION '+pin['from']+' → '+pin['to'],flush=True)
                    _free_space(root,pin['model_bytes']*2)
                    matching=_install_translation(pin,python,root)
                    installed.append(matching)
                    row['status']='installed'
            except Exception as exc:  # noqa: BLE001 -- persist this asset failure and continue independent assets
                row['error']=str(exc)
            save(row)
    return rows
