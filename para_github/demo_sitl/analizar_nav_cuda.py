"""Calcula todos los errores después del vuelo; Gazebo no entra al navegador."""
import bisect
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import zipfile
import cv2
import numpy as np
from geometria_navegacion import qmul,qrot,euler,unproject,project
from rasterio.warp import transform

ROOT=Path(__file__).resolve().parent.parent
def read(path):return json.loads(path.read_text(encoding='utf8'))
def jsonl(path):return [json.loads(l) for l in path.read_text(encoding='utf8').splitlines() if l.strip()]
def safe(v):
    if isinstance(v,np.generic):return v.item()
    raise TypeError(str(type(v)))
def main():
    meta=read(ROOT/'informes/ultima_prueba.json');out=Path(meta['report']);cfg=read(out/'configuracion.json');control=read(out/'control_final.json')
    duration=int(cfg.get('flight_effective_s',45))
    terrain_z=read(out/'terreno_reparado.json')['ortho_top_z_m'] if (out/'terreno_reparado.json').exists() else .24
    truth=jsonl(out/'registros_px4/truth.jsonl');preds=read(out/'predicciones.json');ulog=read(out/'ulog_verificacion.json')
    corrections=jsonl(out/'registros_px4/correcciones.jsonl');sent=jsonl(out/'registros_px4/odometria_enviada.jsonl')
    events=jsonl(out/'registros_px4/eventos.jsonl');orb=jsonl(out/'registros_px4/orb.jsonl')
    start=control['start_sim_s'];cut=control['gnss_cut_sim_s'];off=preds[0]['onboard']['clock_gz_minus_px4_s']
    tt=np.array([t['sim_s'] for t in truth]);senttimes=np.array([r['sample_sim_s'] for r in sent])
    def at(dataset,t):
        rows=ulog.get(dataset,[])
        if not rows:return {}
        times=[r['timestamp'] for r in rows];i=bisect.bisect_right(times,(t-off)*1e6)-1
        return rows[max(0,i)]
    def tr_at(t):
        i=int(np.argmin(abs(tt-t)));raw=truth[i];q=qmul(qmul([0,2**-.5,2**-.5,0],raw['q_enu_flu_wxyz']),[0,1,0,0]);r,p,y=euler(q)
        j=max(0,i-1);k=min(len(truth)-1,i+1);dt=truth[k]['sim_s']-truth[j]['sim_s']
        vel=[0.,0,0];gyro=[0.,0,0]
        if dt>1e-7:
            va,vb=truth[j]['xyz_enu'],truth[k]['xyz_enu'];vel=[(vb[1]-va[1])/dt,(vb[0]-va[0])/dt,-(vb[2]-va[2])/dt]
            qa=qmul(qmul([0,2**-.5,2**-.5,0],truth[j]['q_enu_flu_wxyz']),[0,1,0,0]);qb=qmul(qmul([0,2**-.5,2**-.5,0],truth[k]['q_enu_flu_wxyz']),[0,1,0,0])
            dq=qmul([qa[0],-qa[1],-qa[2],-qa[3]],qb)
            if dq[0]<0:dq=[-v for v in dq]
            nv=math.sqrt(sum(v*v for v in dq[1:]));theta=2*math.atan2(nv,dq[0]);gyro=[v/nv*theta/dt for v in dq[1:]] if nv>1e-10 else [0.,0,0]
        return {'pose':raw,'q':q,'roll':r,'pitch':p,'yaw':y,'velocity':vel,'gyro':gyro,'sync_error_s':raw['sim_s']-t}
    basis=cfg['georeference']['utm_to_enu_basis_per_metre'];U=np.array([[basis[0][0],basis[1][0]],[basis[0][1],basis[1][1]]]);u0=np.array(cfg['georeference']['utm_center'])
    def utm(xyz):return u0+np.linalg.solve(U,np.array(xyz[:2]))
    def degrees_error(a,b):return (math.degrees(a-b)+180)%360-180
    # Attribute fused EV samples to the actual last visual anchor of each sent
    # odometry message, accounting for the measured clock offset.
    fused_by_second={n:0 for n in range(1,duration+1)};rejected_by_second={n:0 for n in range(1,duration+1)}
    aid_samples=ulog.get('estimator_aid_src_ev_pos',[])
    aid_evidence='ULog completo'
    if not aid_samples:
        import re
        aid_evidence='capturas uORB periódicas; recuento mínimo observado, no todas las muestras'
        seen=set()
        for snap in orb:
            text=snap.get('estimator_aid_src_ev_pos','')
            ts=re.search(r'\btimestamp_sample:\s*(\d+)',text)
            if not ts or int(ts[1]) in seen:continue
            seen.add(int(ts[1]))
            aid_samples.append({'timestamp_sample':int(ts[1]),'fused':bool(re.search(r'\bfused:\s*True',text)),
                'innovation_rejected':bool(re.search(r'innovation_rejected:\s*True',text))})
    for aid in aid_samples:
        world=aid['timestamp_sample']/1e6+off
        if len(senttimes)==0:continue
        i=int(np.argmin(abs(senttimes-world)))
        if abs(senttimes[i]-world)>.08:continue
        n=sent[i]['last_image_second']
        fused_by_second[n]+=bool(aid.get('fused'));rejected_by_second[n]+=bool(aid.get('innovation_rejected'))
    rows=[]
    for pred in preds:
        n=pred['second'];t=pred['capture_sim_s'];ob=pred['onboard'];truthval=tr_at(t);raw=truthval['pose'];xyz=raw['xyz_enu'];ue,un=utm(xyz)
        lon,lat=transform('EPSG:25829','EPSG:4326',[float(ue)],[float(un)])
        flags=at('estimator_status_flags',t);lp=at('vehicle_local_position',t);gp=at('vehicle_global_position',t);gps=at('sensor_gps',t)
        phase='GNSS ON' if t<cut else 'GNSS OUT'
        admitted=[c for c in corrections if c.get('admitted_by_companion') and c['arrival_sim_s']<=t]
        last=admitted[-1] if admitted else None
        source='GNSS+IMU/baro' if flags.get('cs_gnss_pos') else 'VISION_PROPAGADA+IMU/baro' if flags.get('cs_ev_pos') else 'ESTIMA_AIRE_VIENTO+IMU/baro' if flags.get('cs_wind_dead_reckoning') else 'ESTIMA_INERCIAL/SIN_POSICION_CONFIRMADA'
        remaining=math.hypot(ue-cfg['B']['utm_e'],un-cfg['B']['utm_n'])
        trueagl=xyz[2]-terrain_z;alt_est=ob['altitude_amsl_px4_m']
        mountq=[2**-.5,0.,0.,2**-.5]
        camera_angles=euler(qmul(ob['q_capture_wxyz'],mountq));true_camera_angles=euler(qmul(truthval['q'],mountq))
        ray=qrot(ob['q_capture_wxyz'],[0,0,1])
        tan=math.tan(math.radians(35));foot=[]
        for xx,yy in [(-1,-1),(1,-1),(1,1),(-1,1)]:
            direction=qrot(ob['q_capture_wxyz'],[-yy*tan*.75,xx*tan,1])
            foot.append([ob['agl_baro_m']*direction[0]/direction[2],ob['agl_baro_m']*direction[1]/direction[2]] if direction[2]>.02 else None)
        row={'second':n,'capture_sim_s':t,'flight_s':t-start,'gnss_phase':phase,'image':f'imagenes/{n:03d}.jpg',
          'rectified_image':f'imagenes/{n:03d}_rectificada.jpg','latitude_visual_deg':pred.get('lat_visual'),'longitude_visual_deg':pred.get('lon_visual'),
          'visual_utm_e_m':pred.get('utm_e_body'),'visual_utm_n_m':pred.get('utm_n_body'),
          'altitude_amsl_px4_m':alt_est,'altitude_source':'PX4 ALTITUDE, EKF baro reference, synthetic datum',
          'agl_baro_m':ob['agl_baro_m'],'agl_source':'HIGHRES_IMU pressure + ground calibration; planar simulated ground',
          'roll_onboard_deg':math.degrees(ob['roll_rad']),'pitch_onboard_deg':math.degrees(ob['pitch_rad']),'heading_onboard_deg':math.degrees(ob['yaw_rad'])%360,
          'gyro_x_rad_s':ob['gyro_frd_rad_s'][0],'gyro_y_rad_s':ob['gyro_frd_rad_s'][1],'gyro_z_rad_s':ob['gyro_frd_rad_s'][2],
          'velocity_n_m_s':ob['velocity_ned_m_s'][0],'velocity_e_m_s':ob['velocity_ned_m_s'][1],'velocity_d_m_s':ob['velocity_ned_m_s'][2],
          'speed_onboard_m_s':math.sqrt(sum(x*x for x in ob['velocity_ned_m_s'])),
          'camera_optical_roll_ned_deg':math.degrees(camera_angles[0]),'camera_optical_pitch_ned_deg':math.degrees(camera_angles[1]),
          'camera_optical_yaw_ned_deg':math.degrees(camera_angles[2])%360,'camera_boresight_n':ray[0],'camera_boresight_e':ray[1],'camera_boresight_d':ray[2],
          'camera_tilt_from_nadir_deg':math.degrees(math.acos(max(-1,min(1,ray[2])))),
          'nadir_footprint_width_m':2*ob['agl_baro_m']*tan,'nadir_footprint_height_m':1.5*ob['agl_baro_m']*tan,
          'tilted_footprint_relative_ned_json':json.dumps(foot),
          'camera_roll_error_deg':degrees_error(camera_angles[0],true_camera_angles[0]),'camera_pitch_error_deg':degrees_error(camera_angles[1],true_camera_angles[1]),
          'camera_yaw_error_deg':degrees_error(camera_angles[2],true_camera_angles[2]),
          'camera_frame_note':'optical to FRD fixed mount [[0,-1,0],[1,0,0],[0,0,1]]; H in IA JSON',
          'truth_lat_deg':lat[0],'truth_lon_deg':lon[0],'truth_utm_e_m':float(ue),'truth_utm_n_m':float(un),
          'truth_altitude_sim_m':xyz[2],'truth_agl_m':trueagl,'truth_roll_deg':math.degrees(truthval['roll']),
          'truth_pitch_deg':math.degrees(truthval['pitch']),'truth_heading_deg':math.degrees(truthval['yaw'])%360,
          'truth_gyro_x_rad_s':truthval['gyro'][0],'truth_gyro_y_rad_s':truthval['gyro'][1],'truth_gyro_z_rad_s':truthval['gyro'][2],
          'truth_velocity_n_m_s':truthval['velocity'][0],'truth_velocity_e_m_s':truthval['velocity'][1],'truth_velocity_d_m_s':truthval['velocity'][2],
          'horizontal_visual_error_m':None,'latitude_error_deg':None,'longitude_error_deg':None,
          'altitude_error_m':None if alt_est is None else alt_est-xyz[2],'agl_error_m':ob['agl_baro_m']-trueagl,
          'roll_error_deg':degrees_error(ob['roll_rad'],truthval['roll']),'pitch_error_deg':degrees_error(ob['pitch_rad'],truthval['pitch']),
          'heading_error_deg':degrees_error(ob['yaw_rad'],truthval['yaw']),
          'gyro_x_error_rad_s':ob['gyro_frd_rad_s'][0]-truthval['gyro'][0],'gyro_y_error_rad_s':ob['gyro_frd_rad_s'][1]-truthval['gyro'][1],
          'gyro_z_error_rad_s':ob['gyro_frd_rad_s'][2]-truthval['gyro'][2],
          'velocity_n_error_m_s':ob['velocity_ned_m_s'][0]-truthval['velocity'][0],'velocity_e_error_m_s':ob['velocity_ned_m_s'][1]-truthval['velocity'][1],
          'velocity_d_error_m_s':ob['velocity_ned_m_s'][2]-truthval['velocity'][2],
          'confidence_uncalibrated':pred['confidence_score'],'visual_accepted':bool(pred['accepted']),'accepted_01':int(pred['accepted']),'image_processed':pred.get('processed',True),
          'visual_rejection_reason':pred['reason'],'inference_ms':pred['total_ms'],'cuda_elapsed_ms':pred['cuda_elapsed_ms'],
          'capture_to_publication_sim_s':pred['transport_ack']['delay_s'],'admitted_by_companion':pred['transport_ack']['admitted'],
          'last_correction_age_at_capture_s':None if last is None else t-last['capture_sim_s'],
          'last_correction_second':None if last is None else last['second'],'sigma_h_m':pred.get('sigma_horizontal_m'),
          'index_height_m':pred['index_height_m'],'rectified_valid_fraction':pred['rectified_fraction'],
          'px4_gnss_position_fused':bool(flags.get('cs_gnss_pos')),'px4_visual_position_fused_at_capture':bool(flags.get('cs_ev_pos')),
          'px4_source_at_capture':source,'px4_fix_type':gps.get('fix_type'),'px4_ev_fused_samples_from_this_correction':fused_by_second[n],
          'px4_ev_rejected_samples_from_this_correction':rejected_by_second[n],'fusion_evidence_source':aid_evidence,'px4_lat_est_deg':gp.get('lat'),'px4_lon_est_deg':gp.get('lon'),
          'px4_position_error_m':None,'remaining_B_truth_m':remaining,'remaining_B_px4_m':None,
          'attitude_sample_age_s':ob['attitude_age_s'],'gyro_sample_age_s':ob['gyro_age_s'],'velocity_sample_age_s':ob['velocity_age_s'],
          'pressure_sample_age_s':ob['pressure_age_s'],'truth_alignment_error_s':truthval['sync_error_s'],
          'cuda_dino':pred['model_devices']['DINOv2'],'cuda_superpoint':pred['model_devices']['SuperPoint'],'cuda_lightglue':pred['model_devices']['LightGlue'],
          'nav_state':at('vehicle_status',t).get('nav_state')}
        if pred['accepted']:
            row.update(horizontal_visual_error_m=math.hypot(pred['utm_e_body']-ue,pred['utm_n_body']-un),latitude_error_deg=pred['lat_visual']-lat[0],longitude_error_deg=pred['lon_visual']-lon[0])
        if gp.get('lat') is not None:
            epx,npx=transform('EPSG:4326','EPSG:25829',[gp['lon']],[gp['lat']]);row['px4_position_error_m']=math.hypot(epx[0]-ue,npx[0]-un)
            row['remaining_B_px4_m']=math.hypot(epx[0]-cfg['B']['utm_e'],npx[0]-cfg['B']['utm_n'])
        rows.append(row)
    with (out/'datos.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (out/'filas.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
    fs=ulog['estimator_status_flags'];during=[f for f in fs if start+5.25<=f['timestamp']/1e6+off<=start+duration]
    fusion_intervals=[];current=None
    for f in during:
        active=bool(f.get('cs_ev_pos'));tw=f['timestamp']/1e6+off-start
        if active and current is None:current=tw
        if not active and current is not None:fusion_intervals.append([current,tw]);current=None
    if current is not None:fusion_intervals.append([current,float(duration)])
    errors=[r['horizontal_visual_error_m'] for r in rows if r['visual_accepted']]
    frame_times=np.array([r['capture_sim_s'] for r in preds]);gpu=read(out/'cuda_final.json')
    A=np.array([cfg['A']['utm_e'],cfg['A']['utm_n']]);B=np.array([cfg['B']['utm_e'],cfg['B']['utm_n']]);ab=B-A
    traj=[utm(t['xyz_enu']) for t in truth if start<=t['sim_s']<=start+duration]
    minB=min(float(np.linalg.norm(p-B)) for p in traj);cross=[abs(float(ab[0]*(p-A)[1]-ab[1]*(p-A)[0]))/float(np.linalg.norm(ab)) for p in traj]
    summary={'outcome':'FALLIDA: no navegación visual sostenida tras GNSS OUT',
        'requested_flight_effective_s':duration,'actual_pause_after_effective_s':control['sim_s']-start,'captures':len(rows),'processed':sum(p.get('processed',True) for p in preds),
        'capture_1hz_verified':len(rows)==duration and bool(np.allclose(np.diff(frame_times),1,atol=.012)),
        'capture_spacing_min_s':float(np.min(np.diff(frame_times))),'capture_spacing_max_s':float(np.max(np.diff(frame_times))),
        'all_models_cuda':all(v=='cuda:0' for v in gpu['proof']['model_devices'].values()) and all(set(v)=={'cuda:0'} for v in gpu['input_devices'].values()),
        'gnss_cut_effective_s':cut-start,'gnss_fusion_samples_after_settle':sum(bool(f.get('cs_gnss_pos')) for f in during),
        'ev_fusion_samples_after_cut':sum(bool(f.get('cs_ev_pos')) for f in during),'ev_fusion_intervals_effective_s':fusion_intervals,
        'visual_accepted':sum(r['visual_accepted'] for r in rows),'companion_admitted':sum(r['admitted_by_companion'] for r in rows),
        'valid_visual_fused_1hz_verified':all(r['visual_accepted'] and r['px4_ev_fused_samples_from_this_correction']>0 for r in rows if r['flight_s']>=5),
        'visual_error_mean_m':statistics.mean(errors) if errors else None,'visual_error_max_m':max(errors) if errors else None,
        'inference_mean_ms':statistics.mean(r['inference_ms'] for r in rows if r['image_processed']),'inference_max_ms':max(r['inference_ms'] for r in rows),
        'inferences_over_1second':sum(r['inference_ms']>1000 for r in rows),'max_correction_publication_delay_sim_s':max(r['capture_to_publication_sim_s'] for r in rows),
        'processing_1hz_deadline_verified':all(r['image_processed'] and r['inference_ms']<=1000 and r['capture_to_publication_sim_s']<=1 for r in rows),
        'fusion_per_correction_evidence':aid_evidence,
        'closest_B_truth_m':minB,'cross_track_p95_m':float(np.percentile(cross,95)),'arrived_B_20m_radius':minB<=20,
        'heading_error_mean_abs_deg':statistics.mean(abs(r['heading_error_deg']) for r in rows),
        'agl_error_mean_abs_m':statistics.mean(abs(r['agl_error_m']) for r in rows),
        'gyro_error_mean_abs_rad_s':[statistics.mean(abs(r[f'gyro_{k}_error_rad_s']) for r in rows) for k in 'xyz'],
        'raw_camera_rate_hz':5,'selected_captured_and_queued_hz':1,'odometry_propagation_hz_nominal':20,
        'sent_odometry_messages':len(sent),'same_orthophoto_map_and_scene':True,'cuda_proof':gpu['proof']}
    summary['received_odometry_ulog_samples']=len(ulog.get('vehicle_visual_odometry',[]))
    summary['corrections_with_direct_fusion_evidence']=[n for n,v in fused_by_second.items() if v>0]
    if summary['capture_1hz_verified'] and summary['all_models_cuda'] and summary['gnss_fusion_samples_after_settle']==0 and len(fusion_intervals)==1 and fusion_intervals[0][0]<=6 and fusion_intervals[0][1]>=duration-.1 and minB<=20:
        summary['outcome']='PASADA: navegación visual fusionada sostenida en este ensayo sintético'
    (out/'resumen.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
