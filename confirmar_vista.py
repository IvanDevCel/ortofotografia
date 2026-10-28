"""Explicit confirmation after inspecting this run's actual Gazebo screenshot."""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--avion-visible',action='store_true',required=True);args=p.parse_args();m=json.loads((ROOT/'informes/ultima_prueba.json').read_text(encoding='utf8'));out=ROOT/'informes'/m['name'];image=out/'capturas/gazebo_antes_armar.png'
    if not image.is_file():raise SystemExit('Todavia no existe la captura de esta ejecucion; no se confirma.')
    (out/'gazebo_verificado.json').write_text(json.dumps(dict(run_name=m['name'],plane_visible_on_ortho=True,evidence='capturas/gazebo_antes_armar.png',confirmed_by_operator=True)),encoding='utf8');print('Vista confirmada para',m['name'])
if __name__=='__main__':main()
