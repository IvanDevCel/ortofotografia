"""Experimental oblique adapter. Accepts image, measured sensors and static map only."""
import time
import numpy as np
import cv2
import torch
from rasterio.warp import transform
from geometry import orthorectify,K_from,chain,plane_rays,orientation,rotation,NADIR_BODY_FROM_CAMERA,rpy_ned,quaternion

class ObliqueMatcher:
    def __init__(self,engine,calibration,cfg):
        self.engine,self.cal,self.cfg=engine,calibration,cfg
        self.region=engine.cfg['regions'][0]['id']
        self.U=np.array(calibration['utm_to_enu_basis_per_metre']).T

    def covariance(self,measurement,pixel):
        cfg=self.cfg
        x=np.r_[measurement['height_body_agl_m'],measurement['body_rpy_deg'],measurement['gimbal_rpy_deg'],pixel]
        def position(v):
            R,lever=chain(v[1:4],v[4:7],cfg)
            return -plane_rays([v[7:9]],K_from(cfg),R,v[0]+lever[2])[0]-lever[:2]
        steps=np.array([.001,*([.001]*6),.01,.01]);J=[]
        for i,step in enumerate(steps):
            a=x.copy();b=x.copy();a[i]+=step;b[i]-=step;J.append((position(a)-position(b))/(2*step))
        J=np.array(J).T;s=measurement['sigma']
        sigma=np.r_[s['height_m'],[s['body_angle_deg']]*3,[s['gimbal_angle_deg']]*3,[s['pixel_px']]*2]
        return J@np.diag(sigma*sigma)@J.T+np.eye(2)*s['map_m']**2

    def verify(self,rect,mask,H,tile,measurement,Rexpected,lever):
        q=self.engine.features(rect,'lightglue');m,_=self.engine.cached_features(tile,'lightglue')
        qp,mp=self.engine.match(q,m,'lightglue');v=self.cfg['verification']
        result=dict(accepted=False,reason='fewer than four matches',tile_id=tile['id'],matches=len(qp),inliers=0)
        if len(qp)<4:return result
        supported=cv2.erode(mask,np.ones((11,11),np.uint8))
        ix=np.clip(np.rint(qp[:,0]).astype(int),0,639);iy=np.clip(np.rint(qp[:,1]).astype(int),0,479)
        keep=supported[iy,ix]>0;qp,mp=qp[keep],mp[keep]
        if len(qp)<4:return result
        hom,inliers=cv2.findHomography(qp,mp,cv2.RANSAC,3.,maxIters=2000,confidence=.999)
        if hom is None or inliers is None:return result
        keep=inliers.ravel().astype(bool);count=int(keep.sum());result['inliers']=count
        raw=cv2.perspectiveTransform(qp[None],np.linalg.inv(H))[0]
        coverage=float(cv2.contourArea(cv2.convexHull(raw[keep]))/(640*480)) if count>=3 else 0.
        eig=np.linalg.eigvalsh(np.cov(raw[keep].T)) if count>=3 else [0.,1.]
        eigen_ratio=float(eig[0]/max(eig[1],1e-12))
        ratio=count/max(1,len(qp));result.update(inlier_ratio=ratio,coverage=coverage,eigen_ratio=eigen_ratio)
        if count<v['min_inliers'] or ratio<v['min_inlier_ratio'] or coverage<v['min_coverage'] or eigen_ratio<v['min_eigen_ratio']:
            result['reason']='insufficient or poorly distributed inliers';return result
        a,b,c,d,e,f=tile['transform'];cols=tile['col']+(mp[keep,0]+.5)*tile['width']/640;rows=tile['row']+(mp[keep,1]+.5)*tile['height']/480
        utm=np.column_stack([a*cols+b*rows+c,d*cols+e*rows+f]);origin=utm.mean(0)
        local=(utm-origin)@self.U.T;obj=np.column_stack([local,np.zeros(count)]).astype('float64')
        K=K_from(self.cfg);image=raw[keep].astype('float64')
        solutions=cv2.solvePnPGeneric(obj,image,K,None,flags=cv2.SOLVEPNP_IPPE)
        good=[]
        if not solutions[0]:result['reason']='planar PnP failed';return result
        for rv,tv in zip(solutions[1],solutions[2]):
            rv,tv=cv2.solvePnPRefineLM(obj,image,K,None,rv,tv)
            Rc=cv2.Rodrigues(rv)[0];Rwc=Rc.T;C=(-Rwc@tv).ravel()
            projected=cv2.projectPoints(obj,rv,tv,K,None)[0].reshape(-1,2)
            error=float(np.median(np.linalg.norm(projected-image,axis=1)))
            disagreement=float(np.rad2deg(np.arccos(np.clip((np.trace(Rexpected.T@Rwc)-1)/2,-1,1))))
            positive=np.all((Rc@obj.T+tv) [2]>0)
            h_expected=measurement['height_body_agl_m']+lever[2]
            if positive and C[2]>0 and abs(C[2]-h_expected)<=max(2.,3*measurement['sigma']['height_m']) and disagreement<=v['max_orientation_disagreement_deg'] and error<=v['max_median_reprojection_px']:
                good.append((error,C,Rwc,disagreement))
        if not good:result['reason']='pose fails height, orientation, depth or reprojection checks';return result
        error,C,Rwc,disagreement=min(good,key=lambda p:p[0])
        covariance=self.covariance(measurement,image.mean(0));sigma=float(np.sqrt(np.linalg.eigvalsh(covariance).max()))
        if sigma>v['max_xy_sigma_m']:result['reason']='geometric uncertainty too large';return result
        camera_utm=origin+np.linalg.solve(self.U,C[:2]);body_utm=origin+np.linalg.solve(self.U,C[:2]-lever[:2])
        RB=Rwc@(rotation(*measurement['gimbal_rpy_deg'])@NADIR_BODY_FROM_CAMERA).T
        lo,la=transform(self.cal['crs'],'EPSG:4326',[body_utm[0],camera_utm[0]],[body_utm[1],camera_utm[1]])
        result.update(accepted=True,reason='verified oblique planar pose',median_reprojection_px=error,
                      orientation_disagreement_deg=disagreement,score=count*ratio*np.sqrt(coverage)/(1+error),
                      body_utm=body_utm.tolist(),camera_utm=camera_utm.tolist(),
                      body=dict(latitude_deg=la[0],longitude_deg=lo[0],altitude_sim_datum_m=float(C[2]-lever[2]),height_agl_m=float(C[2]-lever[2]),
                                measured_rpy_ned_deg=measurement['body_rpy_deg'],estimated_rpy_ned_deg=rpy_ned(RB),
                                quaternion_body_to_enu_wxyz=quaternion(RB).tolist()),
                      camera=dict(latitude_deg=la[1],longitude_deg=lo[1],altitude_sim_datum_m=float(C[2]),height_agl_m=float(C[2]),
                                  **orientation(Rwc),measured_gimbal_rpy_deg=measurement['gimbal_rpy_deg']),
                      covariance_xy_m2=covariance.tolist(),max_xy_sigma_m=sigma,
                      covariance_note='First-order ray/sensor approximation; excludes map-association ambiguity and correlated feature errors')
        return result

    def locate(self,rgb,measurement):
        start=time.perf_counter()
        if not measurement.get('height_valid') or measurement.get('height_body_agl_m',0)<=0:
            return dict(accepted=False,reason='invalid height',total_ms=0.)
        try:
            rect,mask,H,effective,R,lever=orthorectify(rgb,measurement,self.cfg,self.U)
            heights=self.engine.cfg['camera']['heights_m'];height=min(heights,key=lambda h:abs(np.log(h/effective)))
            candidates,_=self.engine.retrieve(rect,self.region,height)
            diagnostics=[self.verify(rect,mask,H,t,measurement,R,lever) for t in candidates]
            valid=sorted([d for d in diagnostics if d['accepted']],key=lambda d:-d['score'])
            result=dict(accepted=False,reason='no valid candidate',diagnostics=diagnostics)
            if valid:
                result=dict(valid[0],diagnostics=diagnostics)
                for other in valid[1:]:
                    if np.linalg.norm(np.array(other['body_utm'])-result['body_utm'])>20 and other['score']>=.90*result['score']:
                        result.update(accepted=False,reason='ambiguous map candidates');break
            result.update(index_height_m=height,effective_virtual_height_m=effective,supported_fraction=float((mask>0).mean()))
        except (ValueError,cv2.error) as error:
            result=dict(accepted=False,reason=str(error))
        torch.cuda.synchronize();result['total_ms']=(time.perf_counter()-start)*1000
        return result
