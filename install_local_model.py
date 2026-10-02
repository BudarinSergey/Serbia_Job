"""Explicit one-time download; runtime never downloads models."""
import hashlib
import json
from pathlib import Path
import requests

REPO='jncraton/m2m100_418M-ct2-int8'
REVISION='7c1b2620a4e58dacecbd8bf89cfd6da7eb9eb7b0'
ROOT=Path(__file__).resolve().parent/'models'/'m2m100-int8'

def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()

def install():
    ROOT.mkdir(parents=True,exist_ok=True)
    response=requests.get(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}',params={'blobs':'true'},timeout=30)
    response.raise_for_status()
    files=response.json()['siblings']
    names={'model.bin','sentencepiece.bpe.model','config.json','shared_vocabulary.json','README.md'}
    for item in files:
        name=item['rfilename']
        if name not in names: continue
        path=ROOT/name
        expected=item.get('lfs',{}).get('sha256')
        if path.exists() and path.stat().st_size==item['size']:
            if not expected or checksum(path)==expected:
                continue
        tmp=path.with_suffix(path.suffix+'.part')
        digest=hashlib.sha256()
        with requests.get(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{name}',stream=True,timeout=(10,60)) as r:
            r.raise_for_status()
            with tmp.open('wb') as f:
                for chunk in r.iter_content(1024*1024):
                    f.write(chunk);digest.update(chunk)
        if tmp.stat().st_size!=item['size'] or (expected and digest.hexdigest()!=expected):
            raise ValueError('Model checksum mismatch')
        tmp.replace(path)
        print('Downloaded:',name,flush=True)
    (ROOT/'provenance.json').write_text(json.dumps({'repo':REPO,'revision':REVISION},indent=2),encoding='utf-8')

if __name__=='__main__':
    install()
