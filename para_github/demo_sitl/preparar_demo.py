"""Create a fresh run from portable config, never from an old report."""
import argparse,json,os,datetime,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def windows_to_wsl(path):
    path=Path(path).resolve()
    if os.name!='nt':return str(path)
    return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix()[3:]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ruta',choices=['ab','abca'],default='abca');args=p.parse_args();cfg=json.loads((ROOT/'config/demo_base.json').read_text(encoding='utf8'));name='demo_'+args.ruta+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S');out=ROOT/'informes'/name
    for d in ['imagenes','capturas','diagnosticos','registros_px4','codigo']:(out/d).mkdir(parents=True,exist_ok=True)
    if args.ruta=='ab':cfg.update(mission_waypoints=[dict(cfg['B'],label='B')],flight_effective_s=45)
    cfg.update(run_name=name,report_windows=str(out),report_linux=windows_to_wsl(out),capture_offsets_s=list(range(cfg['flight_effective_s'])))
    (out/'configuracion.json').write_text(json.dumps(cfg,indent=2),encoding='utf8');shutil.copy2(ROOT/'examples/smoke_entrada.json',out/'smoke_entrada.json');shutil.copy2(ROOT/'config/terreno.json',out/'terreno_reparado.json');(ROOT/'informes/ultima_prueba.json').write_text(json.dumps(dict(name=name,report=str(out),config=str(out/'configuracion.json'),config_linux=cfg['report_linux']+'/configuracion.json'),indent=2),encoding='utf8');print(out)
if __name__=='__main__':main()
