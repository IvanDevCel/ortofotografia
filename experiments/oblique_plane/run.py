"""Run frozen baseline and candidate. This module never opens evaluation truth."""
import os
import sys
sys.dont_write_bytecode=True
import copy
import json
from pathlib import Path
import time
import hashlib
import cv2
import numpy as np
from rasterio.warp import transform
from geometry import rpy_ned

HERE=Path(__file__).resolve().parent;WORKTREE=HERE.parents[1];REPO=WORKTREE/'para_github'
sys.path.insert(0,str(REPO/'piloto_agl'));sys.path.insert(0,str(REPO/'demo_sitl'))
manifest=json.loads((HERE/'baseline_manifest.json').read_text());SOURCE=Path(manifest['source_root'])
os.environ['TORCH_HOME']=str(SOURCE/'para_github/.modelos_agl/torch')
os.environ['MPLCONFIGDIR']=str(HERE/'outputs/runtime/matplotlib')
import comun
comun.MODELS=SOURCE/'para_github/.modelos_agl';comun.OUT=HERE/'outputs/runtime'
from localizador_cuda_nav import CudaNavigatorLocalizer
from localizador import Localizer
from recuperacion_temporal import TemporalRecovery
from matcher import ObliqueMatcher

def safe(value):
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,np.ndarray):return value.tolist()
    raise TypeError(type(value).__name__)

def main():
    import torch
    if not torch.cuda.is_available():raise RuntimeError('CUDA required, no CPU fallback')
    cfg=json.loads((HERE/'config.json').read_text());out=HERE/'outputs';cases=json.loads((out/'cases.json').read_text())
    engines={};predictions=[];start=time.perf_counter()
    for case_id in cases:
        path=out/'measurements'/f'{case_id}.json';m=json.loads(path.read_text())
        if any(key in m for key in ['truth','body','camera','latitude_deg','longitude_deg']):raise RuntimeError('Forbidden truth fields in measurements')
        map_id=m['reference_map_id']
        if map_id not in engines:
            folder=SOURCE/'para_github/outputs/escenarios'/map_id
            pilot=json.loads((folder/'piloto.json').read_text());pilot['index_directory']=str(folder/'indices')
            for region in pilot['regions']:region['file']=str(SOURCE/'archivosTiff'/(region['id']+'.tif'))
            pilot_path=out/'runtime'/f'{map_id}.json';pilot_path.parent.mkdir(parents=True,exist_ok=True);pilot_path.write_text(json.dumps(pilot))
            baseline=CudaNavigatorLocalizer(str(pilot_path))
            candidate_cfg=copy.deepcopy(pilot);candidate_cfg['device']='cuda:0'
            candidate_engine=Localizer(candidate_cfg);candidate_engine.warmup()
            cal=json.loads((folder/'georreferencia.json').read_text())
            engines[map_id]=(baseline,ObliqueMatcher(candidate_engine,cal,cfg),cal)
        baseline,candidate,cal=engines[map_id]
        rgb=cv2.cvtColor(cv2.imread(str(out/'images'/f'{case_id}.png')),cv2.COLOR_BGR2RGB)
        ob=dict(capture_sim_s=m['capture_time_s'],capture_px4_us_est=round(m['capture_time_s']*1e6),
                agl_baro_m=m['height_body_agl_m'],q_capture_wxyz=m['body_quaternion_ned_wxyz'],
                velocity_ned_m_s=[0.,0.,0.],gyro_frd_rad_s=[0.,0.,0.],
                ref_lat=m['static_ekf_origin_lat_deg'],ref_lon=m['static_ekf_origin_lon_deg'],ref_alt=0.)
        baseline.temporal=TemporalRecovery()
        t=time.perf_counter();raw,_=baseline.locate(rgb,ob,cal)
        torch.cuda.synchronize();b=dict(accepted=bool(raw['accepted']),reason=raw['reason'],total_ms=(time.perf_counter()-t)*1000,
                                      body_utm=[raw.get('utm_e_body'),raw.get('utm_n_body')])
        if raw['accepted']:
            b['body']=dict(latitude_deg=raw['lat_visual'],longitude_deg=raw['lon_visual'],
                           altitude_sim_datum_m=m['height_body_agl_m'],height_agl_m=m['height_body_agl_m'],
                           measured_rpy_ned_deg=m['body_rpy_deg'],estimated_rpy_ned_deg=rpy_ned(np.array(raw['body_to_enu_from_matches'])) if raw.get('body_to_enu_from_matches') else None)
            b['camera_utm']=raw.get('camera_utm')
            b['camera']=dict(altitude_sim_datum_m=raw.get('pose_camera_agl_visual_m'),
                             height_agl_m=raw.get('pose_camera_agl_visual_m'),matrix_camera_to_enu=raw.get('camera_to_enu_from_matches'))
            if b['camera_utm']:
                lo,la=transform(cal['crs'],'EPSG:4326',[b['camera_utm'][0]],[b['camera_utm'][1]])
                b['camera'].update(longitude_deg=lo[0],latitude_deg=la[0])
            if raw.get('camera_to_enu_from_matches'):b['camera']['optical_frame_rpy_in_ned_deg']=rpy_ned(np.array(raw['camera_to_enu_from_matches']))
        c=candidate.locate(rgb,m)
        predictions.append(dict(case_id=case_id,measurement_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),baseline=b,oblique=c))
        (out/'predictions.json').write_text(json.dumps(predictions,default=safe,ensure_ascii=False,indent=2),encoding='utf8')
        print(f'{case_id}/{len(cases):03d}: baseline={b["accepted"]} ({b["total_ms"]:.0f}ms) oblique={c["accepted"]} ({c["total_ms"]:.0f}ms)',flush=True)
    for b,c,_ in engines.values():b.engine.close();c.engine.close()
    proof=dict(gpu=torch.cuda.get_device_name(0),torch=torch.__version__,seconds=time.perf_counter()-start,
               map_models={key:dict(baseline=value[0].proof['model_devices'],
                                   oblique={name:str(next(model.parameters()).device) for name,model in [('DINOv2',value[1].engine.dino),('SuperPoint',value[1].engine.sp),('LightGlue',value[1].engine.lg)]}) for key,value in engines.items()},
               reference='Frozen operational source; independent relocalization with reset temporal state for each case',
               truth_file_opened=False,px4_messages_sent=0,flights_started=0)
    (out/'execution.json').write_text(json.dumps(proof,indent=2),encoding='utf8')

if __name__=='__main__':main()
