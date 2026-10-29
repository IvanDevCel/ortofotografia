import json,subprocess,time
from pathlib import Path
reg=json.loads((Path.home()/'uav-sitl/demo_actual.json').read_text())
model='rc_cessna_0' if reg['etapa']=='basico' else 'rc_cessna_ortho_0'
for svc,req in [('/gui/move_to','data: "'+model+'"'),('/gui/follow','data: "'+model+'"')]:
    subprocess.run(['gz','service','-s',svc,'--reqtype','gz.msgs.StringMsg','--reptype','gz.msgs.Boolean','--timeout','2000','--req',req],check=True)
time.sleep(.7)
