r"""Ejecutar desde la raíz: .venv\Scripts\python.exe piloto_agl/piloto.py --help"""
import argparse

from comun import setup, OUT, save_json


def main():
    parser=argparse.ArgumentParser(description='Piloto de localización con altura AGL física, máximo 400 m')
    parser.add_argument('stage',choices=['modelos','generar','indexar','evaluar','revisar','informe','todo'])
    parser.add_argument('--limite',type=int,help='Limitar consultas para una comprobación rápida')
    parser.add_argument('--repeticiones',type=int,default=1,help='Repeticiones por consulta, conservadas individualmente')
    parser.add_argument('--benchmark',action='store_true',help='Diez consultas originales, una por región y altura')
    args=parser.parse_args()
    cfg=setup()
    if args.stage=='modelos':
        from modelos import prepare
        prepare()
    if args.stage in ['generar','todo']:
        from datos import generate
        generate(cfg)
    if args.stage in ['indexar','todo']:
        from indice import build
        build(cfg)
    if args.stage in ['evaluar','todo']:
        from evaluar import run
        run(cfg,args.limite,args.repeticiones,args.benchmark)
        if args.stage=='todo':
            run(cfg,repeats=5,benchmark=True)
    if args.stage=='revisar':
        import json
        from evaluar import annotate
        prefix='benchmark_' if args.benchmark else ('comprobacion_' if args.limite else '')
        predictions=[json.loads(line) for line in (OUT/f'{prefix}predicciones.jsonl').read_text(encoding='utf8').splitlines()]
        annotate(cfg,predictions,prefix)
        print('Evaluación reconstruida desde predicciones guardadas; no se han ejecutado modelos.')
    if args.stage in ['informe','todo']:
        from informe import report
        report(cfg)


if __name__=='__main__':
    main()
