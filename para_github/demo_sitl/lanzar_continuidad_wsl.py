"""WSL launcher for the single authorized flight; never installs/indexes."""
from pathlib import Path
import sys,json,shutil,os,subprocess,time
if Path('/dev/dxg').exists():
    os.environ.setdefault('GALLIUM_DRIVER','d3d12')
    os.environ.setdefault('MESA_D3D12_DEFAULT_ADAPTER_NAME','NVIDIA')
ROOT=Path(sys.argv[1]);base=Path.home()/'uav-sitl';meta=json.loads((ROOT/'informes/ultima_prueba.json').read_text());cfg=json.loads((ROOT/'informes'/meta['name']/'configuracion.json').read_text())
reg=base/'demo_actual.json'
if reg.exists():
    old=json.loads(reg.read_text());p=Path(f"/proc/{old['pid']}/cmdline")
    if p.exists() and b'/uav-sitl/PX4-Autopilot/' in p.read_bytes():raise RuntimeError('Existing PX4 active; refusing second simulation')
    subprocess.run([str(base/'venv/bin/python'),str(base/'scripts/detener_demo.py')],check=True,timeout=6)
    time.sleep(1)
for name in ['nav_cuda_sitl.py','geometria_navegacion.py','coordinacion_demo.py']:shutil.copy2(ROOT/'demo_sitl'/name,base/'scripts'/name)
print('Starting ONE flight',cfg['run_name'],flush=True)
os.execv(str(base/'venv/bin/python'),[str(base/'venv/bin/python'),str(base/'scripts/nav_cuda_sitl.py'),cfg['report_linux']+'/configuracion.json'])
