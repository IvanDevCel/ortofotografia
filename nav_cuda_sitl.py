"""Sólo SITL: 45 capturas a 1Hz, odometría visual propagada a 20Hz."""
import os
os.environ['MAVLINK20']='1'
import argparse
from collections import deque
import datetime
import io
import json
import math
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image
from pymavlink import mavutil
from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image as GImage
from gz.msgs10.pose_v_pb2 import Pose_V
from gz.msgs10.clock_pb2 import Clock
from geometria_navegacion import integrate_q,qmul,euler,project
from coordinacion_demo import FlightSchedule

BASE=Path.home()/'uav-sitl'

def dump(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf8')
def stamp(t):return t.sec+t.nsec*1e-9
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('config');args=parser.parse_args()
    cfg=json.loads(Path(args.config).read_text(encoding='utf8'))
    schedule=FlightSchedule(cfg.get('flight_effective_s',45));total=schedule.duration_s
    report=Path(cfg['report_linux']);report.mkdir(parents=True,exist_ok=True)
    for d in ['imagenes','registros_px4','capturas','diagnosticos']:(report/d).mkdir(exist_ok=True)
    run=BASE/'ejecuciones'/cfg['run_name'];run.mkdir(exist_ok=False)
    repo=BASE/'PX4-Autopilot';binpath=repo/'build/px4_sitl_default/bin'
    registry=BASE/'demo_actual.json'
    if registry.exists():
        old=json.loads(registry.read_text());p=Path(f"/proc/{old['pid']}/cmdline")
        if p.exists() and b'/uav-sitl/PX4-Autopilot/' in p.read_bytes():raise RuntimeError('Cerrar la demo anterior primero')
    env=os.environ.copy();ax,ay=cfg['A']['enu']
    env.update(PX4_SYS_AUTOSTART='4003',PX4_SIM_MODEL='rc_cessna_ortho',PX4_GZ_WORLD='ortofoto',
        GALLIUM_DRIVER='d3d12',MESA_D3D12_DEFAULT_ADAPTER_NAME='NVIDIA',HEADLESS='1',PX4_GZ_STANDALONE='1',
        PX4_GZ_MODEL_POSE=f"{ax},{ay},{cfg.get('physical_ground_enu_z_m',0.)+.3},0,0,0",LD_LIBRARY_PATH='/usr/lib/wsl/lib:'+env.get('LD_LIBRARY_PATH',''),
        GZ_SIM_SERVER_CONFIG_PATH=str(repo/'src/modules/simulation/gz_bridge/server.config'),
        GZ_SIM_SYSTEM_PLUGIN_PATH=str(repo/'build/px4_sitl_default/src/modules/simulation/gz_plugins'))
    if not Path('/usr/lib/wsl/lib').exists():
        env.pop('GALLIUM_DRIVER',None);env.pop('MESA_D3D12_DEFAULT_ADAPTER_NAME',None)
        env['LD_LIBRARY_PATH']=os.environ.get('LD_LIBRARY_PATH','')
    env['GZ_SIM_RESOURCE_PATH']=':'.join(map(str,[BASE/'assets/models',BASE/'assets/worlds',repo/'Tools/simulation/gz/models',repo/'Tools/simulation/gz/worlds']))
    server=subprocess.Popen(['gz','sim','-r','-s',str(BASE/'assets/worlds/ortofoto.sdf')],cwd=run,env=env,stdout=(run/'gazebo_server.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
    time.sleep(2)
    proc=subprocess.Popen([str(binpath/'px4'),'-d'],cwd=run,env=env,stdout=(run/'px4_gazebo.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
    reg={'pid':proc.pid,'server_pid':server.pid,'run':str(run),'etapa':'nav_cuda','world':'ortofoto'};dump(registry,reg)
    link=mavutil.mavlink_connection('udpin:0.0.0.0:14540',source_system=255,source_component=191)
    link.port.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,8*1024*1024)
    lock=threading.RLock();sendlock=threading.Lock();fileslock=threading.Lock();stop=threading.Event();done=False
    state={'sim_s':0.,'start_sim_s':None,'phase':'PREPARACION','mode':'?','capture_count':0,'corrections':0,'gnss_cut_sim_s':None,
           'last_correction':None,'last_odom':None,'px4':{},'ref':None,'cpu_fallback':False}
    sensor={'q':[1.,0,0,0],'q_t':0.,'gyro':[0.,0,0],'gyro_t':0.,'vel':[0.,0,0],'vel_t':0.,'pressure':None,'pressure_t':0.,'altitude_amsl':None}
    gyros=deque(maxlen=4000);vels=deque(maxlen=4000);attitudes=deque(maxlen=4000);pressures=deque(maxlen=4000);altitudes=deque(maxlen=1000);offsets=deque(maxlen=200);p0=None;clock_offset=None
    frames={};last_image=None;airborne=False;anchor=None;nav_position=None;nav_time=None;request_count=0
    logfiles={name:(run/f'{name}.jsonl').open('w') for name in ['eventos','onboard','truth','odometria_enviada','orb','correcciones']}
    def log(name,row):
        with fileslock:logfiles[name].write(json.dumps(row,allow_nan=False)+'\n');logfiles[name].flush()
    def event(kind,**v):log('eventos',{'sim_s':state['sim_s'],'type':kind,**v})
    node=Node()
    def onclock(msg):
        with lock:state['sim_s']=stamp(msg.sim)
    def onpose(msg):
        t=stamp(msg.header.stamp)
        for p in msg.pose:
            if p.name=='rc_cessna_ortho_0':
                # This stream is evaluation-only and never read by navigation.
                log('truth',{'sim_s':t,'xyz_enu':[p.position.x,p.position.y,p.position.z],
                    'q_enu_flu_wxyz':[p.orientation.w,p.orientation.x,p.orientation.y,p.orientation.z]})
    def onboard_at(t):
        off=clock_offset if clock_offset is not None else (sum(offsets)/len(offsets) if offsets else 0.)
        tpx=t-off
        history=[(ts,qq) for ts,qq in attitudes if ts<=tpx]
        base_t,q0=history[-1] if history else (sensor['q_t'],sensor['q'])
        q=list(q0)
        # Integrate actual gyro samples between the last attitude and capture.
        prior_gyro=[gg for ts,gg in gyros if ts<=base_t]
        prev=base_t;g=list(prior_gyro[-1] if prior_gyro else sensor['gyro'])
        for ts,gg in gyros:
            if ts<base_t:continue
            if ts>tpx:break
            q=integrate_q(q,g,max(0,ts-prev));prev=ts;g=gg
        if tpx>=prev:q=integrate_q(q,g,tpx-prev)
        ps=[(ts,pp) for ts,pp in pressures if ts<=tpx];pt,pressure=ps[-1] if ps else (sensor['pressure_t'],sensor['pressure'])
        vv=[(ts,v) for ts,v in vels if ts<=tpx];vt,velocity=vv[-1] if vv else (sensor['vel_t'],sensor['vel'])
        aa=[a for ts,a in altitudes if ts<=tpx];altitude=aa[-1] if aa else sensor['altitude_amsl']
        agl=44330*(1-(pressure/p0)**.190294957) if pressure and p0 else 0.
        ref=state['ref'] or {'ref_lat':0.,'ref_lon':0.,'ref_alt':0.}
        r,p,y=euler(q)
        return {'capture_sim_s':t,'capture_px4_us_est':round(tpx*1e6),'clock_gz_minus_px4_s':off,
                'agl_baro_m':agl,'baro_pressure_hpa':pressure,'ground_pressure_hpa':p0,
                'altitude_amsl_px4_m':altitude,'ground_datum_sim_m':0.,
                'q_capture_wxyz':q,'roll_rad':r,'pitch_rad':p,'yaw_rad':y,'gyro_frd_rad_s':list(g),
                'velocity_ned_m_s':list(velocity),'attitude_age_s':tpx-base_t,
                'gyro_age_s':max(0,tpx-prev),'velocity_age_s':max(0,tpx-vt),
                'pressure_age_s':max(0,tpx-pt),**ref}
    def onimage(msg):
        nonlocal last_image,airborne
        t=stamp(msg.header.stamp)
        im=Image.frombytes('RGB',(msg.width,msg.height),msg.data,'raw','RGB',msg.step)
        buf=io.BytesIO();im.save(buf,format='JPEG',quality=96);blob=buf.getvalue()
        with lock:
            last_image=blob
            if state['start_sim_s'] is None:
                ob=onboard_at(t)
                if state.get('mission_started') and ob['agl_baro_m']>=3 and math.hypot(*sensor['vel'][:2])>5:
                    state['start_sim_s']=t;state['phase']='GNSS ON';event('EFFECTIVE_FLIGHT_START',definition='primer fotograma con baro AGL>=3m y velocidad PX4>5m/s')
                else:return
            elapsed=t-state['start_sim_s'];index=schedule.capture_index(state['start_sim_s'],t)
            if index is None or index in frames:return
            ob=onboard_at(t)
            record={'second':index,'capture_sim_s':t,'flight_s':elapsed,'onboard':ob,'phase':state['phase'],'image_file':f'imagenes/{index:03d}.jpg'}
            frames[index]=record;state['capture_count']=len(frames)
            (report/record['image_file']).write_bytes(blob)
            dump(report/'diagnosticos'/f'captura_{index:03d}.json',record)
            log('onboard',record)
    node.subscribe(Clock,'/world/ortofoto/clock',onclock)
    node.subscribe(Pose_V,'/world/ortofoto/dynamic_pose/info',onpose)
    node.subscribe(GImage,'/demo/nadir',onimage)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal last_image
            with lock:
                if self.path.startswith('/image'):
                    payload=last_image or b'';mime='image/jpeg'
                elif self.path.startswith('/frame/'):
                    n=int(self.path.split('/')[-1]);payload=json.dumps(frames.get(n)).encode();mime='application/json'
                else:payload=json.dumps({**state,'done':done}).encode();mime='application/json'
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)));self.send_header('Access-Control-Allow-Origin','*');self.end_headers();self.wfile.write(payload)
        def do_POST(self):
            nonlocal anchor,nav_position,nav_time
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if data.get('kind')=='frame_done':
                with lock:state['last_completed_second']=max(state.get('last_completed_second',0),data['second'])
                payload=json.dumps({'completed':state['last_completed_second']}).encode();self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
            with lock:
                now=state['sim_s'];age=now-data['capture_sim_s']
                data['arrival_sim_s']=now;data['delay_s']=age
                if data['accepted'] and 0<=age<=1.5:
                    # Integrate only measured/estimated on-board velocity from
                    # capture to arrival. No absolute PX4 or Gazebo position.
                    pos=list(data['ned']);prior=data['capture_sim_s'];v=data['onboard']['velocity_ned_m_s']
                    off=clock_offset or 0.
                    for ts,vv in vels:
                        tw=ts+off
                        if tw<=prior:continue
                        if tw>now:break
                        dt=tw-prior;pos=[pos[i]+v[i]*dt for i in range(2)];prior=tw;v=vv
                    pos=[pos[i]+v[i]*max(0,now-prior) for i in range(2)]
                    anchor=data;nav_position=pos;nav_time=now;state['corrections']+=1
                    state['last_correction']={k:v for k,v in data.items() if k!='onboard'}
                    data['admitted_by_companion']=True
                else:
                    data['admitted_by_companion']=False
                    if age>1.5:data['companion_rejection']='retardo de captura superior a 1.5 s'
                log('correcciones',data)
            payload=json.dumps({'received':True,'admitted':data['admitted_by_companion'],'arrival_sim_s':now,'delay_s':age}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def log_message(self,*a):pass
    http=ThreadingHTTPServer(('0.0.0.0',8768),Handler);threading.Thread(target=http.serve_forever,daemon=True).start()
    def receive(types=None,timeout=10):
        nonlocal p0,clock_offset,request_count
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            m=link.recv_match(blocking=True,timeout=.05)
            if m is None:
                if proc.poll() is not None:raise RuntimeError('PX4 terminó')
                continue
            typ=m.get_type()
            with lock:
                if typ=='TIMESYNC' and m.tc1==0:
                    with sendlock:link.mav.timesync_send(round(state['sim_s']*1e9),m.ts1)
                    request_count+=1
                elif typ=='HEARTBEAT':state['mode']=mavutil.mode_string_v10(m);state['px4']['armed']=bool(m.base_mode&128)
                elif typ=='HIGHRES_IMU':
                    t=m.time_usec/1e6;offsets.append(state['sim_s']-t)
                    sensor.update(gyro=[m.xgyro,m.ygyro,m.zgyro],gyro_t=t,pressure=m.abs_pressure,pressure_t=t)
                    gyros.append((t,[m.xgyro,m.ygyro,m.zgyro]))
                    pressures.append((t,m.abs_pressure))
                    if p0 is None and m.abs_pressure>0:p0=m.abs_pressure
                elif typ=='ATTITUDE_QUATERNION':
                    sensor.update(q=[m.q1,m.q2,m.q3,m.q4],q_t=m.time_boot_ms/1000);attitudes.append((m.time_boot_ms/1000,[m.q1,m.q2,m.q3,m.q4]))
                elif typ=='LOCAL_POSITION_NED':sensor.update(vel=[m.vx,m.vy,m.vz],vel_t=m.time_boot_ms/1000);vels.append((m.time_boot_ms/1000,[m.vx,m.vy,m.vz]))
                elif typ=='ALTITUDE':
                    sensor['altitude_amsl']=m.altitude_amsl if math.isfinite(m.altitude_amsl) else None;altitudes.append((m.time_usec/1e6,sensor['altitude_amsl']))
                elif typ=='GPS_RAW_INT':state['px4'].update(gps_fix=m.fix_type,gps_satellites=m.satellites_visible)
                elif typ=='GLOBAL_POSITION_INT':state['px4'].update(estimated_lat=m.lat/1e7,estimated_lon=m.lon/1e7)
                elif typ=='MISSION_CURRENT':state['px4']['mission_seq']=m.seq
                elif typ=='STATUSTEXT':event('STATUSTEXT',text=m.text);print('PX4:',m.text,flush=True)
            if types is None or typ in types:return m
        raise TimeoutError(str(types))
    def param(name,value,integer=True):
        wire=struct.unpack('<f',struct.pack('<i',int(value)))[0] if integer else float(value)
        with sendlock:link.mav.param_set_send(link.target_system,1,name.encode(),wire,6 if integer else 9)
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            with sendlock:link.mav.param_request_read_send(link.target_system,1,name.encode(),-1)
            try:m=receive(['PARAM_VALUE'],1)
            except TimeoutError:continue
            if m.param_id==name:
                actual=struct.unpack('<i',struct.pack('<f',m.param_value))[0] if integer else m.param_value
                if abs(actual-value)<.001:event('PARAM',name=name,value=actual);return
        raise RuntimeError('Parámetro no confirmado: '+name)
    def orb(topic):
        p=subprocess.run([str(binpath/'px4-listener'),topic,'-n','1'],capture_output=True,text=True,timeout=3)
        return p.stdout
    def orb_loop():
        while not stop.is_set():
            now=state['sim_s'];row={'sim_s':now}
            for topic in ['estimator_status_flags','estimator_aid_src_ev_pos','vehicle_visual_odometry','timesync_status']:
                try:row[topic]=orb(topic)
                except Exception as e:row[topic]=repr(e)
            flags=dict(re.findall(r'\b(cs_\w+):\s*(\w+)',row['estimator_status_flags']))
            with lock:state['fusion_flags']=flags;state['last_orb_sim_s']=now
            log('orb',row);stop.wait(.5)
    def odom_loop():
        nonlocal nav_position,nav_time
        previous=-1
        while not stop.wait(.008):
            with lock:
                now=state['sim_s']
                if now-previous<.05:continue
                previous=now
                if state['start_sim_s'] is None or state['gnss_cut_sim_s'] is None or anchor is None:continue
                age=now-anchor['capture_sim_s']
                if not 0<=age<=2.:continue
                dt=max(0,now-nav_time);v=list(sensor['vel'])
                nav_position=[nav_position[i]+v[i]*dt for i in range(2)];nav_time=now
                ob=onboard_at(now);q=ob['q_capture_wxyz'];gyro=ob['gyro_frd_rad_s']
                sigma2=anchor['sigma_horizontal_m']**2+(1.5*age)**2
                cov=[0.]*21;cov[0]=sigma2;cov[6]=sigma2;cov[11]=9.;cov[15]=cov[18]=math.radians(2)**2;cov[20]=math.radians(5)**2
                vc=[0.]*21;vc[0]=vc[6]=4.;vc[11]=9.;vc[15]=vc[18]=vc[20]=.1
                z=-(ob['agl_baro_m']-ob['ref_alt'])
                args=[round(now*1e6),1,1,nav_position[0],nav_position[1],z,q,*v,*gyro,cov,vc,0,3,80]
                with sendlock:link.mav.odometry_send(*args)
                record={'sample_sim_s':now,'last_image_second':anchor['second'],'last_image_capture_sim_s':anchor['capture_sim_s'],
                        'correction_age_s':age,'position_ned_m':[*nav_position,z],'q_ned_frd_wxyz':q,'velocity_ned_m_s':v,
                        'gyro_frd_rad_s':gyro,'position_variance_m2':sigma2,'capture_to_correction_delay_s':anchor['delay_s'],
                        'new_image':False,'origin':'visual correction propagated with onboard IMU/velocity; correlated'}
                state['last_odom']=record;log('odometria_enviada',record)
    def heartbeat_loop():
        while not stop.wait(.5):
            with sendlock:link.mav.heartbeat_send(6,8,0,0,0)
    threading.Thread(target=heartbeat_loop,daemon=True).start()
    def pause():
        return subprocess.run(['gz','service','-s','/world/ortofoto/control','--reqtype','gz.msgs.WorldControl','--reptype','gz.msgs.Boolean','--timeout','3000','--req','pause: true'],capture_output=True,text=True,timeout=6)
    try:
        hb=receive(['HEARTBEAT'],80);link.target_system=hb.get_srcSystem();link.target_component=1
        gui=subprocess.Popen(['gz','sim','-g'],env=env,stdout=(run/'gazebo_gui.log').open('w'),stderr=subprocess.STDOUT,start_new_session=True)
        reg['gui_pid']=gui.pid;dump(registry,reg)
        for n,val,integer in [('COM_RC_IN_MODE',4,True),('MIS_TKO_LAND_REQ',1,True),('SIM_GPS_USED',10,True),('EKF2_GPS_CTRL',7,True),
            ('EKF2_EV_CTRL',1,True),('EKF2_EV_NOISE_MD',0,True),('EKF2_EV_DELAY',0,False),('EKF2_HGT_REF',0,True),
            ('EKF2_EVP_NOISE',.7,False),('SDLOG_PROFILE',129,True),('MIS_TAKEOFF_ALT',50,False)]:param(n,val,integer)
        for mid,rate in [(105,20000),(31,20000),(32,20000),(141,100000),(24,200000),(33,100000),(111,10000)]:
            with sendlock:link.mav.command_long_send(link.target_system,1,511,0,mid,rate,0,0,0,0,0)
        # Read only the static EKF projection reference established before GNSS
        # loss, not the dynamic current coordinates as a visual measurement.
        end=time.monotonic()+20
        while time.monotonic()<end:
            try:receive(timeout=.2)
            except TimeoutError:pass
            if p0 and state['px4'].get('gps_fix',0)>=3 and len(offsets)>=40:break
        # Allow actual TIMESYNC responses to converge; do not fabricate replies.
        end=time.monotonic()+12
        while time.monotonic()<end:
            try:receive(timeout=.2)
            except TimeoutError:pass
        txt=orb('vehicle_local_position');(run/'referencia_ekf.txt').write_text(txt)
        ref={k:float(v) for k,v in re.findall(r'\b(ref_lat|ref_lon|ref_alt):\s*([-+0-9.e]+)',txt)}
        if len(ref)!=3 or abs(ref['ref_lat'])<1:raise RuntimeError('No se obtuvo la referencia estática NED del EKF')
        state['ref']=ref
        clock_offset=sorted(offsets)[len(offsets)//2]
        event('CLOCK_MAPPING',gz_minus_px4_seconds=clock_offset,timesync_requests_answered=request_count)
        (run/'timesync_antes.txt').write_text(orb('timesync_status'))
        bx,by=cfg['B']['enu'];meta=cfg['georeference']
        # Mission coordinates come from the surveyed map, never simulator truth.
        latb,lonb=cfg['B']['lat'],cfg['B']['lon'];latc,lonc=cfg['takeoff_target']['lat'],cfg['takeoff_target']['lon']
        waypoints=cfg.get('mission_waypoints',cfg.get('intermediate_waypoints',[])+[cfg['B']]);lastpoint=waypoints[-1]
        mission=[(22,latc,lonc,50,15,0)]+[(16,p['lat'],p['lon'],50,0,20) for p in waypoints]+[(17,lastpoint['lat'],lastpoint['lon'],50,0,70)]
        with sendlock:link.mav.mission_clear_all_send(link.target_system,1)
        receive(['MISSION_ACK'])
        with sendlock:link.mav.mission_count_send(link.target_system,1,len(mission))
        sent=set()
        while len(sent)<len(mission):
            m=receive(['MISSION_REQUEST_INT','MISSION_REQUEST'],15);i=m.seq;cmd,lat,lon,alt,p1,p2=mission[i]
            with sendlock:link.mav.mission_item_int_send(link.target_system,1,i,6,cmd,int(i==0),1,p1,0 if cmd==17 else p2,p2 if cmd==17 else 0,float('nan'),round(lat*1e7),round(lon*1e7),alt)
            sent.add(i)
        assert receive(['MISSION_ACK']).type==0
        # Frame and screenshot of THIS model before arming; GUI inspection gate.
        enc=subprocess.run([str(BASE/'venv/bin/python'),str(BASE/'scripts/encuadrar.py')],capture_output=True,text=True,timeout=13)
        if enc.returncode:raise RuntimeError('No armar: fallo de encuadre Gazebo')
        screenshot=subprocess.run(['import','-window','Gazebo Sim',str(report/'capturas/gazebo_antes_armar.png')],capture_output=True,text=True,timeout=5)
        if screenshot.returncode:raise RuntimeError('No armar: falta captura de la ventana Gazebo')
        event('GUI_CAPTURE_READY')
        # Require this run's warmed CUDA worker, camera AND opened video writer.
        ready_deadline=time.monotonic()+60;ready=False
        while time.monotonic()<ready_deadline:
            marker=report/'worker_listo'
            if marker.exists():
                try:
                    r=json.loads(marker.read_text());ready=r.get('run_name')==cfg['run_name'] and r.get('models_warm') and r.get('recorder_ready') and r.get('camera_ready')
                    if cfg.get('require_visual_gate'):
                        visual=json.loads((report/'gazebo_verificado.json').read_text());ready=ready and visual.get('run_name')==cfg['run_name'] and visual.get('plane_visible_on_ortho')
                except (ValueError,OSError):ready=False
            if ready:break
            try:receive(timeout=.1)
            except TimeoutError:pass
        if not ready:raise RuntimeError('No armar: trabajador CUDA/grabacion no preparados para esta ejecucion')
        event('WORKER_AND_VIDEO_READY')
        with sendlock:link.set_mode('MISSION');link.mav.command_long_send(link.target_system,1,400,0,1,0,0,0,0,0,0)
        while True:
            ack=receive(['COMMAND_ACK'])
            if ack.command==400:
                if ack.result!=0:raise RuntimeError('Armado rechazado '+str(ack.result))
                break
        with sendlock:link.mav.command_long_send(link.target_system,1,300,0,0,0,0,0,0,0,0)
        state['mission_started']=True
        threading.Thread(target=orb_loop,daemon=True).start();threading.Thread(target=odom_loop,daemon=True).start()
        subprocess.Popen([str(BASE/'venv/bin/python'),str(BASE/'scripts/encuadrar.py')],stdout=(run/'encuadre.log').open('w'),stderr=subprocess.STDOUT)
        print('VUELO ÚNICO EN CURSO; esperando inicio efectivo',flush=True)
        deadline=time.monotonic()+max(240,total*2+60);last=-1;cut_requested=False
        while time.monotonic()<deadline:
            try:receive(timeout=.1)
            except TimeoutError:pass
            if state['start_sim_s'] is None:continue
            elapsed=state['sim_s']-state['start_sim_s']
            if schedule.cut_due(state['start_sim_s'],state['sim_s']) and not cut_requested:
                cut_requested=True;state['phase']='GNSS OUT (solicitud)';event('GNSS_OUT_REQUEST')
                param('EKF2_GPS_CTRL',0);param('SIM_GPS_USED',0);state['gnss_cut_sim_s']=state['sim_s'];state['phase']='GNSS OUT'
                event('GNSS_OUT_CONFIRMED')
            if int(elapsed)!=last:
                last=int(elapsed)
                if last%5==0:print(f'{elapsed:.3f}s {state["phase"]} capturas={len(frames)} correcciones={state["corrections"]} fusion={state.get("fusion_flags",{}).get("cs_ev_pos")}',flush=True)
            if schedule.end_due(state['start_sim_s'],state['sim_s']):
                if len(frames)!=total:raise RuntimeError(f'Fin a {total} s: faltan capturas 0..{total-1}; no se rellenan')
                break
        pause();done=True;state['done']=True
        # Keep correction HTTP service and files alive for the final capture.
        closing_deadline=time.monotonic()+2
        while state.get('last_completed_second',0)<total and time.monotonic()<closing_deadline:time.sleep(.02)
        event('FINAL_CAPTURE_DRAIN',completed=state.get('last_completed_second',0),timeout=state.get('last_completed_second',0)<total)
        event('FLIGHT_END',captures=len(frames))
        dump(run/'resumen_control.json',{**state,'timesync_requests':request_count,'actual_duration_sim_s':state['sim_s']-(state['start_sim_s'] or state['sim_s'])})
        print('Vuelo terminado; pausado. Exportando registros.',flush=True)
        time.sleep(4)
    except Exception as exc:
        event('ERROR',message=str(exc));state['error']=str(exc);done=True;pause();raise
    finally:
        stop.set();pause();done=True
        for f in logfiles.values():f.flush()
        time.sleep(.6)
        try:subprocess.run([str(binpath/'px4-logger'),'stop'],capture_output=True,text=True,timeout=3)
        except subprocess.TimeoutExpired:event('LOGGER_STOP_TIMEOUT',message='Paused SITL: closing this PX4 process to flush log')
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
        dest=report/'registros_px4'
        for p in run.iterdir():
            if p.is_file():shutil.copy2(p,dest/p.name)
        # ULog is written to PX4's shared rootfs; match this run by mtime.
        for p in (repo/'build/px4_sitl_default/rootfs/log').rglob('*.ulg'):
            if p.stat().st_mtime>=run.stat().st_ctime:shutil.copy2(p,dest/p.name)
        dump(report/'control_final.json',{**state,'timesync_requests':request_count})
        time.sleep(8)

if __name__=='__main__':main()
