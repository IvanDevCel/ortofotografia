#!/usr/bin/env bash
set -euo pipefail
base="$HOME/uav-sitl"
if [[ "${1:-}" != "--instalar" ]]; then
  printf 'Diagnóstico (sin instalar):\n'; uname -a
  command -v git || true; command -v gz || true; command -v cmake || true
  test -x "$base/PX4-Autopilot/build/px4_sitl_default/bin/px4" && echo 'PX4 ya compilado' || true
  echo 'Para instalar en Ubuntu 24.04: bash tools/instalar_sitl.sh --instalar'
  exit 0
fi
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Este instalador SITL está limitado a Ubuntu 24.04'; exit 1; }
if [[ -x "$base/PX4-Autopilot/build/px4_sitl_default/bin/px4" ]]; then
  echo 'PX4 existente: no se reinstala ni recompila. Revisar recursos con equipo.py y desplegar_sitl.py antes de usar otra escena.'
  exit 0
fi
echo 'Instalación inicial oficial: puede superar 10 minutos (20–60 min orientativos), varios GB. No ejecuta vuelos.'
mkdir -p "$base/logs"
exec > >(tee -a "$base/logs/instalacion_portable.log") 2>&1
date -Is
sudo apt-get update
sudo apt-get install -y git python3-venv
if [[ ! -d "$base/PX4-Autopilot/.git" ]]; then
  git clone --depth 1 --branch v1.17.0 https://github.com/PX4/PX4-Autopilot.git "$base/PX4-Autopilot"
fi
git -C "$base/PX4-Autopilot" describe --tags --exact-match | grep -Fx v1.17.0
sudo bash "$base/PX4-Autopilot/Tools/setup/ubuntu.sh" --no-nuttx
sudo apt-get install -y python3-venv python3-pil python3-numpy imagemagick x11-apps mesa-utils
python3 -m venv --system-site-packages "$base/venv"
"$base/venv/bin/python" -m pip install pymavlink==2.4.50 pyulog==1.3.0 pillow
git -C "$base/PX4-Autopilot" submodule update --init --recursive --depth 1 Tools/simulation/gz
root="$(cd "$(dirname "$0")/.." && pwd)"
"$base/venv/bin/python" "$root/tools/desplegar_sitl.py" --preparar
(cd "$base/PX4-Autopilot" && make px4_sitl_default -j4)
date -Is
echo 'Instalación terminada; comprobar doctor y smoke. No se ha armado ni volado.'
