#!/usr/bin/env bash
# Installation only. Never launches PX4, arms, or flies.
set -euo pipefail
phase="${1:?fase requerida: fuentes, paquetes, compilar, verificar}"
base="${2:-$HOME/uav-sitl}"
root="$(cd "$(dirname "$0")/.." && pwd)"
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Se requiere Ubuntu 24.04'; exit 1; }
case "$phase" in
fuentes)
  mkdir -p "$base/logs"
  if [[ ! -d "$base/PX4-Autopilot/.git" ]]; then
    git clone --depth 1 --branch v1.17.0 https://github.com/PX4/PX4-Autopilot.git "$base/PX4-Autopilot"
  fi
  git -C "$base/PX4-Autopilot" describe --tags --exact-match | grep -Fx v1.17.0
  ;;
paquetes)
  [[ "$EUID" == 0 ]] || { echo 'Esta fase requiere root'; exit 1; }
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get -o DPkg::Lock::Timeout=600 install -y git python3-venv
  bash "$base/PX4-Autopilot/Tools/setup/ubuntu.sh" --no-nuttx
  apt-get install -y python3-venv python3-pil python3-numpy imagemagick x11-apps mesa-utils
  ;;
compilar)
  [[ "$EUID" != 0 ]] || { echo 'Compilar como usuario de Ubuntu'; exit 1; }
  [[ -x "$base/venv/bin/python" ]] || python3 -m venv --system-site-packages "$base/venv"
  "$base/venv/bin/python" -m pip install pymavlink==2.4.50 pyulog==1.3.0 pillow
  git -C "$base/PX4-Autopilot" submodule update --init --recursive --depth 1 Tools/simulation/gz
  # Apply the paired magnetic patch even when the map textures are absent.
  "$base/venv/bin/python" - "$root" "$base" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'tools'))
from desplegar_sitl import patch_px4
patch_px4(Path(sys.argv[2]))
PY
  (cd "$base/PX4-Autopilot" && make px4_sitl_default -j4)
  ;;
verificar)
  test -x "$base/PX4-Autopilot/build/px4_sitl_default/bin/px4"
  "$base/venv/bin/python" -c 'import pymavlink, pyulog, gz.transport13, gz.msgs10; print("Imports SITL correctos")'
  gz sim --versions
  if [[ -e /dev/dxg ]]; then
    export GALLIUM_DRIVER="${GALLIUM_DRIVER:-d3d12}"
    export MESA_D3D12_DEFAULT_ADAPTER_NAME="${MESA_D3D12_DEFAULT_ADAPTER_NAME:-NVIDIA}"
  fi
  glxinfo -B
  ;;
*) echo "Fase desconocida: $phase"; exit 2 ;;
esac
