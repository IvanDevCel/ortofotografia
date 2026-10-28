"""Marcos y propagación numérica; sin dependencia de Gazebo ni GNSS."""
import math

def qmul(a,b):
    w,x,y,z=a;v,i,j,k=b
    return [w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v]
def qunit(q):
    n=math.sqrt(sum(x*x for x in q));return [x/n for x in q]
def integrate_q(q,gyro,dt):
    r=math.sqrt(sum(x*x for x in gyro));theta=r*dt
    dq=[math.cos(theta/2),*[x/r*math.sin(theta/2) for x in gyro]] if r>1e-12 else [1.,0.,0.,0.]
    return qunit(qmul(q,dq))
def qrot(q,v):
    r=qmul(qmul(q,[0.,*v]),[q[0],-q[1],-q[2],-q[3]])
    return r[1:]
def euler(q):
    w,x,y,z=q
    return [math.atan2(2*(w*x+y*z),1-2*(x*x+y*y)),math.asin(max(-1,min(1,2*(w*y-z*x)))),math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))]
def project(lat,lon,lat0,lon0):
    """PX4 MapProjection: azimuthal equidistant, earth radius 6371000 m."""
    a,b,c,d=map(math.radians,[lat,lon,lat0,lon0]);dl=b-d
    v=max(-1,min(1,math.sin(c)*math.sin(a)+math.cos(c)*math.cos(a)*math.cos(dl)))
    angle=math.acos(v);k=angle/math.sin(angle) if abs(angle)>1e-10 else 1.
    return [6371000*k*(math.cos(c)*math.sin(a)-math.sin(c)*math.cos(a)*math.cos(dl)),6371000*k*math.cos(a)*math.sin(dl)]
def unproject(n,e,lat0,lon0):
    a,b=map(math.radians,[lat0,lon0]);rho=math.hypot(n,e)/6371000
    if rho<1e-12:return [lat0,lon0]
    xn,ye=n/6371000,e/6371000
    lat=math.asin(math.cos(rho)*math.sin(a)+xn*math.sin(rho)*math.cos(a)/rho)
    lon=b+math.atan2(ye*math.sin(rho),rho*math.cos(a)*math.cos(rho)-xn*math.sin(a)*math.sin(rho))
    return [math.degrees(lat),math.degrees(lon)]
