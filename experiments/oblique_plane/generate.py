"""Generate synthetic images and measured inputs; truth is a separate file."""
import json
from pathlib import Path
import numpy as np
import cv2
import rasterio
from rasterio.windows import Window
from rasterio.warp import transform
from geometry import chain,K_from,plane_rays,orientation,rotation,quaternion

HERE=Path(__file__).resolve().parent

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf8')

def geo(source,map_id):
    return json.loads((source/'para_github/outputs/escenarios'/map_id/'demo_base.json').read_text(encoding='utf8'))['georeference']

def camera_geo(camera,cal):
    U=np.array(cal['utm_to_enu_basis_per_metre']).T
    utm=np.array(cal['utm_center'])+np.linalg.solve(U,camera[:2]);lo,la=transform(cal['crs'],'EPSG:4326',[utm[0]],[utm[1]])
    return dict(utm_e_m=float(utm[0]),utm_n_m=float(utm[1]),latitude_deg=la[0],longitude_deg=lo[0],
                altitude_sim_datum_m=float(camera[2]),height_agl_m=float(camera[2]),
                altitude_reference='Simulation plane z=0; not real surveyed AMSL')

def render(src,cam,R,cfg,cal):
    h,w=cfg['camera']['height'],cfg['camera']['width'];K=K_from(cfg)
    yy,xx=np.indices((h,w));pixels=np.column_stack([xx.ravel(),yy.ravel()])
    ground=plane_rays(pixels,K,R,cam[2])+cam[:2]
    U=np.array(cal['utm_to_enu_basis_per_metre']).T
    utm=np.array(cal['utm_center'])+ground@np.linalg.inv(U).T
    inv=~src.transform;col=inv.a*utm[:,0]+inv.b*utm[:,1]+inv.c-.5;row=inv.d*utm[:,0]+inv.e*utm[:,1]+inv.f-.5
    x0,y0=int(np.floor(col.min()))-2,int(np.floor(row.min()))-2
    x1,y1=int(np.ceil(col.max()))+3,int(np.ceil(row.max()))+3
    if min(x0,y0)<0 or x1>src.width or y1>src.height:raise ValueError('Rendered footprint exits the map')
    patch=src.read([1,2,3],window=Window(x0,y0,x1-x0,y1-y0)).transpose(1,2,0)
    return cv2.remap(patch,(col-x0).reshape(h,w).astype('float32'),(row-y0).reshape(h,w).astype('float32'),cv2.INTER_LINEAR)

