"""Optical camera x-right/y-down/z-forward; body FRD; world ENU metres."""
import math
import numpy as np
import cv2

ENU_FROM_NED=np.array([[0.,1.,0.],[1.,0.,0.],[0.,0.,-1.]])
NADIR_BODY_FROM_CAMERA=np.array([[0.,-1.,0.],[1.,0.,0.],[0.,0.,1.]])

def rotation(roll,pitch,yaw):
    r,p,y=np.deg2rad([roll,pitch,yaw]);cr,sr=np.cos(r),np.sin(r);cp,sp=np.cos(p),np.sin(p);cy,sy=np.cos(y),np.sin(y)
    return np.array([[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],
                     [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]])

def quaternion(R):
    # Stable Hamilton quaternion from a proper rotation matrix.
    wxyz=np.array([1+R.trace(),1+R[0,0]-R[1,1]-R[2,2],1-R[0,0]+R[1,1]-R[2,2],1-R[0,0]-R[1,1]+R[2,2]])
    k=int(np.argmax(wxyz));q=np.zeros(4);q[k]=.5*np.sqrt(max(0,wxyz[k]));d=4*q[k]
    if k==0:q[1:]=[(R[2,1]-R[1,2])/d,(R[0,2]-R[2,0])/d,(R[1,0]-R[0,1])/d]
    elif k==1:q[[0,2,3]]=[(R[2,1]-R[1,2])/d,(R[0,1]+R[1,0])/d,(R[0,2]+R[2,0])/d]
    elif k==2:q[[0,1,3]]=[(R[0,2]-R[2,0])/d,(R[0,1]+R[1,0])/d,(R[1,2]+R[2,1])/d]
    else:q[[0,1,2]]=[(R[1,0]-R[0,1])/d,(R[0,2]+R[2,0])/d,(R[1,2]+R[2,1])/d]
    return q/np.linalg.norm(q)

def matrix(q):
    w,x,y,z=np.asarray(q)/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])

def K_from(cfg):
    c=cfg['camera'];f=c['width']/(2*np.tan(np.deg2rad(c['hfov_deg'])/2))
    return np.array([[f,0,(c['width']-1)/2],[0,f,(c['height']-1)/2],[0,0,1.]])

def chain(body_rpy,gimbal_rpy,cfg):
    RB=ENU_FROM_NED@rotation(*body_rpy);RG=rotation(*gimbal_rpy)
    lever=RB@(np.array(cfg['mount_origin_body_frd_m'])+RG@np.array(cfg['camera_offset_gimbal_frd_m']))
    return RB@RG@NADIR_BODY_FROM_CAMERA,lever

def plane_rays(pixels,K,R,height):
    pixels=np.asarray(pixels,float).reshape(-1,2)
    rays=(R@np.linalg.inv(K)@np.column_stack([pixels,np.ones(len(pixels))]).T).T
    if height<=0 or np.any(rays[:,2]>=-.05):raise ValueError('Invalid height or grazing/above-horizon ray')
    return -height*rays[:,:2]/rays[:,2:3]

def orthorectify(rgb,measurement,cfg,U):
    body=measurement['body_rpy_deg'];gimbal=measurement['gimbal_rpy_deg']
    R,lever=chain(body,gimbal,cfg);height=measurement['height_body_agl_m']+lever[2]
    K=K_from(cfg);h,w=rgb.shape[:2]
    corners=np.array([[-.5,-.5],[w-.5,-.5],[w-.5,h-.5],[-.5,h-.5]],float)
    xy=plane_rays(corners,K,R,height)@np.linalg.inv(U).T
    low,high=xy.min(0),xy.max(0);center=(low+high)/2
    width=max(high[0]-low[0],(high[1]-low[1])*w/h);height_grid=width*h/w
    west,north=center[0]-width/2,center[1]+height_grid/2
    target=np.column_stack([(xy[:,0]-west)/width*w-.5,(north-xy[:,1])/height_grid*h-.5])
    H=cv2.getPerspectiveTransform(corners.astype('float32'),target.astype('float32'))
    rect=cv2.warpPerspective(rgb,H,(w,h),flags=cv2.INTER_LINEAR)
    mask=cv2.warpPerspective(np.full((h,w),255,np.uint8),H,(w,h),flags=cv2.INTER_NEAREST)
    if (mask>0).mean()<.25:raise ValueError('Insufficient supported image area')
    effective_height=width/(2*np.tan(np.deg2rad(cfg['camera']['hfov_deg']/2)))
    return rect,mask,H,effective_height,R,lever

def orientation(R):
    axis=R[:,2];tilt=math.degrees(math.acos(np.clip(-axis[2],-1,1)))
    heading=math.degrees(math.atan2(axis[0],axis[1]))%360 if np.linalg.norm(axis[:2])>1e-8 else None
    return dict(quaternion_camera_to_enu_wxyz=quaternion(R).tolist(),matrix_camera_to_enu=R.tolist(),
                optical_frame_rpy_in_ned_deg=rpy_ned(R),
                optical_axis_off_nadir_deg=tilt,optical_axis_heading_deg=heading)

def rpy_ned(Renu):
    R=ENU_FROM_NED.T@Renu
    return np.rad2deg([np.arctan2(R[2,1],R[2,2]),np.arcsin(np.clip(-R[2,0],-1,1)),np.arctan2(R[1,0],R[0,0])]).tolist()
