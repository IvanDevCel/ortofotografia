"""Instalación reanudable de Windows, modelos y WSL; no inicia vuelos."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'outputs' / 'instalacion'
PY = ROOT / '.venv' / 'Scripts' / 'python.exe'


def run(args, log, cwd=ROOT):
    print('Ejecutando:', ' '.join(map(str, args)), flush=True)
    with (OUT / log).open('a', encoding='utf8') as stream:
        stream.write('\n' + time.strftime('%Y-%m-%d %H:%M:%S') + ' ' + repr(args) + '\n')
        stream.flush()
        environment = dict(os.environ, PYTHONIOENCODING='utf-8')
        process = subprocess.Popen(list(map(str, args)), cwd=cwd, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in process.stdout:
            stream.write(line.decode('utf8', errors='replace').replace('\r\n', '\n'))
            stream.flush()
        code = process.wait()
        if code:
            raise subprocess.CalledProcessError(code, args)


def windows():
    if not PY.exists():
        run([sys.executable, ROOT / 'tools/equipo.py', 'instalar', '--perfil', 'cuda'], 'windows.log')
    else:
        # Resume a partially installed venv; never overwrite or recreate it.
        run([PY, '-m', 'pip', 'install', 'torch==2.14.1', 'torchvision==0.29.1',
             '--index-url', 'https://download.pytorch.org/whl/cu130'], 'windows.log')
        run([PY, '-m', 'pip', 'install', '-r', ROOT / 'requirements/runtime.txt'], 'windows.log')
        run([PY, '-m', 'pip', 'check'], 'windows.log')
    run([PY, ROOT / 'tools/equipo.py', 'diagnostico', '--imports', '--json',
         OUT / 'verificacion.json'], 'windows.log')
    report = json.loads((OUT / 'verificacion.json').read_text(encoding='utf8'))
    if any(not value['ok'] for value in report['imports'].values()):
        raise RuntimeError('Imports incompletos; revisar windows.log')
    if not report['imports']['torch'].get('cuda'):
        raise RuntimeError('CUDA no está operativa; no se sustituye por CPU')
    run([PY, '-c', 'import torch; x=torch.randn(512,512,device="cuda"); '
         'y=x@x; torch.cuda.synchronize(); assert torch.isfinite(y).all(); '
         'print(torch.__version__, torch.cuda.get_device_name(0), y.device)'], 'windows.log')


def models():
    dest = ROOT / '.modelos_agl' / 'dinov2_revision.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    pinned = (ROOT / 'config/dinov2_revision.json').read_bytes()
    if dest.exists() and json.loads(dest.read_bytes()) != json.loads(pinned):
        raise RuntimeError('La revisión DINOv2 existente es distinta; no se sobrescribe')
    if not dest.exists():
        dest.write_bytes(pinned)
    run([PY, ROOT / 'piloto_agl/piloto.py', 'modelos'], 'modelos.log')
    run([PY, ROOT / 'tools/verificar_cuda.py'], 'modelos.log')


def sitl():
    script = '/mnt/' + ROOT.drive[0].lower() + ROOT.as_posix()[2:] + '/tools/automatizar_sitl.sh'
    home = subprocess.check_output(['wsl', '-d', 'Ubuntu', '--', 'printenv', 'HOME'],
                                   encoding='utf8').strip()
    base = home + '/uav-sitl'
    for phase in ['fuentes', 'paquetes', 'compilar', 'verificar']:
        stamp = OUT / ('sitl_' + phase + '.ok')
        if stamp.exists() and phase != 'verificar':
            continue
        args = ['wsl', '-d', 'Ubuntu']
        if phase == 'paquetes':
            args += ['-u', 'root']
        run(args + ['--', 'bash', script, phase, base], 'sitl_' + phase + '.log')
        stamp.write_text(time.strftime('%Y-%m-%d %H:%M:%S'), encoding='utf8')


def resources(source=None):
    # Only import from the supplied backup; merge missing files without overwrites.
    if source:
        import shutil
        mapping = json.loads((ROOT / 'config/recursos.json').read_text(encoding='utf8'))
        pairs = [(p, p) for p in mapping['original_required']]
        pairs += list(mapping['texture_mappings'].items())
        source = Path(source).resolve()
        if source == ROOT:
            raise ValueError('El origen no puede ser el destino')
        for old, new in pairs:
            src, dst = source / old, ROOT / new
            files = src.rglob('*') if src.is_dir() else [src]
            for file in files:
                if not file.is_file() or '__pycache__' in file.parts or file.suffix == '.pyc':
                    continue
                target = dst / file.relative_to(src) if src.is_dir() else dst
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, target)
    mapping = json.loads((ROOT / 'config/recursos.json').read_text(encoding='utf8'))
    expected = ['PNOA_MA_OF_ETRS89_HU29_h25_0001_2.tif',
                'PNOA_MA_OF_ETRS89_HU29_h25_0002_4.tif']
    expected += [f'outputs/piloto_agl/indices/T2_h{h:03d}.{ext}'
                 for h in [50, 100, 200, 300, 400] for ext in ['json', 'npz']]
    expected += list(mapping['texture_mappings'].values())
    expected += ['examples/camara_006.jpg', 'assets/mapa_T2.jpg']
    missing = [p for p in expected if not (ROOT / p).is_file()]
    (OUT / 'recursos_pendientes.json').write_text(json.dumps(missing, indent=2), encoding='utf8')
    if missing:
        print('Recursos externos pendientes:', len(missing), flush=True)
    return missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fase', choices=['todo', 'windows', 'modelos', 'sitl', 'recursos'], default='todo')
    parser.add_argument('--origen', help='Carpeta de la copia de seguridad con los TIFF e índices')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    state_file = OUT / 'estado_automatico.json'
    state = json.loads(state_file.read_text(encoding='utf8')) if state_file.exists() else {}
    phases = [('windows', windows), ('modelos', models), ('sitl', sitl)]
    errors = []
    for name, action in phases:
        if args.fase not in ['todo', name]:
            continue
        current = json.loads(state_file.read_text(encoding='utf8')) if state_file.exists() else {}
        current[name] = {'ok': False, 'en_curso': True}
        state_file.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding='utf8')
        try:
            action()
            state[name] = {'ok': True, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S')}
        except Exception as error:
            state[name] = {'ok': False, 'error': str(error)}
            errors.append(name)
            print(name + ': ' + str(error), flush=True)
        current = json.loads(state_file.read_text(encoding='utf8')) if state_file.exists() else {}
        current[name] = state[name]
        state_file.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding='utf8')
        state = current
    missing = resources(args.origen)
    maps = ROOT.parent / 'archivosTiff'
    available = []
    if maps.is_dir() and PY.exists():
        try:
            run([PY, ROOT / 'tools/verificar_mapas.py', maps], 'mapas.log')
            available = json.loads((OUT / 'mapas_disponibles.json').read_text(encoding='utf8'))
        except subprocess.CalledProcessError:
            print('Verificación de mapas pendiente; ver mapas.log', flush=True)
    status = ['# Estado de instalación', '']
    status += [f'- {name}: ' + ('en curso' if value.get('en_curso') else
                              'verificado' if value.get('ok') else value.get('error', 'pendiente'))
               for name, value in state.items()]
    verification = OUT / 'verificacion.json'
    if verification.exists() and state.get('windows', {}).get('ok'):
        imports = json.loads(verification.read_text(encoding='utf8'))['imports']
        status += ['', '## Software instalado', '',
                   '- Python 3.12 y entorno aislado `para_github/.venv`.',
                   '- PyTorch ' + imports['torch']['version'] + ' y torchvision ' +
                   imports['torchvision']['version'] + '; CUDA operativa en ' + imports['torch']['gpu'] + '.',
                   '- Rasterio, OpenCV, NumPy, Pillow, Matplotlib, LightGlue, openpyxl y dependencias: imports y pip check correctos.']
    if state.get('modelos', {}).get('ok'):
        status += ['- Pesos DINOv2 (revisión fijada), SuperPoint y LightGlue descargados.',
                   '- Inferencia de los tres modelos en GPU: `para_github/outputs/instalacion/modelos_cuda.json`.']
    if state.get('sitl', {}).get('ok'):
        status += ['- Ubuntu 24.04 en WSL2, PX4 v1.17.0 compilado y Gazebo Harmonic.',
                   '- Entorno nativo: `~/uav-sitl/venv`; compilación y fuentes: `~/uav-sitl/PX4-Autopilot` (usuario de Ubuntu).',
                   '- WSLg: el lanzador configura D3D12/NVIDIA; comprobación en `para_github/outputs/instalacion/sitl_verificar.log`.']
    if available:
        status += ['', '## Mapas aportados y verificados', '']
        status += ['- `' + Path(row['file']).name + '` — ' + row['crs'] + ', SHA256 verificado.'
                   for row in available]
        status += ['', 'Los mapas de Valencia necesitan índices, escena y georreferencia propios.',
                   'No sustituyen los mapas EPSG:25829 de la demo histórica.']
    prepared=[]
    for folder in sorted((ROOT/'outputs/escenarios').glob('*')):
        cfgpath=folder/'piloto.json'
        if not cfgpath.is_file():continue
        cfg=json.loads(cfgpath.read_text(encoding='utf8'));region=cfg['regions'][0]['id']
        expected=[folder/'indices'/f'{region}_h{h:03d}.{ext}' for h in cfg['camera']['heights_m'] for ext in ['json','npz']]
        if all(p.is_file() for p in expected) and (folder/'assets/worlds/ortofoto.sdf').is_file():prepared.append(folder.name)
    if prepared:
        status += ['', '## Escenarios de Valencia preparados', '']
        status += ['- `'+name+'`: cinco índices de altura CUDA, textura, escena y georreferencia propias.' for name in prepared]
        status += ['', 'Los resultados de vuelo están en `para_github/informes/`; el visor activo es http://localhost:18081/.',
                   'Sagunto tiene un plan único de siete puntos: `outputs/escenarios/04_mar_costa_sagunto/planes/siete_puntos.json`.']
    status += ['', '## Recursos pendientes de la demo original', ''] + ['- `' + p + '`' for p in missing]
    status += ['', 'Estos recursos solo son necesarios para reproducir la escena antigua. No se necesitan para los escenarios de Valencia ya preparados.']
    status += ['', 'Reanudar desde la raíz: `powershell -ExecutionPolicy Bypass -File .\\INSTALAR.ps1`.',
               'Importar copia: añadir `--fase recursos --origen "D:\\copia_del_proyecto"`.',
               'La instalación no inicia vuelos. Los comandos de preparación y simulación están en el README.']
    (ROOT.parent / 'ESTADO_INSTALACION.md').write_text('\n'.join(status) + '\n', encoding='utf8')
    raise SystemExit(1 if errors else 0)


if __name__ == '__main__':
    main()
