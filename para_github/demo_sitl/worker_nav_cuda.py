"""Procesa exactamente los 45 fotogramas, en CUDA, sin leer verdad Gazebo."""
import argparse
import base64
import io
import json
from pathlib import Path
import sys
import threading
import time
import urllib.request
import urllib.error
import http.client
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PIL import Image,ImageDraw,ImageFont
import numpy as np
import cv2
from localizador_cuda_nav import CudaNavigatorLocalizer
from cola_ultima_imagen import LatestFramePolicy
from coordinacion_demo import validate_onboard,route_points,AbsoluteVideoClock,publication_allowed

ROOT=Path(__file__).resolve().parent.parent
def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8768'+path,timeout=2) as r:return json.load(r)
def post(data):
    req=urllib.request.Request('http://127.0.0.1:8768/correction',data=json.dumps(data).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=3) as r:return json.load(r)
def safe(v):
    if isinstance(v,np.generic):return v.item()
    raise TypeError(str(type(v)))
def main():
    p=argparse.ArgumentParser();p.add_argument('--smoke',action='store_true');p.add_argument('--output-dir');p.add_argument('--keep-viewer',action='store_true');args=p.parse_args()
    last=json.loads((ROOT/'informes/ultima_prueba.json').read_text());out=Path(last['report']);cfg=json.loads((out/'configuracion.json').read_text(encoding='utf8'))
    total=int(cfg.get('flight_effective_s',45))
    source_out=out
    if args.output_dir:
        if not args.smoke:p.error('--output-dir se admite solo con --smoke')
        out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    engine=CudaNavigatorLocalizer(cfg.get('pilot_config'))
    (out/'cuda_dispositivos.json').write_text(json.dumps(engine.proof,indent=2))
    print('CUDA lista',engine.proof,flush=True)
    if args.smoke:
        source=json.loads((source_out/'smoke_entrada.json').read_text());validate_onboard(source['onboard'],temporal=False);rgb=np.array(Image.open(ROOT/source['image']).convert('RGB'))
        pred,rect=engine.locate_onboard(rgb,source['onboard'],cfg['georeference'])
        first_ms=pred['total_ms']
        pred,rect=engine.locate_onboard(rgb,source['onboard'],cfg['georeference'])
        cv2.imwrite(str(out/'smoke_rectificada.jpg'),cv2.cvtColor(rect,cv2.COLOR_RGB2BGR))
        proof={'proof':engine.proof,'calls':engine.calls,'input_devices':engine.input_devices,'cold_ms':first_ms,'warm_ms':pred['total_ms'],'result':pred,
               'note':'Prueba de integración histórica; no vuelo nuevo ni validación de error'}
        (out/'integracion_cuda.json').write_text(json.dumps(proof,default=safe,indent=2),encoding='utf8')
        if set(engine.calls)!={'DINOv2','SuperPoint','LightGlue'}:raise RuntimeError('No se ejecutaron los tres modelos CUDA')
        print('INTEGRACION',pred['accepted'],pred['total_ms'],'ms',engine.calls,flush=True);engine.engine.close();return
    # Exercise CUDA kernels before the one real flight starts. This is the same
    # single historical integration image, not extra flight observations.
    warm=json.loads((out/'smoke_entrada.json').read_text())
    validate_onboard(warm['onboard'],temporal=False)
    (out/'worker_listo').unlink(missing_ok=True)
    warm_rgb=np.array(Image.open(ROOT/warm['image']).convert('RGB'))
    for _ in range(2):engine.locate_onboard(warm_rgb,warm['onboard'],cfg['georeference'])
    # Historical warmup is not a valid visual anchor for a new flight.
    from recuperacion_temporal import TemporalRecovery
    engine.temporal=TemporalRecovery()
    latest={'state':{},'result':None,'image':None,'panel':None};guard=threading.Lock();exit_event=threading.Event()
    def portable_font(size):
        for file in ['C:/Windows/Fonts/arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
            try:return ImageFont.truetype(file,size)
            except OSError:pass
        return ImageFont.load_default(size=size)
    font=portable_font(21);title=portable_font(27)
    mapim=Image.open(ROOT/cfg.get('map_image','assets/mapa_T2.jpg')).convert('RGB').resize((600,600))
    def render():
        with guard:s=dict(latest['state']);r=latest['result'];blob=latest['image']
        im=Image.new('RGB',(1280,860),'#122337');d=ImageDraw.Draw(im)
        t=s.get('sim_s',0)-(s.get('start_sim_s') or s.get('sim_s',0));phase=s.get('phase','PREPARACION')
        if s.get('done') and 'PAUSADO' not in phase:phase='FIN · PAUSADO'
        d.text((20,16),f'RC Cessna · CUDA · vuelo {t:.1f} / {total} s',font=title,fill='white')
        d.text((850,16),phase,font=title,fill='#ffad8f' if 'OUT' in phase else '#78edbc')
        if blob:
            try:im.paste(Image.open(io.BytesIO(blob)).convert('RGB'),(20,70))
            except Exception:pass
        im.paste(mapim,(670,65))
        # Map extents are computed from the geotransform; no truth displayed live.
        reg=cfg['region'];tr=cfg['source_transform'];west=tr[2]+reg['col']*tr[0];north=tr[5]+reg['row']*tr[4]
        map_width=reg['width']*abs(tr[0]);map_height=reg['height']*abs(tr[4])
        def xy(e,n):return(int(670+(e-west)/map_width*600),int(65+(north-n)/map_height*600))
        route=route_points(cfg);points=[xy(p['utm_e'],p['utm_n']) for _,p in route];d.line(points,fill='#f5cf62',width=3)
        for (k,_),point in zip(route,points):d.ellipse((point[0]-5,point[1]-5,point[0]+5,point[1]+5),fill='#f5cf62');d.text(point,k,font=font,fill='white')
        correction=s.get('last_correction');age=None if not correction else s.get('sim_s',0)-correction['capture_sim_s']
        if correction:
            x,y=xy(correction['utm_e_body'],correction['utm_n_body']);d.rectangle((x-7,y-7,x+7,y+7),outline='#60f6b5',width=3)
        d.text((20,568),f'Capturadas: {s.get("capture_count",0)}/{total} · Correcciones válidas: {s.get("corrections",0)}',font=font,fill='white')
        if r:
            d.text((20,604),f'Imagen {r["second"]}: '+('ACEPTADA' if r['accepted'] else 'RECHAZADA')+f' · IA {r["total_ms"]:.0f} ms',font=font,fill='#73edb3' if r['accepted'] else '#ffc185')
            d.text((20,640),('Edad corrección: sin corrección' if age is None else f'Edad última corrección: {age:.2f} s')+f' · GPS fix {s.get("px4",{}).get("gps_fix","?")}',font=font,fill='white')
        flags=s.get('fusion_flags',{})
        d.text((20,686),f'PX4 {s.get("mode","?")} · GNSS fusionado: {flags.get("cs_gnss_pos","?")} · visión fusionada: {flags.get("cs_ev_pos","?")}',font=font,fill='white')
        d.text((20,728),'Captura + IA a 1 Hz. Odometría propagada a 20 Hz, con edad e incertidumbre.',font=font,fill='white')
        d.text((20,768),'Posición real Gazebo reservada al análisis posterior; no entra al navegador.',font=font,fill='#c1d7e9')
        d.text((20,808),f'DINOv2 + SuperPoint + LightGlue · {engine.proof["gpu"]} / CUDA.',font=font,fill='#f2d780')
        return im
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/panel'):
                with guard:payload=latest['panel'] or b''
                mime='image/jpeg'
            else:
                payload=b'<!doctype html><meta charset="utf-8"><title>RC Cessna CUDA - vision fusionada</title><style>body{margin:0;background:#122337}img{width:100%;max-width:1280px}</style><img id="p"><script>setInterval(()=>p.src="/panel.jpg?t="+Date.now(),200)</script>'
                mime='text/html'
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def log_message(self,*a):pass
    http=ThreadingHTTPServer(('127.0.0.1',18081),Handler);threading.Thread(target=http.serve_forever,daemon=True).start()
    recorder_ready=threading.Event();camera_ready=threading.Event()
    def video_loop():
        video=cv2.VideoWriter(str(out/'vuelo_visor.mp4'),cv2.VideoWriter_fourcc(*'mp4v'),5,(1280,860));timeline=AbsoluteVideoClock(duration=total);prev=None;s={};samples=[];repeated=0
        if not video.isOpened():return
        recorder_ready.set()
        while not exit_event.wait(.1):
            try:
                s=get('/status')
                with urllib.request.urlopen('http://127.0.0.1:8768/image',timeout=2) as response:blob=response.read()
                decoded=Image.open(io.BytesIO(blob));decoded.load()
                if decoded.size!=(640,480):raise ValueError('Camara nadiral con dimensiones inesperadas')
                camera_ready.set()
                with guard:latest['state']=s;latest['image']=blob
                im=render();buf=io.BytesIO();im.save(buf,format='JPEG',quality=91)
                with guard:latest['panel']=buf.getvalue()
                if s.get('start_sim_s') is not None:
                    t=s['sim_s']-s['start_sim_s']
                    if 0<=t<=total+1:
                        n=timeline.slots_due(s['start_sim_s'],s['sim_s'],finish=bool(s.get('done') and s.get('capture_count',0)>=total))
                        current=cv2.cvtColor(np.array(im),cv2.COLOR_RGB2BGR)
                        for _ in range(max(0,n-1)):video.write(prev if prev is not None else current)
                        repeated+=max(0,n-1);samples.append({'sim_s':s['sim_s'],'slot_frames':n,'repeated_frames':max(0,n-1),'camera_decoded':True})
                        if n:video.write(current)
                        prev=current
                        if int(t) in [4,6,20,40]:im.save(out/'capturas'/f'visor_{int(t):02d}.jpg')
                if s.get('done') and s.get('last_completed_second',0)>=total:
                    im.save(out/'capturas/final.jpg');break
            except Exception:continue
        with guard:s=dict(latest['state'])
        if prev is not None and s.get('start_sim_s') is not None:
            if cfg.get('stop_at_mission_end') and s.get('done'):
                timeline.duration_s=min(total,max(0,s['sim_s']-s['start_sim_s']))
                timeline.duration=timeline.duration_s
            tail=timeline.slots_due(s['start_sim_s'],s.get('sim_s',0),finish=bool(s.get('done') and s.get('capture_count',0)>=total))
            for _ in range(tail):video.write(prev)
            repeated+=tail
        video.release()
        (out/'video_timeline.json').write_text(json.dumps({'start_sim_s':s.get('start_sim_s'),'frames':timeline.frames,'fps':5,'duration_s':timeline.frames/5,'repeated_frames':repeated,'samples':samples,'gap_policy':'repeat previous observed frame; final tail repeated to absolute duration'}))
    video_thread=threading.Thread(target=video_loop,daemon=True);video_thread.start()
    if not recorder_ready.wait(5):raise RuntimeError('No se pudo preparar la grabacion; no autorizar armado')
    if not camera_ready.wait(45):raise RuntimeError('No hay camara nadiral decodificada; no autorizar armado')
    (out/'worker_listo').write_text(json.dumps({'run_name':cfg['run_name'],'models_warm':True,'recorder_ready':True,'camera_ready':True,'created_unix_s':time.time()}))
    rows=[];policy=LatestFramePolicy();discarded=[]
    def skip(frame,reason,now):
        n=frame['second'];row={'second':n,'capture_sim_s':frame['capture_sim_s'],'onboard':frame['onboard'],
            'accepted':False,'confidence_score':0.,'reason':reason,'total_ms':0.,'cuda_elapsed_ms':0.,
            'model_devices':engine.proof['model_devices'],'processed':False,'discarded_stale':True,
            'index_height_m':None,'rectified_fraction':0.,'utm_e_body':None,'utm_n_body':None,'lat_visual':None,'lon_visual':None,
            'transport_ack':{'admitted':False,'received':False,'delay_s':now-frame['capture_sim_s']}}
        rows.append(row);discarded.append(n)
        (out/'diagnosticos'/f'ia_{n:03d}.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf8')
        post({'kind':'frame_done','second':n,'capture_sim_s':frame['capture_sim_s'],'accepted':False})
        print(f'{n:02d}/{total} OMITIDA: {reason}',flush=True)
    try:
        while policy.last_selected<total:
            end=time.monotonic()+200;frame=None
            while time.monotonic()<end:
                try:
                    status=get('/status')
                except (urllib.error.URLError,TimeoutError,ConnectionError,HTTPException):
                    time.sleep(.04);continue
                n,dropped=policy.select(min(total,status.get('capture_count',0)))
                if n is not None:
                    for omitted in dropped:skip(get(f'/frame/{omitted}'),'reemplazada por una captura más reciente',status['sim_s'])
                    frame=get(f'/frame/{n}');break
                if status.get('done'):break
                time.sleep(.04)
            if not frame:
                if status.get('done'):break
                raise RuntimeError('No llegó una captura nueva; no se inventa una imagen')
            if not policy.may_start(frame['capture_sim_s'],status['sim_s']):
                skip(frame,'caducada antes de iniciar IA',status['sim_s']);continue
            rgb=np.array(Image.open(out/frame['image_file']).convert('RGB'))
            result,rect=engine.locate(rgb,frame['onboard'],cfg['georeference'])
            result.update(second=n,capture_sim_s=frame['capture_sim_s'],onboard=frame['onboard'],processed=True)
            now=get('/status')['sim_s'];packet=dict(result)
            if not policy.may_publish(frame['capture_sim_s'],now) or not publication_allowed(frame['capture_sim_s'],now,result['total_ms']/1000):
                packet['accepted']=False;packet['reason']='resultado caducado al terminar IA';result['discarded_stale']=True
            reply=post(packet);result['transport_ack']=reply;rows.append(result)
            cv2.imwrite(str(out/'imagenes'/f'{n:03d}_rectificada.jpg'),cv2.cvtColor(rect,cv2.COLOR_RGB2BGR))
            (out/'diagnosticos'/f'ia_{n:03d}.json').write_text(json.dumps(result,default=safe,ensure_ascii=False,indent=2),encoding='utf8')
            post({'kind':'frame_done','second':n,'capture_sim_s':frame['capture_sim_s'],'accepted':False})
            with guard:latest['result']=result
            print(f'{n:02d}/{total} CUDA {result["total_ms"]:.0f} ms aceptada={result["accepted"]} recibida={reply["admitted"]} retraso={reply["delay_s"]:.3f}s',flush=True)
        rows.sort(key=lambda r:r['second'])
        (out/'predicciones.json').write_text(json.dumps(rows,default=safe,ensure_ascii=False,indent=2),encoding='utf8')
        (out/'fotogramas_descartados.json').write_text(json.dumps(discarded))
        finish_deadline=time.monotonic()+5
        while time.monotonic()<finish_deadline:
            status=get('/status')
            if status.get('done'):break
            time.sleep(.04)
    finally:
        try:
            final_status=get('/status')
            with guard:latest['state']=final_status
        except (urllib.error.URLError,TimeoutError,ConnectionError,HTTPException):pass
        exit_event.set();video_thread.join(timeout=3)
        (out/'cuda_final.json').write_text(json.dumps({'proof':engine.proof,'input_devices':engine.input_devices,'calls':engine.calls,'frames_processed':sum(r.get('processed',True) for r in rows),'frames_observed':len(rows),'frames_skipped':discarded},indent=2))
        engine.engine.close()
        if args.keep_viewer:
            buf=io.BytesIO();render().save(buf,format='JPEG',quality=93)
            with guard:latest['panel']=buf.getvalue()
            print('Visor final disponible en http://localhost:18081/',flush=True)
            threading.Event().wait()
        http.shutdown()
if __name__=='__main__':main()
