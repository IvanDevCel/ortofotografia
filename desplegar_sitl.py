"""Install copied scene and guarded PX4 patch; never starts simulation."""
import argparse,shutil,re,filecmp,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def patch_px4(base):
    module=base/'PX4-Autopilot/src/modules/simulation/gz_bridge';cpp=module/'GZBridge.cpp';config=module/'server.config'
    source=cpp.read_text(encoding='utf8');tree=ET.parse(config);plugins=[p for p in tree.getroot().iter('plugin') if 'magnetometer' in p.get('filename','')]
    if len(plugins)!=1:raise RuntimeError('Version no reconocida: magnetometro no identificado; no se modifica PX4')
    old=r'report\.x\s*=\s*-msg\.field_tesla\(\)\.y\(\);\s*report\.y\s*=\s*-msg\.field_tesla\(\)\.x\(\);\s*report\.z\s*=\s*msg\.field_tesla\(\)\.z\(\);'
    new='report.x = msg.field_tesla().x();\n\t\treport.y = -msg.field_tesla().y();\n\t\treport.z = -msg.field_tesla().z();'
    updated,count=re.subn(old,new,source)
    already=r'report\.x\s*=\s*msg\.field_tesla\(\)\.x\(\);\s*report\.y\s*=\s*-msg\.field_tesla\(\)\.y\(\);\s*report\.z\s*=\s*-msg\.field_tesla\(\)\.z\(\);'
    if count>1 or (count==0 and not re.search(already,source)):raise RuntimeError('Puente magnetico desconocido; no se modifica PX4')
    for key,value in [('use_earth_frame_ned','false'),('use_units_gauss','true')]:
        element=plugins[0].find(key)
        if element is None:element=ET.SubElement(plugins[0],key)
        element.text=value
    backup=base/'logs/antes_parche_portable';backup.mkdir(parents=True,exist_ok=True)
    for p in [cpp,config]:
        if not (backup/p.name).exists():shutil.copy2(p,backup/p.name)
    cpp.write_text(updated);ET.indent(tree,space='  ');tree.write(config,encoding='utf-8',xml_declaration=True)
def prepare(root,base):
    src=root/'sitl_assets';required=['models/ortho_terreno/materials/textures/ortofoto.png','models/poblacion_detalle/materials/textures/poblacion_detalle.png','models/indice_T2/materials/textures/textura_T2.png']
    missing=[p for p in required if not (src/p).is_file()]
    if missing:raise RuntimeError('Faltan texturas; copiar recursos antes de preparar SITL: '+', '.join(missing))
    for p in src.rglob('*'):
        if p.is_file():
            dest=base/'assets'/p.relative_to(src);dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists() and not filecmp.cmp(dest,p,shallow=False):raise RuntimeError('No se sobrescribe un recurso SITL distinto: '+str(dest))
            if not dest.exists():shutil.copy2(p,dest)
    (base/'scripts').mkdir(parents=True,exist_ok=True)
    for name in ['encuadrar.py','detener_demo.py','geometria_navegacion.py','coordinacion_demo.py']:shutil.copy2(root/'demo_sitl'/name,base/'scripts'/name)
    patch_px4(base)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--preparar',action='store_true');args=p.parse_args()
    if not args.preparar:raise SystemExit('Solo prepara al indicar --preparar. No ejecuta vuelos.')
    prepare(ROOT,Path.home()/'uav-sitl');print('Escena copiada y parche aplicado. Compilar PX4 antes de volar.')
if __name__=='__main__':main()
