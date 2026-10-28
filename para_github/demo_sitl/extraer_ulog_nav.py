"""Verificación posterior al vuelo: no se ejecuta dentro del navegador."""
import json
from pathlib import Path
import shutil
import math
import re
from pyulog import ULog

root=Path(__file__).resolve().parent.parent
meta=json.loads((root/'informes/ultima_prueba.json').read_text(encoding='utf8'));out=root/'informes'/meta['name']
reg=json.loads((Path.home()/'uav-sitl/demo_actual.json').read_text());run=Path(reg['run'])
if run.name!=meta['name']:raise RuntimeError('El registro activo no corresponde al informe solicitado')
sources=list((run/'log').rglob('*.ulg'))
if not sources:sources=list((out/'registros_px4').glob('*.ulg'))
if not sources:
    # Shared PX4 rootfs: select only the exact path logged by this process.
    recorded=re.findall(r'\./log/([0-9-]+/[0-9_]+\.ulg)',(run/'px4_gazebo.log').read_text())
    sources=[Path.home()/'uav-sitl/PX4-Autopilot/build/px4_sitl_default/rootfs/log'/p for p in set(recorded)]
    sources=[p for p in sources if p.is_file()]
if not sources:raise RuntimeError('No hay ULog atribuible a esta ejecución; no se usa el registro de otro vuelo')
latest=max(sources,key=lambda p:p.stat().st_mtime)
destination=out/'registros_px4'/latest.name
if latest.resolve()!=destination.resolve():shutil.copy2(latest,destination)
u=ULog(str(out/'registros_px4'/latest.name));result={}
fields={
 'estimator_status_flags':['timestamp','cs_gnss_pos','cs_gnss_vel','cs_gps_hgt','cs_ev_pos','cs_ev_vel','cs_ev_hgt','cs_ev_yaw','cs_wind_dead_reckoning','cs_inertial_dead_reckoning','cs_fuse_aspd','cs_baro_hgt'],
 'estimator_aid_src_ev_pos':['timestamp','timestamp_sample','time_last_fuse','fused','innovation_rejected','observation[0]','observation[1]','test_ratio[0]','test_ratio[1]'],
 'vehicle_visual_odometry':['timestamp','timestamp_sample','position[0]','position[1]','position[2]','position_variance[0]','position_variance[1]','quality'],
 'timesync_status':['timestamp','estimated_offset','observed_offset','round_trip_time'],
 'vehicle_local_position':['timestamp','x','y','z','vx','vy','vz','xy_valid','v_xy_valid','ref_lat','ref_lon','ref_alt'],
 'vehicle_global_position':['timestamp','lat','lon','alt'],
 'vehicle_status':['timestamp','nav_state','arming_state'],
 'sensor_gps':['timestamp','timestamp_sample','fix_type','satellites_used'],
}
for dataset in u.data_list:
    if dataset.multi_id!=0 or dataset.name not in fields:continue
    d=dataset.data
    def val(v):
        v=v.item() if hasattr(v,'item') else v
        return None if isinstance(v,float) and not math.isfinite(v) else v
    keys=[k for k in fields[dataset.name] if k in d]
    result[dataset.name]=[{k:val(d[k][i]) for k in keys} for i in range(len(d['timestamp']))]
(out/'ulog_verificacion.json').write_text(json.dumps(result,allow_nan=False),encoding='utf8')
(out/'ulog_datasets.json').write_text(json.dumps({d.name:{'instance':d.multi_id,'samples':len(d.data['timestamp'])} for d in u.data_list},indent=2))
print('ULog leído:',latest.name,{k:len(v) for k,v in result.items()})
