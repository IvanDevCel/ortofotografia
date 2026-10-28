"""Inferencia ciega primero; evaluación con verdad de referencia después."""
import hashlib
import importlib.metadata
import json
import platform
from time import perf_counter

import cv2
import numpy as np
import psutil
from PIL import Image

from comun import ROOT, OUT, MODELS, Resources, save_json, save_csv
from localizador import Localizer


def retrieval_coverage(truth,tile):
    if not truth['positive']:
        return None
    polygon=np.asarray(truth['corners_px'],np.float32)-np.array([tile['col'],tile['row']],np.float32)
    rectangle=np.array([[0,0],[tile['width'],0],[tile['width'],tile['height']],[0,tile['height']]],np.float32)
    center_x=truth['col_real']-tile['col']
    center_y=truth['row_real']-tile['row']
    if not (0<=center_x<=tile['width'] and 0<=center_y<=tile['height']):
        return 0.
    area,_=cv2.intersectConvexConvex(polygon,rectangle)
    return min(1.,max(0.,float(area)/abs(cv2.contourArea(polygon))))


def diagnostic(loc,image,candidates,pred,path):
    best=pred['best']
    tile=next(t for t in candidates if t['id']==best['tile_id'])
    mapped=loc.tile_image(tile)
    color=(0,220,0) if pred['accepted'] else (255,80,60)
    if best['polygon_map_px'] is not None:
        poly=np.clip(np.asarray(best['polygon_map_px']),-2000,2000).astype(np.int32)
        cv2.polylines(mapped,[poly],True,color,2)
        cx,cy=best['center_map_px']
        cv2.drawMarker(mapped,(int(np.clip(cx,-2000,2000)),int(np.clip(cy,-2000,2000))),color,cv2.MARKER_CROSS,22,2)
    canvas=np.full((530,1280,3),255,np.uint8)
    canvas[40:520,:640]=image
    canvas[40:520,640:]=mapped
    label='ACEPTADA' if pred['accepted'] else 'RECHAZADA: mejor candidata, no posicion aceptada'
    cv2.putText(canvas,'ENTRADA SINTETICA DE ORTOFOTO',(10,25),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,0),1)
    cv2.putText(canvas,label,(650,25),cv2.FONT_HERSHEY_SIMPLEX,.5,(0,0,0),1)
    Image.fromarray(canvas).save(path,quality=90)


def annotate(cfg,predictions,prefix):
    # La verdad no se abre hasta terminar y guardar todas las predicciones.
    truth={t['id']:t for t in json.loads((OUT/'verdad.json').read_text(encoding='utf8'))}
    records=[]
    for item in predictions:
        actual=truth[item['id']]
        prediction=item['prediction']
        best=prediction['best']
        coverage=[retrieval_coverage(actual,t) for t in item['candidates']]
        correct=[i+1 for i,c in enumerate(coverage) if c is not None and c>0]
        footprint80=[i+1 for i,c in enumerate(coverage) if c is not None and c>=cfg['evaluation']['correct_retrieval_coverage']]
        recovered=bool(correct) if actual['positive'] else None
        error=float(np.hypot(prediction['x_est']-actual['x_real'],prediction['y_est']-actual['y_real'])) if actual['positive'] and prediction['accepted'] else None
        localized=bool(error is not None and error<=cfg['evaluation']['success_error_m'])
        record={
            'id':item['id'],'method':item['method'],'repeat':item['repeat'],
            'region':actual['region'],'positive':actual['positive'],'independent':False,
            'terrain':actual['terrain'],'variant':actual['variant'],
            'agl_m':actual['agl_m'],'footprint_width_m':actual['width_m'],'footprint_height_m':actual['height_m'],
            'footprint_area_m2':actual['area_m2'],'gsd_m_px':actual['gsd_m_px'],
            'x_real':actual['x_real'],'y_real':actual['y_real'],'x_est':prediction['x_est'],'y_est':prediction['y_est'],
            'error_m':error,'accepted':prediction['accepted'],'localized_within_5m':localized,
            'confidence_score':prediction['confidence_score'],'confidence_is_probability':False,
            'retrieval_ok_top10':recovered,'first_correct_rank':correct[0] if correct else None,
            'retrieval_footprint80_top10':bool(footprint80) if actual['positive'] else None,
            'first_footprint80_rank':footprint80[0] if footprint80 else None,
            'max_footprint_coverage_top10':max(coverage) if actual['positive'] else None,
            'retrieval_failure':not recovered if actual['positive'] else None,
            'verification_failure_given_retrieval':bool(recovered and not localized) if actual['positive'] else None,
            'false_acceptance':bool(not actual['positive'] and prediction['accepted']),
            'wrong_acceptance_positive':bool(actual['positive'] and prediction['accepted'] and not localized),
            'false_rejection':bool(actual['positive'] and not prediction['accepted']),
            'reason':prediction['reason'],'best_tile':best['tile_id'],'best_inliers':best['inliers'],
            'best_inlier_ratio':best['inlier_ratio'],'best_coverage':best['coverage'],
            'best_reprojection_px':best['median_reprojection_px'],
            'image_load_ms':item['image_load_ms'],**item['retrieval_times'],
            'query_features_ms':prediction['query_features_ms'],'verification_ms':prediction['verification_ms'],
            'total_query_ms':item['image_load_ms']+sum(item['retrieval_times'].values())+prediction['query_features_ms']+prediction['verification_ms'],
            'map_feature_cache_misses':prediction['map_feature_cache_misses'],
            'rss_peak_mib':max(item['resources']['rss_peak_mib'],item.get('retrieval_resources',{}).get('rss_peak_mib',0)),
            'rss_increase_mib':item['resources']['rss_increase_mib'],
            'input_image':item['image'],'found_map_image':item['diagnostic']}
        records.append(record)
    save_csv(OUT/f'{prefix}resultados.csv',records)
    save_json(OUT/f'{prefix}resultados.json',records)
    return records


