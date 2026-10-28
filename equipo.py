"""Inventory by default. Installs ONLY into a new .venv with explicit instalar."""
import argparse,json,os,platform,shutil,subprocess,sys,time,venv
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def command(args):
    try:
        r=subprocess.run(args,capture_output=True,timeout=12)
        def decode(data):return data.decode('utf-16-le' if b'\x00' in data else 'utf8',errors='replace').strip()
        return dict(code=r.returncode,stdout=decode(r.stdout),stderr=decode(r.stderr))
    except (OSError,subprocess.TimeoutExpired) as ex:return dict(code=-1,error=str(ex))
def inspect(check_imports=False):
    result=dict(platform=platform.platform(),python=sys.version,executable=sys.executable,git=shutil.which('git'),gpu=command(['nvidia-smi','--query-gpu=name,driver_version,memory.total','--format=csv,noheader']),wsl=command(['wsl','--list','--quiet']) if os.name=='nt' else None)
    if check_imports:
        imports={}
        for name in ['numpy','rasterio','PIL','cv2','matplotlib','psutil','einops','omegaconf','torch','torchvision','lightglue','openpyxl']:
            try:
                mod=__import__(name);imports[name]=dict(ok=True,version=getattr(mod,'__version__',None))
                if name=='torch':imports[name].update(cuda=mod.cuda.is_available(),gpu=mod.cuda.get_device_name(0) if mod.cuda.is_available() else None)
            except Exception as ex:imports[name]=dict(ok=False,error=str(ex))
        result['imports']=imports
    result['resources']={
        'tiff_T2':(ROOT/'PNOA_MA_OF_ETRS89_HU29_h25_0002_4.tif').is_file(),
        'indices_T2':all((ROOT/f'outputs/piloto_agl/indices/T2_h{h:03d}.{ext}').is_file() for h in [50,100,200,300,400] for ext in ['json','npz']),
        'dino_revision':(ROOT/'.modelos_agl/dinov2_revision.json').is_file(),
        'sitl_textures':all((ROOT/p).is_file() for p in ['sitl_assets/models/ortho_terreno/materials/textures/ortofoto.png','sitl_assets/models/poblacion_detalle/materials/textures/poblacion_detalle.png','sitl_assets/models/indice_T2/materials/textures/textura_T2.png'])}
    return result
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['diagnostico','instalar']);p.add_argument('--perfil',choices=['auto','cpu','cuda'],default='auto');p.add_argument('--imports',action='store_true');p.add_argument('--json',type=Path);args=p.parse_args();report=inspect(args.imports)
    if args.json:args.json.parent.mkdir(parents=True,exist_ok=True);args.json.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))
    if args.action=='diagnostico':return
    if not (3,12)<=sys.version_info[:2]<=(3,14):raise SystemExit('Usa Python 3.12, 3.13 o 3.14; no se modifica el Python del sistema.')
    if (ROOT/'.venv').exists():raise SystemExit('.venv ya existe: no se sobrescribe. Usa diagnostico con su Python o crea una copia limpia.')
    profile=args.perfil
    if profile=='auto':profile='cuda' if report['gpu']['code']==0 else 'cpu'
    if profile=='cuda' and report['gpu']['code']!=0:raise SystemExit('CUDA requiere NVIDIA/driver detectables. No se instala CPU como sustituto de la demo CUDA.')
    print('Perfil:',profile,'; descarga estimada: CPU 1-2 GB / CUDA 3-6 GB; duración orientativa 5-20 min según red. Sin modelos, índices ni vuelos.',flush=True)
    logdir=ROOT/'outputs/instalacion';logdir.mkdir(parents=True,exist_ok=True);start=time.perf_counter();venv.create(ROOT/'.venv',with_pip=True);py=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    def run(cmd):
        with (logdir/'pip.log').open('a',encoding='utf8') as f:
            f.write('\nCOMMAND '+repr(cmd)+'\n');f.flush();subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
    run([str(py),'-m','pip','install','--upgrade','pip'])
    index='https://download.pytorch.org/whl/'+('cu130' if profile=='cuda' else 'cpu')
    run([str(py),'-m','pip','install','torch==2.14.1','torchvision==0.29.1','--index-url',index])
    run([str(py),'-m','pip','install','-r',str(ROOT/'requirements/runtime.txt')]);run([str(py),'-m','pip','check'])
    run([str(py),str(__file__),'diagnostico','--imports','--json',str(logdir/'verificacion.json')])
    check=json.loads((logdir/'verificacion.json').read_text(encoding='utf8'));failed=[k for k,v in check['imports'].items() if not v['ok']]
    if failed:raise SystemExit('Instalación incompleta: '+', '.join(failed)+'; ver outputs/instalacion/pip.log')
    if profile=='cuda' and not check['imports']['torch'].get('cuda'):raise SystemExit('CUDA no operativa: revisa driver y compatibilidad. La demo no se considera válida.')
    (logdir/'fase.json').write_text(json.dumps(dict(seconds=time.perf_counter()-start,profile=profile)));print('Dependencias verificadas; todavía hay que aportar TIFF, índices y pesos. No se ha ejecutado ningún vuelo.')
if __name__=='__main__':main()
