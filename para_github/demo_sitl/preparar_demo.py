"""Create a fresh run from portable config, never from an old report."""
import argparse,json,os,datetime,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def windows_to_wsl(path):
    path=Path(path).resolve()
    if os.name!='nt':return str(path)
    return '/mnt/'+path.drive[0].lower()+'/'+path.as_posix()[3:]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ruta',choices=['ab','aba','abca'],default='abca');p.add_argument('--escenario');p.add_argument('--plan');args=p.parse_args()
    base=ROOT/'outputs/escenarios'/args.escenario if args.escenario else ROOT/'config'
    if args.escenario and (base.parent!=ROOT/'outputs/escenarios' or not (base/'demo_base.json').is_file()):p.error('Escenario no preparado')
    cfg=json.loads((base/'demo_base.json').read_text(encoding='utf8'))
    if args.plan:
        plan=base/'planes'/(args.plan+'.json')
        if plan.parent!=base/'planes':p.error('Plan no válido')
        cfg.update(json.loads(plan.read_text(encoding='utf8')))
    name='demo_'+(args.escenario+'_' if args.escenario else '')+(args.plan or args.ruta)+'_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');out=ROOT/'informes'/name
    for d in ['imagenes','capturas','diagnosticos','registros_px4','codigo']:(out/d).mkdir(parents=True,exist_ok=True)
    if args.ruta=='ab' and not args.plan:cfg.update(mission_waypoints=[dict(cfg['B'],label='B')],flight_effective_s=45)
    if args.ruta=='aba' and not args.plan:cfg.update(mission_waypoints=[dict(cfg['B'],label='B'),dict(cfg['A'],label='A (vuelta)')],flight_effective_s=150)
    cfg.update(run_name=name,report_windows=str(out),report_linux=windows_to_wsl(out),capture_offsets_s=list(range(cfg['flight_effective_s'])))
    (out/'configuracion.json').write_text(json.dumps(cfg,indent=2),encoding='utf8');shutil.copy2(base/'smoke_entrada.json' if args.escenario else ROOT/'examples/smoke_entrada.json',out/'smoke_entrada.json');shutil.copy2(base/'terreno.json',out/'terreno_reparado.json');(ROOT/'informes/ultima_prueba.json').write_text(json.dumps(dict(name=name,report=str(out),config=str(out/'configuracion.json'),config_linux=cfg['report_linux']+'/configuracion.json'),indent=2),encoding='utf8');print(out)
if __name__=='__main__':main()