def generate(source,cfg):
    out=HERE/'outputs';rng=np.random.default_rng(cfg['seed']);truth=[];cases=[]
    sag='04_mar_costa_sagunto';lli='02_urbano_lliria'
    sites=[(sag,(.52,.40),'land_reference'),(sag,(.35,.12),'land_reference'),
           (lli,(.50,.50),'land_reference'),(lli,(.65,.55),'land_reference'),
           (sag,(.86,.45),'water_in_map'),(sag,(.76,.70),'water_in_map')]
    water=[]
    for site_index,(map_id,uv,category) in enumerate(sites):
        cal=geo(source,map_id);U=np.array(cal['utm_to_enu_basis_per_metre']).T
        with rasterio.open(source/'archivosTiff'/(map_id+'.tif')) as src:
            target_utm=np.array(src.transform*(uv[0]*src.width,uv[1]*src.height))
            target_xy=U@(target_utm-np.array(cal['utm_center']))
            for tilt in cfg['gimbal_tilts_deg']:
                index=len(cases)+1;case_id=f'{index:03d}'
                body=[0.,0.,float(site_index*23%90)] if tilt==0 else [3.,-2.,float(site_index*23%90)]
                gimbal=[0.,float(tilt),float([-30,0,45,90][site_index%4])]
                R,lever=chain(body,gimbal,cfg);h=cfg['height_body_agl_m']
                offset=plane_rays([[319.5,239.5]],K_from(cfg),R,h+lever[2])[0]
                body_xyz=np.r_[target_xy-offset-lever[:2],h];cam=body_xyz+lever
                image=render(src,cam,R,cfg,cal)
                measured_body=(np.array(body)+rng.normal(0,cfg['sensor_sigma']['body_angle_deg'],3)).tolist()
                measured_gimbal=(np.array(gimbal)+rng.normal(0,cfg['sensor_sigma']['gimbal_angle_deg'],3)).tolist()
                hm=float(h+rng.normal(0,cfg['sensor_sigma']['height_m']))
                measurement=dict(case_id=case_id,reference_map_id=map_id,capture_time_s=float(index),
                                 height_body_agl_m=hm,altitude_body_sim_datum_m=hm,altitude_reference='Simulation plane z=0',
                                 height_valid=True,body_rpy_deg=measured_body,gimbal_rpy_deg=measured_gimbal,
                                 body_quaternion_ned_wxyz=quaternion(rotation(*measured_body)).tolist(),
                                 gimbal_sample_time_s=float(index),attitude_sample_time_s=float(index),
                                 sigma=cfg['sensor_sigma'],static_ekf_origin_lat_deg=cal['latitude_deg'],
                                 static_ekf_origin_lon_deg=cal['longitude_deg'],
                                 note='No current body/camera latitude, longitude or truth orientation in estimator inputs')
                image_path=out/'images'/f'{case_id}.png';image_path.parent.mkdir(parents=True,exist_ok=True)
                cv2.imwrite(str(image_path),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))
                save(out/'measurements'/f'{case_id}.json',measurement)
                truth.append(dict(case_id=case_id,category=category,source_map_id=map_id,
                                  nominal_gimbal_tilt_deg=tilt,body=camera_geo(body_xyz,cal),
                                  camera=dict(**camera_geo(cam,cal),**orientation(R)),
                                  body_rpy_ned_deg=body,gimbal_rpy_deg=gimbal,
                                  body_quaternion_ned_wxyz=quaternion(rotation(*body)).tolist()))
                cases.append(case_id)
                if category=='water_in_map':water.append((image.copy(),measurement,truth[-1]))
    for image,measurement,t in water:
        case_id=f'{len(cases)+1:03d}';m=dict(measurement,case_id=case_id,reference_map_id=lli)
        save(out/'measurements'/f'{case_id}.json',m)
        cv2.imwrite(str(out/'images'/f'{case_id}.png'),cv2.cvtColor(image,cv2.COLOR_RGB2BGR))
        truth.append(dict(t,case_id=case_id,category='wrong_map_water',expected_reject=True));cases.append(case_id)
    for i in range(4):
        image,m,t=water[i];case_id=f'{len(cases)+1:03d}'
        constant=np.empty_like(image);constant[:]=np.median(image.reshape(-1,3),axis=0).astype('uint8')
        save(out/'measurements'/f'{case_id}.json',dict(m,case_id=case_id))
        cv2.imwrite(str(out/'images'/f'{case_id}.png'),cv2.cvtColor(constant,cv2.COLOR_RGB2BGR))
        truth.append(dict(t,case_id=case_id,category='uniform_water',expected_reject=True));cases.append(case_id)
    save(out/'cases.json',cases);save(out/'truth_evaluation_only.json',truth)
    save(out/'dataset_manifest.json',dict(cases=len(cases),tilts_deg=cfg['gimbal_tilts_deg'],seed=cfg['seed'],
                                        truth_separated=True,flights_started=0,second_rangefinder=False,terrain='plane z=0'))
    print(f'Generated {len(cases)} synthetic cases; truth stored separately.',flush=True)

if __name__=='__main__':
    manifest=json.loads((HERE/'baseline_manifest.json').read_text());generate(Path(manifest['source_root']),json.loads((HERE/'config.json').read_text()))
