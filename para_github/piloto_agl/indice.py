import json
from time import perf_counter

import cv2
import numpy as np
import rasterio
import torch

from camara import footprint
from comun import ROOT, OUT, Resources, save_json, save_csv
from datos import read_tile
from modelos import dino


def descriptor(model,arrays,cfg):
    width=cfg['index']['descriptor_width']
    height=cfg['index']['descriptor_height']
    array=np.stack([cv2.resize(a,(width,height),interpolation=cv2.INTER_AREA) for a in arrays])
    device=next(model.parameters()).device
    tensor=torch.from_numpy(array.transpose(0,3,1,2).copy()).to(device=device,dtype=torch.float32)/255
    mean=torch.tensor([.485,.456,.406],device=device).view(1,3,1,1)
    std=torch.tensor([.229,.224,.225],device=device).view(1,3,1,1)
    with torch.inference_mode():
        vector=model((tensor-mean)/std)
        vector=torch.nn.functional.normalize(vector,dim=1)
    return vector.cpu().numpy().astype(np.float32)


def origins(start,length,side,stride):
    end=start+length-side
    if end<start:
        raise ValueError('La región es menor que una tesela para esta altura')
    values=list(np.arange(start,end+1e-6,stride))
    if not values or abs(values[-1]-end)>1e-5:
        values.append(end)
    return [float(v) for v in values]


def grid(reg,src,agl,cfg):
    fp=footprint(cfg['camera'],agl)
    factor=cfg['index']['tile_footprint_factor']
    stride=cfg['index']['stride_footprint_factor']
    width=fp['width_m']*factor/src.res[0]
    height=fp['height_m']*factor/src.res[1]
    cols=origins(reg['col'],reg['width'],width,min(fp['width_m']*stride,cfg['index']['max_stride_m'])/src.res[0])
    rows=origins(reg['row'],reg['height'],height,min(fp['height_m']*stride,cfg['index']['max_stride_m'])/src.res[1])
    return [{'id':f"{reg['id']}_h{agl}_{i:05d}",'region':reg['id'],'file':reg['file'],
             'agl_m':agl,'col':col,'row':row,'width':width,'height':height,
             'transform':list(src.transform)[:6],'resolution':src.res[0]}
            for i,(row,col) in enumerate((r,c) for r in rows for c in cols)]


def build(cfg):
    out=ROOT/cfg['index_directory'] if cfg.get('index_directory') else OUT/'indices'
    out.mkdir(parents=True,exist_ok=True)
    with Resources() as loading:
        model=dino(device=cfg.get('device','cpu'))
        descriptor(model,[np.zeros((168,224,3),dtype=np.uint8)],cfg)
    save_json(out.parent/'carga_dino_indice.json',loading.result())
    records=[]
    for reg in cfg['regions']:
        with rasterio.open(ROOT/reg['file']) as src:
            for height in cfg['camera']['heights_m']:
                with Resources() as res:
                    tiles=grid(reg,src,height,cfg)
                    vectors=[]
                    for start in range(0,len(tiles),cfg['index']['batch_size']):
                        batch=tiles[start:start+cfg['index']['batch_size']]
                        arrays=[read_tile(src,t['col'],t['row'],t['width'],t['height'],224,168) for t in batch]
                        vectors.append(descriptor(model,arrays,cfg))
                    stem=f"{reg['id']}_h{height:03d}"
                    save_json(out/f'{stem}.json',tiles)
                    np.savez_compressed(out/f'{stem}.npz',descriptors=np.concatenate(vectors))
                fp=footprint(cfg['camera'],height)
                factor=cfg['index']['tile_footprint_factor']
                stride=cfg['index']['stride_footprint_factor']
                full_count=len(origins(0,src.width,fp['width_m']*factor/src.res[0],min(fp['width_m']*stride,cfg['index']['max_stride_m'])/src.res[0]))*len(origins(0,src.height,fp['height_m']*factor/src.res[1],min(fp['height_m']*stride,cfg['index']['max_stride_m'])/src.res[1]))
                record={'region':reg['id'],'agl_m':height,'tiles':len(tiles),'area_km2':reg['width']*reg['height']*src.res[0]**2/1e6,
                        **res.result(),'full_tiff_tiles_estimate':full_count,
                        'full_tiff_seconds_linear_estimate':res.seconds*full_count/len(tiles),
                        'descriptor_file_bytes':(out/f'{stem}.npz').stat().st_size}
                records.append(record)
                save_csv(out.parent/'preparacion.csv',records)
                save_json(out.parent/'preparacion.json',records)
                print(f"Índice {stem}: {len(tiles)} teselas, {res.seconds:.2f} s, RSS pico {res.peak/2**20:.0f} MiB",flush=True)


def load_indices(cfg):
    result={}
    out=ROOT/cfg['index_directory'] if cfg.get('index_directory') else OUT/'indices'
    for reg in cfg['regions']:
        for height in cfg['camera']['heights_m']:
            stem=f"{reg['id']}_h{height:03d}"
            tiles=json.loads((out/f'{stem}.json').read_text(encoding='utf8'))
            with np.load(out/f'{stem}.npz',allow_pickle=False) as archive:
                vectors=archive['descriptors'].copy()
            result[(reg['id'],height)]=(tiles,vectors)
    return result