def machine():
    import torch
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
            cpu=winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
    except (ImportError,OSError):
        cpu=platform.processor()
    packages={name:importlib.metadata.version(name) for name in ['torch','torchvision','rasterio','numpy','pillow','opencv-python','psutil','lightglue']}
    weights={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (MODELS/'torch/hub/checkpoints').glob('*.pth')}
    return {'cpu':cpu,'physical_cores':psutil.cpu_count(logical=False),'logical_cores':psutil.cpu_count(),
            'ram_gib':psutil.virtual_memory().total/2**30,'os':platform.platform(),'python':platform.python_version(),
            'device':'CPU','torch_threads':torch.get_num_threads(),'cuda_available_in_this_environment':torch.cuda.is_available(),
            'gpu_memory_used_mib':0,'versions':packages,'weights_sha256':weights,
            'dinov2_revision':json.loads((MODELS/'dinov2_revision.json').read_text(encoding='utf8')),
            'note':'CUDA no usada; esta instalación CPU no determina si el portátil tiene otra GPU.'}


def run(cfg,limit=None,repeats=1,benchmark=False):
    if repeats<1:
        raise ValueError('Se necesita al menos una repetición')
    queries=json.loads((OUT/'consultas.json').read_text(encoding='utf8'))
    local_cfg={k:v for k,v in cfg.items() if k!='zones'}
    save_json(OUT/'config_localizador.json',local_cfg)
    prefix='benchmark_' if benchmark else ('comprobacion_' if limit else '')
    if benchmark:
        chosen=[]
        for region in cfg['regions']:
            for height in cfg['camera']['heights_m']:
                chosen.append(next(q for q in queries if q['region']==region['id'] and q['agl_m']==height and q['id'].endswith('_original')))
        queries=chosen
    if limit:
        queries=queries[:limit]
    with Resources() as loading:
        loc=Localizer(local_cfg)
        loc.warmup()
    save_json(OUT/f'{prefix}carga_localizador.json',loading.result())
    save_json(OUT/'equipo.json',machine())
    predictions=[]
    (OUT/'diagnosticos').mkdir(exist_ok=True)
    started=perf_counter()
    spool=OUT/f'{prefix}predicciones.jsonl'
    try:
        with spool.open('w',encoding='utf8') as stream:
            for number,query in enumerate(queries,1):
                for repeat in range(1,repeats+1):
                    tic=perf_counter()
                    with Image.open(OUT/query['image']) as pil:
                        image=np.asarray(pil.convert('RGB')).copy()
                    load_ms=(perf_counter()-tic)*1000
                    with Resources() as retrieval_res:
                        candidates,retrieval_times=loc.retrieve(image,query['region'],query['agl_m'])
                    methods=['lightglue','sift'] if (number+repeat)%2==0 else ['sift','lightglue']
                    for method in methods:
                        with Resources() as res:
                            prediction=loc.verify(image,candidates,query['agl_m'],method)
                        relative=f"diagnosticos/{prefix}{query['id']}_{method}_r{repeat}.jpg"
                        diagnostic(loc,image,candidates,prediction,OUT/relative)
                        item={**query,'method':method,'repeat':repeat,'prediction':prediction,
                              'candidates':candidates,'retrieval_times':retrieval_times,
                              'image_load_ms':load_ms,'resources':res.result(),
                              'retrieval_resources':retrieval_res.result(),'diagnostic':relative}
                        stream.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n')
                        stream.flush()
                        predictions.append(item)
                if number%5==0 or number==len(queries):
                    print(f"{number}/{len(queries)} consultas, {len(predictions)} verificaciones, {perf_counter()-started:.1f} s",flush=True)
    finally:
        loc.close()
    records=annotate(cfg,predictions,prefix)
    mem=psutil.Process().memory_info()
    save_json(OUT/f'{prefix}duracion_consultas.json',{'wall_seconds_including_diagnostics':perf_counter()-started,
        'queries':len(queries),'repeats':repeats,'method_records':len(records),
        'peak_process_working_set_mib':getattr(mem,'peak_wset',mem.rss)/2**20,
        'note':'La suma por método incluye carga de entrada, DINO compartido y su verificador; excluye figuras y verdad.'})
    print(f'Guardados {len(records)} resultados; verdad de referencia unida después de inferir.',flush=True)
