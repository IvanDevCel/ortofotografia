# Estado de instalación

- sitl: verificado
- windows: verificado
- modelos: verificado

## Software instalado

- Python 3.12 y entorno aislado `para_github/.venv`.
- PyTorch 2.14.1+cu130 y torchvision 0.29.1+cu130; CUDA operativa en NVIDIA GeForce RTX 5080.
- Rasterio, OpenCV, NumPy, Pillow, Matplotlib, LightGlue, openpyxl y dependencias: imports y pip check correctos.
- Pesos DINOv2 (revisión fijada), SuperPoint y LightGlue descargados.
- Inferencia de los tres modelos en GPU: `para_github/outputs/instalacion/modelos_cuda.json`.
- Ubuntu 24.04 en WSL2, PX4 v1.17.0 compilado y Gazebo Harmonic.
- Entorno nativo: `~/uav-sitl/venv`; compilación y fuentes: `~/uav-sitl/PX4-Autopilot` (usuario de Ubuntu).
- WSLg: el lanzador configura D3D12/NVIDIA; comprobación en `para_github/outputs/instalacion/sitl_verificar.log`.

## Mapas aportados y verificados

- `01_montana_calderona.tif` — EPSG:25830, SHA256 verificado.
- `02_urbano_lliria.tif` — EPSG:25830, SHA256 verificado.
- `03_playa_el_saler.tif` — EPSG:25830, SHA256 verificado.
- `04_mar_costa_sagunto.tif` — EPSG:25830, SHA256 verificado.

Los mapas de Valencia necesitan índices, escena y georreferencia propios.
No sustituyen los mapas EPSG:25829 de la demo histórica.

## Escenarios de Valencia preparados

- `01_montana_calderona`: cinco índices de altura CUDA, textura, escena y georreferencia propias.
- `02_urbano_lliria`: cinco índices de altura CUDA, textura, escena y georreferencia propias.
- `03_playa_el_saler`: cinco índices de altura CUDA, textura, escena y georreferencia propias.
- `04_mar_costa_sagunto`: cinco índices de altura CUDA, textura, escena y georreferencia propias.

Los resultados de vuelo están en `para_github/informes/`; el visor activo es http://localhost:18081/.
Sagunto tiene un plan único de siete puntos: `outputs/escenarios/04_mar_costa_sagunto/planes/siete_puntos.json`.

## Recursos pendientes de la demo original

- `PNOA_MA_OF_ETRS89_HU29_h25_0001_2.tif`
- `PNOA_MA_OF_ETRS89_HU29_h25_0002_4.tif`
- `outputs/piloto_agl/indices/T2_h050.json`
- `outputs/piloto_agl/indices/T2_h050.npz`
- `outputs/piloto_agl/indices/T2_h100.json`
- `outputs/piloto_agl/indices/T2_h100.npz`
- `outputs/piloto_agl/indices/T2_h200.json`
- `outputs/piloto_agl/indices/T2_h200.npz`
- `outputs/piloto_agl/indices/T2_h300.json`
- `outputs/piloto_agl/indices/T2_h300.npz`
- `outputs/piloto_agl/indices/T2_h400.json`
- `outputs/piloto_agl/indices/T2_h400.npz`
- `sitl_assets/models/ortho_terreno/materials/textures/ortofoto.png`
- `sitl_assets/models/poblacion_detalle/materials/textures/poblacion_detalle.png`
- `sitl_assets/models/indice_T2/materials/textures/textura_T2.png`

Estos recursos solo son necesarios para reproducir la escena antigua. No se necesitan para los escenarios de Valencia ya preparados.

Reanudar desde la raíz: `powershell -ExecutionPolicy Bypass -File .\INSTALAR.ps1`.
Importar copia: añadir `--fase recursos --origen "D:\copia_del_proyecto"`.
La instalación no inicia vuelos. Los comandos de preparación y simulación están en el README.
