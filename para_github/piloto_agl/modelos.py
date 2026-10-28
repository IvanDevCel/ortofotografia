"""Modelos oficiales; pesos y fuentes se guardan dentro del proyecto."""
import json
import time
import urllib.request

from comun import MODELS, save_json


def dino(download=False,device='cpu'):
    import torch
    record=MODELS/'dinov2_revision.json'
    if not record.exists():
        if not download:
            raise RuntimeError('Primero ejecuta: python piloto_agl/piloto.py modelos')
        req=urllib.request.Request('https://api.github.com/repos/facebookresearch/dinov2/commits/main',headers={'User-Agent':'UAV-AGL-pilot'})
        with urllib.request.urlopen(req) as reply:
            sha=json.load(reply)['sha']
        save_json(record,{'repository':'https://github.com/facebookresearch/dinov2','commit':sha})
    sha=json.loads(record.read_text())['commit']
    source=MODELS/'torch'/'hub'/f'facebookresearch_dinov2_{sha}'
    if source.exists():
        model=torch.hub.load(str(source),'dinov2_vits14',source='local',pretrained=True)
    else:
        if not download:
            raise RuntimeError('Faltan las fuentes DINOv2: ejecuta el comando modelos con Internet')
        model=torch.hub.load(f'facebookresearch/dinov2:{sha}','dinov2_vits14',trust_repo=True,skip_validation=True)
    return model.eval().to(device)


def local_models(device='cpu',cfg=None):
    from lightglue import SuperPoint, LightGlue
    from comun import config
    sp=SuperPoint(max_num_keypoints=(cfg or config())['verification']['max_keypoints']).eval().to(device)
    lg=LightGlue(features='superpoint',flash=False,depth_confidence=0.95,width_confidence=0.99).eval().to(device)
    return sp,lg


def prepare():
    start=time.perf_counter()
    dino(download=True)
    local_models()
    print(f'Modelos descargados y cargados en CPU: {time.perf_counter()-start:.1f} s',flush=True)
