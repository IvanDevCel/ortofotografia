"""Copia una escena a su carpeta propia y valida SDF; nunca inicia vuelos."""
from pathlib import Path
import shutil
import subprocess
import sys
import os

folder=Path(sys.argv[1]).resolve()
base=Path.home()/'uav-sitl'
dest=base/'escenarios'/folder.name/'assets'
shutil.copytree(folder/'assets',dest,dirs_exist_ok=True)
(base/'scripts').mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parent.parent
for name in ['encuadrar.py','detener_demo.py','geometria_navegacion.py','coordinacion_demo.py']:
    shutil.copy2(root/'demo_sitl'/name,base/'scripts'/name)
env=dict(os.environ,SDF_PATH=str(dest/'models')+':'+str(base/'PX4-Autopilot/Tools/simulation/gz/models'))
subprocess.run(['gz','sdf','-k',str(dest/'worlds/ortofoto.sdf')],check=True,env=env)
subprocess.run(['gz','sdf','-k',str(dest/'models/rc_cessna_ortho/model.sdf')],check=True,env=env)
print('Escena desplegada:',dest)
