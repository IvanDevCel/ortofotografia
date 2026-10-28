"""Generación: altura determina el remuestreo físico. Verdad fuera de consultas."""
import math
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling
from rasterio.windows import Window

from camara import camera_parameters, footprint
from comun import ROOT, OUT, save_csv, save_json


def read_tile(src,col,row,width,height,ow,oh):
    if col<0 or row<0 or col+width>src.width or row+height>src.height:
        raise ValueError('Huella fuera del TIFF')
    arr=src.read([1,2,3],window=Window(col,row,width,height),out_shape=(3,oh,ow),
                 resampling=Resampling.average if width/ow>1 else Resampling.bilinear)
    return np.ascontiguousarray(arr.transpose(1,2,0))


def capture(src,col_center,row_center,agl,yaw,camera):
    fp=footprint(camera,agl)
    # Contexto se remuestrea primero a GSD de cámara; giro después sin bordes negros.
    gsd=fp['gsd_m_px']
    diagonal=int(math.ceil(math.hypot(camera['width'],camera['height'])))+8
    side_source=diagonal*gsd/src.res[0]
    context=read_tile(src,col_center-side_source/2,row_center-side_source/2,side_source,side_source,diagonal,diagonal)
    center=(diagonal/2-.5,diagonal/2-.5)
    matrix=cv2.getRotationMatrix2D(center,yaw,1)
    rotated=cv2.warpAffine(context,matrix,(diagonal,diagonal),flags=cv2.INTER_CUBIC)
    # Extraer por remap mantiene el centro geométrico para tamaños pares e impares.
    xx,yy=np.meshgrid(np.arange(camera['width'],dtype=np.float32),np.arange(camera['height'],dtype=np.float32))
    image=cv2.remap(rotated,xx+(diagonal-camera['width'])/2,yy+(diagonal-camera['height'])/2,cv2.INTER_CUBIC)
    # Esquinas de entrada en coordenadas globales de bordes del raster.
    theta=math.radians(yaw)
    corners=[]
    for u,v in [(-.5,-.5),(.5,-.5),(.5,.5),(-.5,.5)]:
        dx,dy=u*fp['width_m']/src.res[0],v*fp['height_m']/src.res[1]
        corners.append([col_center+math.cos(theta)*dx-math.sin(theta)*dy,
                        row_center+math.sin(theta)*dx+math.cos(theta)*dy])
    return image,corners,fp


def generate(cfg):
    start=perf_counter()
    camera=cfg['camera']
    save_json(OUT/'camara.json',camera_parameters(camera))
    save_csv(OUT/'alturas.csv',camera_parameters(camera)['heights'])
    queries,truth=[],[]
    images=OUT/'entradas'
    images.mkdir(parents=True,exist_ok=True)
    variants=[('original',0),('giro25',25),('brillo065',0),('sombra045',0),('desenfoque15',0)]
    region_by_id={r['id']:r for r in cfg['regions']}
    for zone in cfg['zones']:
        reg=region_by_id[zone['region']]
        col=reg['col']+reg['width']*zone['u']
        row=reg['row']+reg['height']*zone['v']
        with rasterio.open(ROOT/reg['file']) as src:
            for height in camera['heights_m']:
                for variant,yaw in variants:
                    ident=f"{zone['id']}_h{height:03d}_{variant}"
                    image,corners,fp=capture(src,col,row,height,yaw,camera)
                    if variant=='brillo065':
                        image=np.clip(image.astype(np.float32)*.65,0,255).astype(np.uint8)
                    if variant=='sombra045':
                        mask=np.zeros(image.shape[:2],dtype=np.float32)
                        cv2.fillConvexPoly(mask,np.array([[0,60],[400,0],[640,300],[160,480]]),1)
                        mask=cv2.GaussianBlur(mask,(0,0),18)
                        image=np.clip(image.astype(float)*(1-.55*mask[:,:,None]),0,255).astype(np.uint8)
                    if variant=='desenfoque15':
                        image=cv2.GaussianBlur(image,(0,0),1.5)
                    Image.fromarray(image).save(images/f'{ident}.png')
                    queries.append({'id':ident,'image':f'entradas/{ident}.png','region':reg['id'],'agl_m':height})
                    x,y=src.transform*(col,row)
                    truth.append({'id':ident,'positive':True,'region':reg['id'],'terrain':zone['terrain'],
                                  'variant':variant,'independent':False,'x_real':x,'y_real':y,
                                  'col_real':col,'row_real':row,'corners_px':corners,**fp})
    # Negativos de otra región y de información inexistente, en cada altura.
    rng=np.random.default_rng(cfg['seed'])
    for height in camera['heights_m']:
        for target,source_zone in [('T1','bosque'),('T2','costa')]:
            original=f'{source_zone}_h{height:03d}_original'
            ident=f'rechazo_{target}_h{height:03d}_otra_zona'
            with Image.open(images/f'{original}.png') as im:
                im.save(images/f'{ident}.png')
            queries.append({'id':ident,'image':f'entradas/{ident}.png','region':target,'agl_m':height})
            origin=next(t for t in truth if t['id']==original)
            truth.append({**origin,'id':ident,'positive':False,'region':target,'variant':'otra_zona'})
        for variant,target in [('uniforme','T1'),('ruido','T2')]:
            ident=f'rechazo_{target}_h{height:03d}_{variant}'
            array=np.full((480,640,3),128,dtype=np.uint8) if variant=='uniforme' else rng.integers(0,256,(480,640,3),dtype=np.uint8)
            Image.fromarray(array).save(images/f'{ident}.png')
            queries.append({'id':ident,'image':f'entradas/{ident}.png','region':target,'agl_m':height})
            truth.append({'id':ident,'positive':False,'region':target,'terrain':'sin información',
                          'variant':variant,'independent':False,'x_real':None,'y_real':None,
                          'col_real':None,'row_real':None,'corners_px':None,**footprint(camera,height)})
    save_json(OUT/'consultas.json',queries)
    save_json(OUT/'verdad.json',truth)
    save_csv(OUT/'imagenes.csv',[{k:v for k,v in t.items() if k!='corners_px'} for t in truth])
    save_json(OUT/'config_ejecucion.json',{k:cfg[k] for k in ('seed','camera','regions','zones')})
    print(f'{len(queries)} imágenes generadas: altura cambia huella y GSD; {perf_counter()-start:.2f} s',flush=True)
