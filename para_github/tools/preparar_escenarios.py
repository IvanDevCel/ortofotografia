"""Prepara mapas georreferenciados, índices CUDA y escenas separadas de Gazebo."""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'piloto_agl'))
sys.path.insert(0, str(ROOT / 'demo_sitl'))
from comun import setup, save_json
from geometria_navegacion import project


def wslpath(path):
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:] if os.name == 'nt' else str(path)


def ecef(lat, lon):
    import numpy as np
    lat, lon = math.radians(lat), math.radians(lon)
    e2 = 6.6943799901413165e-3
    n = 6378137 / math.sqrt(1 - e2 * math.sin(lat)**2)
    return np.array([n*math.cos(lat)*math.cos(lon), n*math.cos(lat)*math.sin(lon), n*(1-e2)*math.sin(lat)])


def prepare(path, index=True):
    import numpy as np
    import rasterio
    from rasterio.warp import transform
    from PIL import Image
    from datos import capture
    from indice import build
    from busqueda_orientaciones import quaternion_rpy

    slug = path.stem
    folder = ROOT / 'outputs/escenarios' / slug
    folder.mkdir(parents=True, exist_ok=True)
    pilot = setup()
    pilot.pop('zones', None)
    pilot.update(device='cuda:0', navigation_region=slug,
                 index_directory=f'outputs/escenarios/{slug}/indices')
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    with rasterio.open(path) as src:
        if src.count != 3 or src.crs is None or abs(src.transform.b) > 1e-9 or abs(src.transform.d) > 1e-9:
            raise ValueError('Se requiere GeoTIFF RGB norte arriba')
        crs = src.crs.to_string()
        center = np.array(src.transform * (src.width/2, src.height/2))
        lon, lat = transform(crs, 'EPSG:4326', [center[0]], [center[1]])
        lon, lat = lon[0], lat[0]
        phi, lam = math.radians(lat), math.radians(lon)
        tangent = np.array([[-math.sin(lam), math.cos(lam), 0],
                            [-math.sin(phi)*math.cos(lam), -math.sin(phi)*math.sin(lam), math.cos(phi)]])
        origin = ecef(lat, lon)
        def enu(e, n):
            lo, la = transform(crs, 'EPSG:4326', [float(e)], [float(n)])
            return tangent @ (ecef(la[0], lo[0]) - origin)
        U = np.column_stack([enu(center[0]+1, center[1]), enu(center[0], center[1]+1)])
        yaw = math.atan2(U[1, 0], U[0, 0])
        width, height = src.width*src.res[0], src.height*src.res[1]
        corners = [src.transform * p for p in [(0, src.height), (src.width, src.height), (src.width, 0), (0, 0)]]
        errors = [float(np.linalg.norm(enu(*p) - U @ (np.array(p)-center))) for p in corners]
        if max(errors) > .15:
            raise ValueError('La aproximación plana supera 15 cm en las esquinas')
        region = dict(id=slug, file=os.path.relpath(path, ROOT).replace('\\', '/'),
                      col=0, row=0, width=src.width, height=src.height)
        pilot['regions'] = [region]
        geo = dict(source=region['file'], crs=crs,
                   source_window={k:region[k] for k in ['col','row','width','height']},
                   resolution_grid_m_per_pixel=src.res[0], width_grid_m=width, height_grid_m=height,
                   texture_pixels=[src.width, src.height], texture_center_enu=[0,0],
                   utm_center=center.tolist(), latitude_deg=lat, longitude_deg=lon,
                   utm_to_enu_basis_per_metre=U.T.tolist(), grid_north_bearing_deg=-math.degrees(yaw),
                   enu_vertices=[[*enu(*p).tolist(), .003] for p in corners],
                   max_planar_approximation_error_m=max(errors),
                   terrain_model='plano horizontal z=0; ortofoto RGB sin DEM')
        def point(u, v):
            col, row = u*src.width, v*src.height
            e, n = src.transform * (col, row)
            lo, la = transform(crs, 'EPSG:4326', [e], [n])
            return dict(col=col, row=row, utm_e=e, utm_n=n, enu=(U@(np.array([e,n])-center)).tolist(),lat=la[0],lon=lo[0])
        a, b, takeoff = point(.30, .60), point(.70, .60), point(.40, .60)
        cfg = json.loads((ROOT/'config/demo_base.json').read_text(encoding='utf8'))
        cfg.update(georeference=geo,source_transform=list(src.transform)[:6],region=region,
                   source_tiff=region['file'],A=a,B=b,takeoff_target=takeoff,
                   mission_waypoints=[dict(b,label='B'),dict(a,label='A (vuelta)')],intermediate_waypoints=[],
                   route_note='A -> B -> A; regreso y órbita, sin aterrizaje',flight_effective_s=150,
                   pilot_config=f'outputs/escenarios/{slug}/piloto.json',map_image=f'outputs/escenarios/{slug}/mapa.jpg',
                   sitl_assets_subdir=f'escenarios/{slug}/assets',scenario=slug)
        texture = folder/'assets/models/ortho_terreno/materials/textures/ortofoto.png'
        texture.parent.mkdir(parents=True, exist_ok=True)
        rgb = Image.fromarray(src.read([1,2,3]).transpose(1,2,0))
        rgb.save(texture)
        rgb.resize((1000,1000),Image.Resampling.LANCZOS).save(folder/'mapa.jpg',quality=95)
        image, _, _ = capture(src, src.width/2, src.height/2, 100, 0, pilot['camera'])
        Image.fromarray(image).save(folder/'smoke.png')
        q = quaternion_rpy(0,0,math.radians(geo['grid_north_bearing_deg']))
        onboard = dict(capture_sim_s=10.,capture_px4_us_est=10000000,agl_baro_m=100.,q_capture_wxyz=q,
                       ref_lat=lat,ref_lon=lon,ref_alt=0.,roll_rad=0.,pitch_rad=0.,yaw_rad=math.radians(geo['grid_north_bearing_deg']),
                       gyro_frd_rad_s=[0.,0.,0.],velocity_ned_m_s=[0.,0.,0.],altitude_amsl_px4_m=100.,
                       attitude_age_s=0.,gyro_age_s=0.,velocity_age_s=0.,pressure_age_s=0.,
                       ground_pressure_hpa=1013.25,baro_pressure_hpa=1001.29,ground_datum_sim_m=0.)
        smoke = dict(image=f'outputs/escenarios/{slug}/smoke.png',onboard=onboard,
                     note='Imagen sintética de integración, no vuelo ni observación independiente')
    model = ET.Element('sdf',version='1.9')
    body=ET.SubElement(model,'model',name='ortho_terreno');ET.SubElement(body,'static').text='true'
    ET.SubElement(body,'pose').text=f'0 0 .003 0 0 {yaw}'
    link=ET.SubElement(body,'link',name='suelo');visual=ET.SubElement(link,'visual',name='ortofoto')
    plane=ET.SubElement(ET.SubElement(visual,'geometry'),'plane')
    ET.SubElement(plane,'normal').text='0 0 1'
    ET.SubElement(plane,'size').text=f'{width*np.linalg.norm(U[:,0])} {height*np.linalg.norm(U[:,1])}'
    material=ET.SubElement(visual,'material')
    ET.SubElement(material,'ambient').text='1 1 1 1';ET.SubElement(material,'diffuse').text='1 1 1 1'
    metal=ET.SubElement(ET.SubElement(material,'pbr'),'metal')
    ET.SubElement(metal,'albedo_map').text='model://ortho_terreno/materials/textures/ortofoto.png'
    ET.SubElement(metal,'metalness').text='0';ET.SubElement(metal,'roughness').text='1'
    ET.SubElement(visual,'cast_shadows').text='false'
    ET.indent(model)
    ET.ElementTree(model).write(folder/'assets/models/ortho_terreno/model.sdf',encoding='utf8',xml_declaration=True)
    shutil.copy2(ROOT/'sitl_assets/models/ortho_terreno/model.config',folder/'assets/models/ortho_terreno/model.config')
    shutil.copytree(ROOT/'sitl_assets/models/rc_cessna_ortho',folder/'assets/models/rc_cessna_ortho',dirs_exist_ok=True)
    world=ET.parse(ROOT/'sitl_assets/worlds/ortofoto.sdf');node=world.getroot().find('world')
    for include in list(node.findall('include')):
        if include.findtext('uri')!='model://ortho_terreno':node.remove(include)
    node.remove(node.find("model[@name='verificacion_mapa']"))
    node.find('spherical_coordinates/latitude_deg').text=str(lat)
    node.find('spherical_coordinates/longitude_deg').text=str(lon)
    # Sensors and noise come from the aircraft SDF; do not invent a pitot reading.
    aircraft=ET.parse(folder/'assets/models/rc_cessna_ortho/model.sdf')
    sensors=[]
    for sensor in aircraft.getroot().iter('sensor'):
        sensors.append(dict(name=sensor.get('name'),type=sensor.get('type'),
                            rate_hz=float(sensor.findtext('update_rate')),pose=sensor.findtext('pose'),
                            noise_xml=[ET.tostring(n,encoding='unicode') for n in sensor.iter('noise')]))
    camera=next(s for s in aircraft.getroot().iter('sensor') if s.get('name')=='nadir')
    if camera.findtext('camera/image/width')!='640' or abs(float(camera.findtext('camera/horizontal_fov'))-math.radians(70))>1e-8:
        raise ValueError('Cámara distinta de la calibración del localizador')
    cfg['sensor_contract']=dict(sensors=sensors,camera_mount_frd_m=[.05,0,.15],
                               airspeed_measurement_available=False,
                               visual_input='cámara, actitud/giroscopio, barómetro y velocidad estimada por PX4',
                               truth='Solo evaluación posterior; no se entrega al localizador')
    (folder/'assets/worlds').mkdir(parents=True,exist_ok=True)
    ET.indent(world);world.write(folder/'assets/worlds/ortofoto.sdf',encoding='utf8',xml_declaration=True)
    for name,data in [('piloto.json',pilot),('demo_base.json',cfg),('georreferencia.json',geo),
                      ('smoke_entrada.json',smoke),('sensores.json',cfg['sensor_contract']),
                      ('terreno.json',dict(ortho_top_z_m=.003,physical_ground_pose_after='0 0 0 0 0 0'))]:
        save_json(folder/name,data)
    if index:
        marker=folder/'indice_origen.json'
        signature=dict(sha256=digest,index=pilot['index'],camera=pilot['camera'],region=region,revision=json.loads((ROOT/'config/dinov2_revision.json').read_text()))
        expected=[folder/'indices'/f'{slug}_h{h:03d}.{ext}' for h in pilot['camera']['heights_m'] for ext in ['json','npz']]
        if not marker.exists() or json.loads(marker.read_text())!=signature or not all(p.exists() for p in expected):
            build(pilot);save_json(marker,signature)
        else:print('Índices existentes verificados:',slug,flush=True)
    print('Preparado:',folder,flush=True)
    return folder


def deploy(folder):
    script = ROOT/'tools/desplegar_escenario_wsl.py'
    subprocess.run(['wsl','-d','Ubuntu','--','python3',wslpath(script),wslpath(folder)],check=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--escenario',default='02_urbano_lliria')
    p.add_argument('--todos',action='store_true');p.add_argument('--sin-indices',action='store_true')
    args=p.parse_args();maps=ROOT.parent/'archivosTiff'
    files=sorted(maps.glob('*.tif')) if args.todos else [maps/(args.escenario+'.tif')]
    for file in files:
        folder=prepare(file,index=not args.sin_indices);deploy(folder)


if __name__=='__main__':main()
