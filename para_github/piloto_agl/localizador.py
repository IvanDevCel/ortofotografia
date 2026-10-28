"""No lee verdad.json ni recibe coordenadas, zona de prueba, variante o giro real."""
from collections import OrderedDict
from time import perf_counter

import cv2
import numpy as np
import rasterio
import torch

from camara import footprint
from comun import ROOT
from datos import read_tile
from indice import descriptor, load_indices
from modelos import dino, local_models


def tensor_image(rgb,device='cpu'):
    return torch.from_numpy(rgb.transpose(2,0,1).copy()).to(device=device,dtype=torch.float32)/255


class Localizer:
    def __init__(self,cfg):
        if 'zones' in cfg or any(k in cfg for k in ('x_real','y_real','corners_px')):
            raise ValueError('El localizador no acepta configuración de generación ni verdad de referencia')
        self.cfg=cfg
        self.device=cfg.get('device','cpu')
        self.dino=dino(device=self.device)
        self.sp,self.lg=local_models(device=self.device,cfg=cfg)
        self.sift=cv2.SIFT_create(nfeatures=1024,contrastThreshold=.025)
        self.bf=cv2.BFMatcher(cv2.NORM_L2)
        self.indices=load_indices(cfg)
        self.sources={r['id']:rasterio.open(ROOT/r['file']) for r in cfg['regions']}
        self.cache={'lightglue':OrderedDict(),'sift':OrderedDict()}

    def close(self):
        for src in self.sources.values():
            src.close()

    def warmup(self):
        rgb=np.zeros((480,640,3),np.uint8)
        descriptor(self.dino,[rgb],self.cfg)
        with torch.inference_mode():
            self.sp.extract(tensor_image(rgb,self.device),resize=self.cfg['verification']['superpoint_resize'])
        self.sift.detectAndCompute(rgb,None)

    def retrieve(self,image,region,agl):
        start=perf_counter()
        vector=descriptor(self.dino,[image],self.cfg)[0]
        desc_ms=(perf_counter()-start)*1000
        start=perf_counter()
        tiles,vectors=self.indices[(region,agl)]
        scores=vectors@vector
        order=np.argsort(-scores,kind='stable')[:self.cfg['index']['top_k']]
        candidates=[{**tiles[i],'rank':rank,'similarity':float(scores[i])} for rank,i in enumerate(order,1)]
        return candidates,{'dino_descriptor_ms':desc_ms,'search_ms':(perf_counter()-start)*1000}

    def tile_image(self,tile):
        return read_tile(self.sources[tile['region']],tile['col'],tile['row'],tile['width'],tile['height'],640,480)

    def features(self,rgb,method):
        if method=='lightglue':
            with torch.inference_mode():
                return self.sp.extract(tensor_image(rgb,self.device),resize=self.cfg['verification']['superpoint_resize'])
        points,descriptors=self.sift.detectAndCompute(cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY),None)
        return np.array([p.pt for p in points],np.float32).reshape(-1,2),descriptors

    def cached_features(self,tile,method):
        cache=self.cache[method]
        key=tile['id']
        if key in cache:
            cache.move_to_end(key)
            return cache[key],True
        value=self.features(self.tile_image(tile),method)
        cache[key]=value
        if len(cache)>96:
            cache.popitem(last=False)
        return value,False

    def match(self,q,m,method):
        if method=='lightglue':
            if q['keypoints'].shape[1]<4 or m['keypoints'].shape[1]<4:
                return np.empty((0,2),np.float32),np.empty((0,2),np.float32)
            with torch.inference_mode():
                matches=self.lg({'image0':q,'image1':m})['matches'][0].cpu().numpy()
            return q['keypoints'][0].cpu().numpy()[matches[:,0]],m['keypoints'][0].cpu().numpy()[matches[:,1]]
        qp,qd=q
        mp,md=m
        if qd is None or md is None or len(md)<2:
            return np.empty((0,2),np.float32),np.empty((0,2),np.float32)
        pairs=self.bf.knnMatch(qd,md,k=2)
        good=[pair[0] for pair in pairs if len(pair)==2 and pair[0].distance<.75*pair[1].distance]
        return qp[[m.queryIdx for m in good]],mp[[m.trainIdx for m in good]]

    def geometry(self,qpoints,mpoints,tile,agl):
        cfg=self.cfg['verification']
        result={'tile_id':tile['id'],'rank':tile['rank'],'similarity':tile['similarity'],
                'matches':len(qpoints),'inliers':0,'inlier_ratio':0.,'coverage':0.,
                'median_reprojection_px':None,'score':0.,'valid':False,'reason':'menos de 4 correspondencias',
                'x_est':None,'y_est':None,'center_map_px':None,'polygon_map_px':None}
        if len(qpoints)<4:
            return result
        homography,mask=cv2.findHomography(qpoints,mpoints,cv2.RANSAC,cfg['ransac_px'],maxIters=2000,confidence=.999)
        if homography is None or mask is None or not np.isfinite(homography).all():
            result['reason']='homografía no estimable'
            return result
        accepted=mask.ravel().astype(bool)
        count=int(accepted.sum())
        if count<4:
            return result
        projected=cv2.perspectiveTransform(qpoints[None],homography)[0]
        median=float(np.median(np.linalg.norm(projected[accepted]-mpoints[accepted],axis=1)))
        coverage=float(cv2.contourArea(cv2.convexHull(qpoints[accepted]))/(640*480))
        points=np.array([[[319.5,239.5],[-.5,-.5],[639.5,-.5],[639.5,479.5],[-.5,479.5]]],np.float32)
        mapped=cv2.perspectiveTransform(points,homography)[0]
        center=mapped[0]
        polygon=mapped[1:]
        if not np.isfinite(mapped).all():
            result['reason']='proyección no finita'
            return result
        physical_area=abs(cv2.contourArea(polygon))*(tile['width']*tile['resolution']/640)*(tile['height']*tile['resolution']/480)
        area_ratio=physical_area/footprint(self.cfg['camera'],agl)['area_m2']
        col=tile['col']+(float(center[0])+.5)*tile['width']/640
        row=tile['row']+(float(center[1])+.5)*tile['height']/480
        a,b,c,d,e,f=tile['transform']
        x,y=a*col+b*row+c,d*col+e*row+f
        ratio=count/len(qpoints)
        score=count*ratio*max(coverage,0)**.5/(1+median)
        checks=[(count>=cfg['min_inliers'],'pocos inliers'),(ratio>=cfg['min_inlier_ratio'],'baja proporción de inliers'),
                (coverage>=cfg['min_coverage'],'poca cobertura de puntos'),(median<=cfg['max_median_reprojection_px'],'error geométrico'),
                (0<=center[0]<640 and 0<=center[1]<480,'centro fuera de candidata'),
                (cv2.isContourConvex(polygon),'huella no convexa'),
                (cfg['area_ratio_min']<=area_ratio<=cfg['area_ratio_max'],'escala incompatible con altura')]
        failed=[reason for ok,reason in checks if not ok]
        result.update(inliers=count,inlier_ratio=ratio,coverage=coverage,median_reprojection_px=median,
                      score=float(score),valid=not failed,reason=', '.join(failed) if failed else 'geometría coherente',
                      x_est=float(x),y_est=float(y),center_map_px=center.tolist(),polygon_map_px=polygon.tolist(),area_ratio=float(area_ratio))
        return result

    def verify(self,image,candidates,agl,method,deadline=None):
        start=perf_counter()
        q=self.features(image,method)
        extraction_ms=(perf_counter()-start)*1000
        start=perf_counter()
        diagnostics=[]
        misses=0
        for tile in candidates:
            if deadline is not None and perf_counter()+.04>=deadline:break
            m,hit=self.cached_features(tile,method)
            misses+=not hit
            qp,mp=self.match(q,m,method)
            diagnostics.append(self.geometry(qp,mp,tile,agl))
        verification_ms=(perf_counter()-start)*1000
        valid=sorted([d for d in diagnostics if d['valid']],key=lambda d:-d['score'])
        if not diagnostics:
            return {'accepted':False,'reason':'presupuesto agotado antes de verificar','confidence_score':0.,'confidence_is_probability':False,'x_est':None,'y_est':None,'best':None,'diagnostics':[],'query_features_ms':extraction_ms,'verification_ms':verification_ms,'map_feature_cache_misses':misses}
        best=valid[0] if valid else max(diagnostics,key=lambda d:d['score'])
        reason=best['reason']
        accepted=bool(valid)
        if accepted:
            for other in valid[1:]:
                distance=np.hypot(best['x_est']-other['x_est'],best['y_est']-other['y_est'])
                if distance>self.cfg['verification']['ambiguity_distance_m'] and other['score']>=best['score']*self.cfg['verification']['ambiguity_ratio']:
                    accepted=False
                    reason='candidatas geométricas ambiguas'
                    break
        confidence=min(1.,best['inliers']/80)*best['inlier_ratio']*min(1.,best['coverage']/.3)
        return {'accepted':accepted,'reason':reason,'confidence_score':confidence,'confidence_is_probability':False,
                'x_est':best['x_est'] if accepted else None,'y_est':best['y_est'] if accepted else None,
                'best':best,'diagnostics':diagnostics,'query_features_ms':extraction_ms,
                'verification_ms':verification_ms,'map_feature_cache_misses':misses}
