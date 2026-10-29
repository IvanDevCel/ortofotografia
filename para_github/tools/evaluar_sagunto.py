"""Evalúa la misión de agua con verdad separada; nunca guía al navegador."""
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent.parent
meta=json.loads((ROOT/'informes/ultima_prueba.json').read_text(encoding='utf8'))
out=Path(meta['report'])
def read(path):return json.loads(path.read_text(encoding='utf8'))
cfg=read(out/'configuracion.json');ctrl=read(out/'control_final.json');pred=read(out/'predicciones.json')
truth=[json.loads(s) for s in (out/'registros_px4/truth.jsonl').read_text().splitlines() if s.strip()]
events=[json.loads(s) for s in (out/'registros_px4/eventos.jsonl').read_text().splitlines() if s.strip()]
U=np.array(cfg['georeference']['utm_to_enu_basis_per_metre']).T;origin=np.array(cfg['georeference']['utm_center'])
xy=origin+(np.linalg.inv(U)@np.array([p['xyz_enu'][:2] for p in truth]).T).T
times=np.array([p['sim_s'] for p in truth]);errors=[]
for p in pred:
    if p['accepted']:
        i=int(np.argmin(abs(times-p['capture_sim_s'])))
        errors.append(float(np.linalg.norm(xy[i]-[p['utm_e_body'],p['utm_n_body']])))
gpu=read(out/'cuda_final.json');route=read(out/'recorrido_verificado.json')
summary=dict(run=meta['name'],route=route['route'],completed_route=route['completed_route'],
             ordered_visits=route['ordered_visits'],captures=len(pred),
             visual_accepted=sum(bool(p['accepted']) for p in pred),
             companion_admitted=sum(bool(p.get('transport_ack',{}).get('admitted')) for p in pred),
             visual_error_mean_m=float(np.mean(errors)) if errors else None,
             visual_error_max_m=max(errors) if errors else None,
             inference_mean_ms=float(np.mean([p['total_ms'] for p in pred])) if pred else None,
             inference_max_ms=max([p['total_ms'] for p in pred],default=None),
             actual_duration_s=ctrl['sim_s']-ctrl['start_sim_s'],
             phase=ctrl['phase'],error=ctrl.get('error'),
             planned_route_complete_event=any(e['type']=='PLANNED_ROUTE_COMPLETE' for e in events),
             all_models_cuda=all(v=='cuda:0' for v in gpu['proof']['model_devices'].values()),
             gpu=gpu['proof']['gpu'],model_calls=gpu['calls'],
             gnss_cut_effective_s=ctrl['gnss_cut_sim_s']-ctrl['start_sim_s'] if ctrl['gnss_cut_sim_s'] else None,
             visual_navigation_demonstrated=bool(errors),
             same_static_orthophoto_as_map_and_scene=True,
             limitation='Agua fotografiada inmóvil y terreno plano; no es validación sobre mar real')
(out/'resumen_sagunto.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
