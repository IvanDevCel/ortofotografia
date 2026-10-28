"""Cierra únicamente el grupo de procesos iniciado por esta demo."""
import json
import os
import signal
from pathlib import Path

record=Path.home()/'uav-sitl/demo_actual.json'
data=json.loads(record.read_text())
pid=data['pid']
cmdline=Path(f'/proc/{pid}/cmdline')
if cmdline.exists():
    command=cmdline.read_bytes().replace(b'\x00',b' ')
    if b'/uav-sitl/PX4-Autopilot/build/px4_sitl_default/bin/px4' not in command:
        raise RuntimeError('El PID ya no corresponde al PX4 de esta demo')
    os.killpg(pid,signal.SIGINT)
    print('Cierre solicitado al grupo PX4/Gazebo:',pid)
else:
    print('El PX4 de esta demo ya terminó')
gui_pid=data.get('gui_pid')
if gui_pid and Path(f'/proc/{gui_pid}/cmdline').exists():
    command=Path(f'/proc/{gui_pid}/cmdline').read_bytes()
    if b'gz' in command and b'sim' in command:
        os.killpg(gui_pid,signal.SIGINT)
        print('Cierre solicitado al cliente gráfico:',gui_pid)

server_pid=data.get('server_pid')
if server_pid and Path(f'/proc/{server_pid}/cmdline').exists():
    command=Path(f'/proc/{server_pid}/cmdline').read_bytes()
    if b'gz' in command and b'sim' in command:
        os.killpg(server_pid,signal.SIGINT)
        print('Cierre solicitado al servidor de esta demo:',server_pid)
