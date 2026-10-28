"""Budgeted visual continuity. No simulator truth or dynamic GNSS input."""
import time,math
import numpy as np
import cv2,torch
from geometria_navegacion import integrate_q,euler
from busqueda_orientaciones import rectify,quaternion_rpy,global_yaw_search
from posicion_camara_visual import matched_camera_position

class TemporalRecovery:
    def __init__(self):self.state=None
    def seed(self,result,ob,cal,tile):
        result=dict(result)
        matched_camera_position(result,np.array(result['rectification_H']),tile,ob,cal)
        R=np.array(result['body_to_enu_from_matches']);yaw=math.atan2(R[0,0],R[1,0]);r,p,_=euler(ob['q_capture_wxyz'])
        self.state=dict(xy=np.array([result['utm_e_body'],result['utm_n_body']]),q=quaternion_rpy(r,p,yaw),
            t=ob['capture_sim_s'],last_visual_t=ob['capture_sim_s'],velocity=np.array(ob['velocity_ned_m_s']),gyro=np.array(ob['gyro_frd_rad_s']))
    def locate(self,loc,rgb,ob,cal,budget_s=.9):
        from coordinacion_demo import validate_onboard
        validate_onboard(ob,temporal=True)
        start=time.perf_counter();deadline=start+budget_s;capture=ob['capture_sim_s'];h=max(1.,ob['agl_baro_m']);ih=min([50,100,200,300,400],key=lambda x:abs(np.log(x/h)))
        tiles=loc.engine.indices[('T2',ih)][0];basis=np.array(cal['utm_to_enu_basis_per_metre']).T
        s=self.state;age=None;radius=None
        if s is not None:
            dt=capture-s['t'];age=capture-s['last_visual_t']
            if dt<0:raise ValueError('capture timestamp regressed')
            vel=np.array(ob['velocity_ned_m_s']);gyro=np.array(ob['gyro_frd_rad_s'])
            avg=(vel+s['velocity'])/2;s['xy']+=np.linalg.solve(basis,[avg[1]*dt,avg[0]*dt]);s['q']=integrate_q(s['q'],(gyro+s['gyro'])/2,dt)
            s.update(t=capture,velocity=vel,gyro=gyro)
            radius=12+3*(1.5*age+.1*age**2)
        reliable=s is not None and age<=10 and radius<=90
        if not reliable:
            # Original 10-tile path only: no unbounded 80-pair fallback.
            result,rect=global_yaw_search(loc,rgb,ob,cal,recover_on_rejection=False,deadline=deadline)
            mode='global';pairs=len(result.get('diagnostics',[]))
        else:
            # Existing tiles ranked by predicted body proximity. The generous
            # radius grows with dead-reckoning age; no real XY enters this gate.
            centers=[]
            for tile in tiles:
                a,b,c,d,e,f=tile['transform'];center=np.array([c+a*(tile['col']+tile['width']/2),f+e*(tile['row']+tile['height']/2)])
                dist=float(np.linalg.norm(basis@(center-s['xy'])));half=.5*np.hypot(tile['width']*tile['resolution'],tile['height']*tile['resolution'])
                if dist<=radius+half:centers.append((dist,tile))
            centers.sort(key=lambda x:x[0]);pool=[dict(**z,rank=i+1,similarity=0.) for i,(_,z) in enumerate(centers[:4])]
            r,p,_=euler(ob['q_capture_wxyz']);yaw=euler(s['q'])[2]
            # Spatially and angularly diverse first probes, not adjacent
            # descriptor winners. Cache query per orientation, map via LRU.
            hypotheses=[];groups=[];pairs=0;rect=rgb
            for deg in [0,90,-90,180]:
                if time.perf_counter()+.07>=deadline:break
                q=quaternion_rpy(r,p,yaw+math.radians(deg));im,frac,H=rectify(rgb,q,cal)
                if frac<=.45:continue
                hypotheses.append((q,im,frac,H));query=loc.engine.features(im,'lightglue');diagnostics=[]
                for tile in pool:
                    if time.perf_counter()+.04>=deadline:break
                    feat,hit=loc.engine.cached_features(tile,'lightglue');qp,mp=loc.engine.match(query,feat,'lightglue');diagnostics.append(loc.engine.geometry(qp,mp,tile,h));pairs+=1
                if diagnostics:groups.extend((d,q,im,frac,H) for d in diagnostics)
                # A local angular probe is enough once strong geometry passes;
                # ambiguity is still checked across all four nearby tiles.
                # Verify neighbours before committing a marginal/edge result.
                # Continue to other orientations only if this neighbourhood
                # has no valid geometry; never loosen the original checks.
                if any(d['valid'] for d in diagnostics):break
            valid=sorted([g for g in groups if g[0]['valid']],key=lambda x:-x[0]['score'])
            chosen=valid[0] if valid else max(groups,key=lambda x:x[0]['score']) if groups else None
            if chosen:
                best,q,rect,frac,H=chosen;accepted=bool(valid);reason=best['reason'];v=loc.engine.cfg['verification']
                for other,*_ in valid[1:]:
                    if np.hypot(best['x_est']-other['x_est'],best['y_est']-other['y_est'])>v['ambiguity_distance_m'] and other['score']>=best['score']*v['ambiguity_ratio']:accepted=False;reason='candidatas geométricas ambiguas'
                result=dict(accepted=accepted,reason=reason,best=best,diagnostics=[g[0] for g in groups],x_est=best['x_est'],y_est=best['y_est'],
                    confidence_score=min(1.,best['inliers']/80)*best['inlier_ratio']*min(1.,best['coverage']/.3),rectification_H=H.tolist(),rectified_fraction=frac,
                    selected_q_wxyz=q,selected_yaw_is_measured_heading=False,utm_e_body=None,utm_n_body=None,lat_visual=None,lon_visual=None)
            else:result=dict(accepted=False,reason='presupuesto agotado sin candidata verificable',best=None,diagnostics=[],confidence_score=0.,rectified_fraction=0.,utm_e_body=None,utm_n_body=None,lat_visual=None,lon_visual=None)
            mode='temporal'
        anchor_before=self.state
        if result['accepted']:
            try:
                tile=next(z for z in tiles if z['id']==result['best']['tile_id']);self.seed(result,ob,cal,tile)
                matched_camera_position(result,np.array(result['rectification_H']),tile,ob,cal)
            except (ValueError,cv2.error) as ex:result.update(accepted=False,reason='pose física rechazada: '+str(ex))
        torch.cuda.synchronize();elapsed=time.perf_counter()-start
        if elapsed>=budget_s:result.update(accepted=False,reason='presupuesto de cálculo agotado; no publicar',discarded_stale=True)
        result.update(total_ms=elapsed*1000,cuda_elapsed_ms=None,index_height_m=ih,model_devices=loc.proof['model_devices'],
            temporal_reference_age_s=age,search_radius_m=radius,search_mode=mode,verified_pairs=pairs,compute_budget_s=budget_s,
            compute_deadline_met=elapsed<budget_s,capture_sim_s=capture,publication_limit_s=1.5,
            sigma_horizontal_m=max(1.,2*(1-result['confidence_score'])+.025*h),confidence_is_probability=False)
        # A timed-out candidate must never become the next visual anchor.
        if not result['accepted']:self.state=anchor_before
        return result,rect
