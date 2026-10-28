"""Corrección visual con escala barométrica y actitud/giroscopio de a bordo."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'piloto_agl'))
import time
import cv2
import numpy as np
import torch
from comun import setup
from localizador import Localizer
from indice import descriptor
from geometria_navegacion import qrot,project
from rasterio.warp import transform

class CudaNavigatorLocalizer:
    def __init__(self):
        if not torch.cuda.is_available():raise RuntimeError('PRUEBA NO VÁLIDA: CUDA no disponible')
        cfg=setup();cfg.pop('zones');cfg['device']='cuda:0';cfg['regions']=[r for r in cfg['regions'] if r['id']=='T2']
        cfg['camera']['heights_m']=[50,100,200,300,400]
        torch.set_float32_matmul_precision('high')
        t=time.perf_counter();self.engine=Localizer(cfg);self.engine.warmup()
        self.calls={};self.input_devices={}
        def tensors(x):
            if torch.is_tensor(x):return [str(x.device)]
            if isinstance(x,dict):return sum([tensors(v) for v in x.values()],[])
            if isinstance(x,(list,tuple)):return sum([tensors(v) for v in x],[])
            return []
        for name,model in [('DINOv2',self.engine.dino),('SuperPoint',self.engine.sp),('LightGlue',self.engine.lg)]:
            if next(model.parameters()).device.type!='cuda':raise RuntimeError(name+' está en CPU')
            def hook(m,args,name=name):
                devices=tensors(args)
                if not devices or any(not d.startswith('cuda') for d in devices):raise RuntimeError(name+' recibió tensores fuera de CUDA')
                self.calls[name]=self.calls.get(name,0)+1;self.input_devices[name]=sorted(set(devices))
            model.register_forward_pre_hook(hook)
        # Extractor.extract calls SuperPoint.forward directly, bypassing the
        # parent __call__ hook. Inspect its first actual convolution instead.
        def superpoint_hook(module,args):
            devices=tensors(args)
            if any(not d.startswith('cuda') for d in devices):raise RuntimeError('SuperPoint recibió imagen CPU')
            self.calls['SuperPoint']=self.calls.get('SuperPoint',0)+1
            self.input_devices['SuperPoint']=sorted(set(devices))
        self.engine.sp.conv1a.register_forward_pre_hook(superpoint_hook)
        self.preparation_s=time.perf_counter()-t
        self.proof={'torch':torch.__version__,'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),
            'capability':torch.cuda.get_device_capability(0),'model_devices':{n:str(next(m.parameters()).device) for n,m in [('DINOv2',self.engine.dino),('SuperPoint',self.engine.sp),('LightGlue',self.engine.lg)]}}
        self.index_gpu={key:torch.from_numpy(v).cuda() for key,(tiles,v) in self.engine.indices.items()}
    def locate(self,rgb,onboard,calibration,heading_mode='temporal'):
        """Recover yaw visually; never assume PX4's yaw prior is trustworthy.

        The original single-attitude path remains explicit for regression and
        diagnosis. Acceptance thresholds are identical in both paths.
        """
        if {'truth','gazebo','gnss_lat','gnss_lon','px4_lat','px4_lon'}.intersection(onboard):raise ValueError('Entrada de verdad/GNSS prohibida')
        if heading_mode=='temporal':
            from recuperacion_temporal import TemporalRecovery
            if not hasattr(self,'temporal'):self.temporal=TemporalRecovery()
            return self.temporal.locate(self,rgb,onboard,calibration)
        if heading_mode=='onboard':return self.locate_onboard(rgb,onboard,calibration)
        if heading_mode!='global':raise ValueError('heading_mode debe ser global u onboard')
        if {'truth','gazebo','gnss_lat','gnss_lon','px4_lat','px4_lon'}.intersection(onboard):raise ValueError('Entrada de verdad/GNSS prohibida')
        from busqueda_orientaciones import global_yaw_search
        start_event=torch.cuda.Event(enable_timing=True);end_event=torch.cuda.Event(enable_timing=True);start_event.record()
        result,rect=global_yaw_search(self,rgb,onboard,calibration)
        end_event.record();torch.cuda.synchronize()
        result.update(cuda_elapsed_ms=start_event.elapsed_time(end_event),input_devices=dict(self.input_devices),calls=dict(self.calls),heading_mode='global_15deg_plus_onboard')
        return result,rect

    def locate_onboard(self,rgb,onboard,calibration):
        # No simulator truth or dynamic GNSS can be passed into this method.
        forbidden={'truth','gazebo','gnss_lat','gnss_lon','px4_lat','px4_lon'}
        if forbidden.intersection(onboard):raise ValueError('Entrada de verdad/GNSS prohibida')
        torch.cuda.synchronize();start=time.perf_counter();events=[torch.cuda.Event(enable_timing=True) for _ in range(2)];events[0].record()
        h=max(1.,onboard['agl_baro_m']);q=onboard['q_capture_wxyz']
        focal=640/(2*np.tan(np.deg2rad(35)));K=np.array([[focal,0,319.5],[0,focal,239.5],[0,0,1]],np.float64)
        R=np.column_stack([qrot(q,axis) for axis in [[1,0,0],[0,1,0],[0,0,1]]])
        mount=np.array([[0,-1,0],[1,0,0],[0,0,1]],float)
        angle=np.deg2rad(calibration['grid_north_bearing_deg']);si,co=np.sin(angle),np.cos(angle)
        virtual=np.array([[-si,-co,0],[co,-si,0],[0,0,1.]])
        H=K@virtual.T@R@mount@np.linalg.inv(K)
        rectified=cv2.warpPerspective(rgb,H,(640,480),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        mask=cv2.warpPerspective(np.full((480,640),255,np.uint8),H,(640,480),flags=cv2.INTER_NEAREST)
        valid_fraction=float((mask>0).mean())
        index_h=min([50,100,200,300,400],key=lambda a:abs(np.log(a/h)))
        vec=descriptor(self.engine.dino,[rectified],self.engine.cfg)[0]
        scores=self.index_gpu[('T2',index_h)]@torch.from_numpy(vec).cuda()
        values,ids=torch.topk(scores,10);tiles=self.engine.indices[('T2',index_h)][0]
        candidates=[{**tiles[int(i)],'rank':rank,'similarity':float(v)} for rank,(i,v) in enumerate(zip(ids.cpu(),values.cpu()),1)]
        result=self.engine.verify(rectified,candidates,h,'lightglue')
        events[1].record();torch.cuda.synchronize()
        result.update(index_height_m=index_h,agl_used_m=h,rectified_fraction=valid_fraction,
                      cuda_elapsed_ms=events[0].elapsed_time(events[1]),total_ms=(time.perf_counter()-start)*1000,
                      model_devices=self.proof['model_devices'],input_devices=dict(self.input_devices),calls=dict(self.calls))
        result['utm_e_body']=None;result['utm_n_body']=None;result['lat_visual']=None;result['lon_visual']=None
        if result['accepted'] and valid_fraction>.45:
            # Rectified image centre is vertically below the camera. Subtract
            # the lever arm expressed in NED, then invert UTM-to-ENU basis.
            lever=qrot(q,[.05,0,.15]);b=calibration['utm_to_enu_basis_per_metre']
            U=np.array([[b[0][0],b[1][0]],[b[0][1],b[1][1]]])
            delta=np.linalg.solve(U,np.array([lever[1],lever[0]]))
            e=result['x_est']-delta[0];n=result['y_est']-delta[1]
            lon,lat=transform('EPSG:25829','EPSG:4326',[e],[n]);ned=project(lat[0],lon[0],onboard['ref_lat'],onboard['ref_lon'])
            sigma=max(.7,min(10.,2*(1-result['confidence_score'])+.015*h/max(.25,valid_fraction)))
            # An empirical, conservative uncertainty, NOT a calibrated guarantee.
            result.update(utm_e_body=float(e),utm_n_body=float(n),lat_visual=lat[0],lon_visual=lon[0],ned=ned,
                          sigma_horizontal_m=sigma,uncertainty_model='geometry + baro/attitude term; empirical, uncalibrated')
        else:
            result['accepted']=False
            if valid_fraction<=.45:result['reason']='rectificación con menos del 45% de imagen válida'
        result['rectification_H']=H.tolist()
        return result,rectified
