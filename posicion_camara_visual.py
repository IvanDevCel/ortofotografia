"""Planar camera pose from matched map points; heading hypothesis is NOT a pose."""
import cv2
import numpy as np
from rasterio.warp import transform
from geometria_navegacion import project

def matched_camera_position(result,Hrect,tile,onboard,cal):
    if not result['accepted']:return
    best=result['best'];f=640/(2*np.tan(np.deg2rad(35)))
    K=np.array([[f,0,319.5],[0,f,239.5],[0,0,1.]],float)
    # Existing accepted homography corners suffice to reconstruct the same
    # projectivity. Undo rectification before recovering physical camera pose.
    rectcorners=np.array([[-.5,-.5],[639.5,-.5],[639.5,479.5],[-.5,479.5]],np.float32)
    mapped=np.array(best['polygon_map_px'],np.float64)
    raw=cv2.perspectiveTransform(rectcorners[None],np.linalg.inv(Hrect))[0].astype(np.float64)
    a,b,c,d,e,ff=tile['transform'];cols=tile['col']+(mapped[:,0]+.5)*tile['width']/640;rows=tile['row']+(mapped[:,1]+.5)*tile['height']/480
    utm=np.column_stack([a*cols+b*rows+c,d*cols+e*rows+ff]);origin=utm.mean(0)
    basis=np.array(cal['utm_to_enu_basis_per_metre']).T
    enu=(basis@(utm-origin).T).T
    obj=np.column_stack([enu,np.zeros(4)])
    ok,rv,tv=cv2.solvePnP(obj,raw,K,None,flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:raise ValueError('pose planar no estimable')
    R=cv2.Rodrigues(rv)[0];C=(-R.T@tv).ravel();optical=R.T[:,2]
    if C[2]<=0 or optical[2]>=-.15:raise ValueError('pose camera above-plane/downward check failed')
    mount=np.array([[0,-1,0],[1,0,0],[0,0,1.]],float)
    # Optical camera -> body FRD mounting; recovered attitude comes from
    # correspondences, NOT from selected descriptor angle or Gazebo.
    Rbody=R.T@mount.T;lever=Rbody@np.array([.05,0,.15])
    hcam=max(1.,onboard['agl_baro_m']+lever[2])
    if not .4<=C[2]/hcam<=2.5:raise ValueError('visual altitude incompatible with onboard AGL')
    # Intersect the ORIGINAL principal ray with the mapped plane, then lift
    # along its visually recovered direction using available onboard AGL.
    H=cv2.getPerspectiveTransform(raw.astype(np.float32),enu.astype(np.float32))
    ground=cv2.perspectiveTransform(np.array([[[319.5,239.5]]],np.float64),H)[0,0]
    camera_xy=ground+hcam*optical[:2]/optical[2]
    body_xy=camera_xy-lever[:2]
    ebody,nbody=origin+np.linalg.solve(basis,body_xy)
    lon,lat=transform('EPSG:25829','EPSG:4326',[ebody],[nbody])
    result.update(utm_e_body=float(ebody),utm_n_body=float(nbody),lat_visual=lat[0],lon_visual=lon[0],
        ned=project(lat[0],lon[0],onboard['ref_lat'],onboard['ref_lon']),
        camera_utm=(origin+np.linalg.solve(basis,camera_xy)).tolist(),
        original_principal_ray_ground_utm=(origin+np.linalg.solve(basis,ground)).tolist(),
        pose_camera_agl_visual_m=float(C[2]),camera_agl_onboard_m=float(hcam),
        camera_to_enu_from_matches=R.T.tolist(),body_to_enu_from_matches=Rbody.tolist(),
        position_method='original_principal_ray + matched_planar_pose + onboard_AGL + lever',
        selected_yaw_is_measured_heading=False)

