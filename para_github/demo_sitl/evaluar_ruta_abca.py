"""Evaluate ordered waypoint visits AFTER the flight using separate truth."""
import json,csv
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
def read(p):return json.loads(p.read_text(encoding='utf8'))
m=read(ROOT/'informes/ultima_prueba.json');out=Path(m['report']);cfg=read(out/'configuracion.json');ctrl=read(out/'control_final.json');start=ctrl['start_sim_s'];duration=cfg['flight_effective_s']
truth=[json.loads(l) for l in (out/'registros_px4/truth.jsonl').read_text().splitlines()];truth=[p for p in truth if start<=p['sim_s']<=start+duration]
U=np.array(cfg['georeference']['utm_to_enu_basis_per_metre']).T;origin=np.array(cfg['georeference']['utm_center']);xy=origin+(np.linalg.inv(U)@np.array([p['xyz_enu'][:2] for p in truth]).T).T;times=np.array([p['sim_s']-start for p in truth]);cursor=0;visits=[]
for p in cfg['mission_waypoints']:
    ds=np.linalg.norm(xy-np.array([p['utm_e'],p['utm_n']]),axis=1);eligible=np.arange(len(times))>=cursor;ids=np.flatnonzero(eligible & (ds<=20));best=int(np.argmin(np.where(eligible,ds,np.inf)));hit=int(ids[0]) if len(ids) else None
    visits.append(dict(point=p['label'],visited_in_order=hit is not None,first_entry_flight_s=None if hit is None else float(times[hit]),minimum_distance_m=float(ds[best]),closest_flight_s=float(times[best])))
    cursor=(hit+1) if hit is not None else len(times)
    if hit is None:break
last=cfg['mission_waypoints'][-1];ends_at_a=np.hypot(last['utm_e']-cfg['A']['utm_e'],last['utm_n']-cfg['A']['utm_n'])<.01
route=cfg.get('start_label','A')+'-'+'-'.join(p.get('label','?').split(' ')[0] for p in cfg['mission_waypoints'])
completed=len(visits)==len(cfg['mission_waypoints']) and all(v['visited_in_order'] for v in visits)
result=dict(run=m['name'],route=route,ordered_visits=visits,completed_route=completed,returned_to_A=bool(ends_at_a and completed),final_distance_to_A_m=float(np.linalg.norm(xy[-1]-np.array([cfg['A']['utm_e'],cfg['A']['utm_n']]))),after_return='pause at final waypoint' if cfg.get('stop_at_mission_end') else 'orbit around A, no landing',evaluation_only=True)
(out/'recorrido_verificado.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
