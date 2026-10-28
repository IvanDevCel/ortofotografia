"""Recuperación global de rumbo usando sólo imagen, mapa y roll/pitch a bordo."""
import math
import time
import cv2
import numpy as np
from geometria_navegacion import qrot,qmul,euler,project

def quaternion_rpy(r,p,y):
    return qmul(qmul([math.cos(y/2),0,0,math.sin(y/2)],[math.cos(p/2),0,math.sin(p/2),0]),[math.cos(r/2),math.sin(r/2),0,0])

def rectify(rgb,q,cal):
    f=640/(2*np.tan(np.deg2rad(35)));K=np.array([[f,0,319.5],[0,f,239.5],[0,0,1.]])
    R=np.column_stack([qrot(q,a) for a in np.eye(3)])
    mount=np.array([[0,-1,0],[1,0,0],[0,0,1.]])
    a=np.deg2rad(cal['grid_north_bearing_deg']);s,c=np.sin(a),np.cos(a)
    virtual=np.array([[-s,-c,0],[c,-s,0],[0,0,1.]])
    H=K@virtual.T@R@mount@np.linalg.inv(K)
    im=cv2.warpPerspective(rgb,H,(640,480),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    mask=cv2.warpPerspective(np.full((480,640),255,np.uint8),H,(640,480),flags=cv2.INTER_NEAREST)
    return im,float((mask>0).mean()),H

def body_from_ground(result,q,onboard,cal):
    from rasterio.warp import transform
    if not result['accepted']:return
    lever=qrot(q,[.05,0,.15]);b=cal['utm_to_enu_basis_per_metre'];U=np.array([[b[0][0],b[1][0]],[b[0][1],b[1][1]]])
    d=np.linalg.solve(U,np.array([lever[1],lever[0]]));e=result['x_est']-d[0];n=result['y_est']-d[1]
    lo,la=transform('EPSG:25829','EPSG:4326',[e],[n]);h=max(1,onboard['agl_baro_m'])
    result.update(utm_e_body=float(e),utm_n_body=float(n),lat_visual=la[0],lon_visual=lo[0],
        ned=project(la[0],lo[0],onboard['ref_lat'],onboard['ref_lon']),
        sigma_horizontal_m=max(.7,min(10.,2*(1-result['confidence_score'])+.015*h/max(.25,result['rectified_fraction']))))

def verify_neighbours(engine,image,rejected,tiles,agl,deadline):
    """Rescue a geometrically coherent centre outside its candidate, no truth."""
    seeds=[d for d in rejected if d['reason']=='centro fuera de candidata']
    choices={}
    for d in seeds:
        for t in tiles:
            a,b,c,dd,e,f=t['transform'];col=(d['x_est']-c)/a;row=(d['y_est']-f)/e
            if t['col']<=col<t['col']+t['width'] and t['row']<=row<t['row']+t['height']:
                choices[t['id']]={**t,'rank':d['rank'],'similarity':d['similarity']}
    if not choices or time.perf_counter()+.07>=deadline:return None
    return engine.verify(image,list(choices.values())[:4],agl,'lightglue',deadline=deadline)

def global_yaw_search(loc,rgb,onboard,cal,step_deg=15,recover_on_rejection=True,deadline=None):
    """Top 10 DISTINCT map tiles, same RANSAC/acceptance thresholds as baseline.

    No truth or estimated global position is used. A 360° image search retains
    roll/pitch as an onboard prior, and explicitly tests yaw independently.
    """
    import torch
    from indice import descriptor
    torch.cuda.synchronize();start=time.perf_counter()
    r,p,y=euler(onboard['q_capture_wxyz']);angles=[y]+[math.radians(a) for a in range(0,360,step_deg)]
    hypotheses=[]
    for angle in angles:
        q=quaternion_rpy(r,p,angle);im,fraction,H=rectify(rgb,q,cal)
        hypotheses.append({'q':q,'image':im,'fraction':fraction,'H':H,'yaw_deg':math.degrees(angle)%360})
    if all(a['fraction']<=.45 for a in hypotheses):
        return {'accepted':False,'reason':'rectificación inválida en todas las orientaciones','confidence_score':0.,'best':None,'diagnostics':[],'rectified_fraction':max(a['fraction'] for a in hypotheses),'utm_e_body':None,'utm_n_body':None,'lat_visual':None,'lon_visual':None},rgb
    h=max(1.,onboard['agl_baro_m']);index_h=min([50,100,200,300,400],key=lambda a:abs(np.log(a/h)))
    vectors=[]
    for i in range(0,len(hypotheses),6):
        if deadline is not None and time.perf_counter()+.06>=deadline:
            return {'accepted':False,'reason':'presupuesto agotado en DINO global','confidence_score':0.,'best':None,'diagnostics':[],'rectified_fraction':0.,'utm_e_body':None,'utm_n_body':None,'lat_visual':None,'lon_visual':None},rgb
        vectors.append(descriptor(loc.engine.dino,[a['image'] for a in hypotheses[i:i+6]],loc.engine.cfg))
    vectors=torch.from_numpy(np.concatenate(vectors)).cuda()
    scores=loc.index_gpu[('T2',index_h)]@vectors.T
    # Insufficient valid image area can never win the candidate search.
    invalid=[i for i,a in enumerate(hypotheses) if a['fraction']<=.45]
    if invalid:scores[:,invalid]=-float('inf')
    values,rotations=scores.max(dim=1);top,ids=torch.topk(values,10)
    tiles=loc.engine.indices[('T2',index_h)][0]
    candidates=[{**tiles[int(i)],'rank':k,'similarity':float(v),'hypothesis':int(rotations[int(i)])}
        for k,(i,v) in enumerate(zip(ids.cpu(),top.cpu()),1)]
    torch.cuda.synchronize();retrieval_ms=(time.perf_counter()-start)*1000
    groups=[]
    for k in sorted(set(c['hypothesis'] for c in candidates)):
        if deadline is not None and time.perf_counter()+.06>=deadline:break
        subset=[c for c in candidates if c['hypothesis']==k]
        result=loc.engine.verify(hypotheses[k]['image'],subset,h,'lightglue',deadline=deadline);result['hypothesis']=k
        if result['best'] is not None:groups.append(result)
    if not groups:
        return {'accepted':False,'reason':'presupuesto agotado en verificación global','confidence_score':0.,'best':None,'diagnostics':[],'rectified_fraction':0.,'utm_e_body':None,'utm_n_body':None,'lat_visual':None,'lon_visual':None},rgb
    valid=sorted([g for g in groups if g['accepted']],key=lambda a:-a['best']['score'])
    if not valid and deadline is not None:
        rescued=[]
        for g in groups:
            k=g['hypothesis'];other=verify_neighbours(loc.engine,hypotheses[k]['image'],g['diagnostics'],tiles,h,deadline)
            if other and other['best'] is not None:other['hypothesis']=k;rescued.append(other)
        groups+=rescued
        valid=sorted([g for g in groups if g['accepted']],key=lambda a:-a['best']['score'])
    recovery=False
    # The image-25 diagnostic proves two independent truncations: correct
    # tile at rank 17, successful yaw at its fourth descriptor hypothesis.
    # Preserve every baseline acceptance. Only on rejection, verify up to
    # 20 existing tiles x 4 image-scored rotations; no truth/XY prior enters.
    # RANSAC, geometry and cross-orientation ambiguity thresholds stay intact.
    if not valid and recover_on_rejection and (deadline is None or time.perf_counter()+.1<deadline):
        recovery=True
        more_values,more_ids=torch.topk(values,min(20,len(tiles)))
        expanded=[]
        for rank,(i,v) in enumerate(zip(more_ids.cpu(),more_values.cpu()),1):
            j=int(i)
            for k in torch.topk(scores[j],min(4,len(hypotheses))).indices.cpu().tolist():
                if hypotheses[k]['fraction']>.45:
                    expanded.append({**tiles[j],'rank':rank,'similarity':float(scores[j,k]),'hypothesis':k})
        initial_groups=groups;groups=[]
        for k in sorted(set(c['hypothesis'] for c in expanded)):
            if deadline is not None and time.perf_counter()+.06>=deadline:break
            subset=[c for c in expanded if c['hypothesis']==k]
            group=loc.engine.verify(hypotheses[k]['image'],subset,h,'lightglue',deadline=deadline)
            group['hypothesis']=k
            if group['best'] is not None:groups.append(group)
        if not groups:groups=initial_groups
        candidates=expanded
        valid=sorted([g for g in groups if g['accepted']],key=lambda a:-a['best']['score'])
    result=valid[0] if valid else max(groups,key=lambda a:a['best']['score'])
    verified_pairs=sum(len(g['diagnostics']) for g in groups)
    diagnostics=[d for g in groups for d in g['diagnostics']];result['diagnostics']=diagnostics
    result['map_feature_cache_misses']=sum(g['map_feature_cache_misses'] for g in groups)
    if valid:
        v=loc.engine.cfg['verification']
        for other in valid[1:]:
            if np.hypot(result['x_est']-other['x_est'],result['y_est']-other['y_est'])>v['ambiguity_distance_m'] and other['best']['score']>=result['best']['score']*v['ambiguity_ratio']:
                result['accepted']=False;result['reason']='orientaciones geométricas ambiguas'
    selected=hypotheses[result['hypothesis']]
    result.update(index_height_m=index_h,agl_used_m=h,rectified_fraction=selected['fraction'],rectification_H=selected['H'].tolist(),
        selected_q_wxyz=selected['q'],selected_yaw_deg=selected['yaw_deg'],hypotheses_count=len(hypotheses),retrieval_ms=retrieval_ms,
        recovery_on_rejection=recovery,verified_tile_orientation_pairs=verified_pairs,
        utm_e_body=None,utm_n_body=None,lat_visual=None,lon_visual=None,
        model_devices=loc.proof['model_devices'],candidates=candidates)
    body_from_ground(result,selected['q'],onboard,cal)
    torch.cuda.synchronize();result['total_ms']=(time.perf_counter()-start)*1000
    return result,selected['image']
