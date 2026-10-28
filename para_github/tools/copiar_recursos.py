"""Dry-run inventory; --copiar copies external resources without rebuilding."""
import argparse,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--origen',type=Path,required=True);p.add_argument('--copiar',action='store_true');args=p.parse_args();src=args.origen.resolve()
    if src==ROOT.resolve():raise SystemExit('Origen y destino deben ser carpetas diferentes.')
    pairs=[('.modelos_agl','.modelos_agl'),('outputs/piloto_agl/indices','outputs/piloto_agl/indices')]
    pairs += [(n,n) for n in ['PNOA_MA_OF_ETRS89_HU29_h25_0001_2.tif','PNOA_MA_OF_ETRS89_HU29_h25_0002_4.tif']]
    pairs += [('outputs/demo_sitl/assets/models/ortho_terreno/materials/textures/ortofoto.png','sitl_assets/models/ortho_terreno/materials/textures/ortofoto.png'),('outputs/demo_sitl/assets/models/ortho_terreno/materials/textures/poblacion_detalle.png','sitl_assets/models/poblacion_detalle/materials/textures/poblacion_detalle.png'),('outputs/demo_integrada/textura_T2.png','sitl_assets/models/indice_T2/materials/textures/textura_T2.png')]
    rows=[]
    for old,new in pairs:
        source=src/old;dest=ROOT/new;exists=source.exists();rows.append(dict(source=old,destination=new,exists=exists))
        if args.copiar and exists:
            if dest.exists():raise SystemExit('No se sobrescribe un recurso existente: '+str(dest))
            dest.parent.mkdir(parents=True,exist_ok=True)
            if source.is_dir():shutil.copytree(source,dest,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            else:shutil.copy2(source,dest)
    print(json.dumps(dict(mode='copy' if args.copiar else 'dry-run',resources=rows),indent=2))
    if any(not r['exists'] for r in rows):raise SystemExit('Faltan recursos de origen; no se indexa ni descarga nada automáticamente.')
if __name__=='__main__':main()
