# Localización de un avión mediante ortofotografía

Proyecto didáctico: GeoTIFF → búsqueda DINOv2 → SuperPoint/LightGlue/RANSAC → posición visual → fusión en PX4 SITL. Avión RC Cessna y Gazebo Harmonic. Solo simulación; no preparado para controlar una aeronave real.

La última prueba A→B→C→A completó el recorrido: 150 imágenes, 132 aceptadas (88 %), error medio 0,691 m y máximo 4,860 m. Hubo interrupciones de visión; no supera la validación estricta de fusión continua. Se usó la propia ortofoto como escena y mapa: no es validación con imágenes independientes. Los resultados pequeños están en `examples/resultados/`.

## Qué contiene este repositorio

- `inspeccionar.py`, `ver_ventana.py`: metadatos y ventanas pequeñas, sin cargar todo el TIFF.
- `piloto_agl/`: geometría AGL, lectura por ventanas, índices y localizador.
- `demo_sitl/`: navegador visual, trabajador CUDA, controlador PX4, evaluación y visor existente.
- `config/`: configuración portable sin depender de informes anteriores.
- `sitl_assets/`: mundo y modelos personalizados actuales, con las capas fotográficas a 1/2/3 mm y suelo físico en z=0. Las texturas se aportan aparte.
- `tools/`: diagnóstico, instalación, copia de recursos y creación de una ejecución nueva.

No contiene TIFF, pesos, índices, vídeos, entornos Python, PX4 compilado ni dependencias privadas de Codex. No requiere Node para generar Excel: `tools/exportar_excel.py` utiliza openpyxl.

## Otro equipo: diagnosticar antes de instalar

Se necesita Python 3.12–3.14. El perfil CUDA se probó en Windows con RTX 5060 Laptop; SITL vive en Ubuntu 24.04 (WSL2 con WSLg o Ubuntu con escritorio). No se ha probado físicamente esta copia en otro ordenador.

```text
python tools/equipo.py diagnostico --json diagnostico_equipo.json
python tools/equipo.py instalar --perfil auto
```

El segundo comando crea una `.venv` nueva y nunca sobrescribe una existente. Instala las dependencias registradas y comprueba imports y `pip check`. CUDA utiliza ruedas cu130 oficiales; la compatibilidad del driver/GPU se comprueba al terminar y NO se acepta una caída silenciosa a CPU para la demo. Para una GPU o driver incompatible, detenerse y elegir el perfil PyTorch adecuado; el script no instala ni modifica drivers. CPU permite estudiar los TIFF y el piloto, pero no valida la demo CUDA.

Duración orientativa de dependencias: 5–20 minutos según red y equipo. El instalador escribe registros y no descarga modelos, indexa ni inicia vuelos. No es necesario ejecutarlo en el portátil original, que conserva sus entornos funcionales.

En Windows, usar después `.venv\Scripts\python.exe`; en Linux, `.venv/bin/python`.

## Recursos externos: reutilizar, no volver a indexar

Conserva la copia de seguridad del proyecto original. Desde este repositorio nuevo:

```text
python tools/copiar_recursos.py --origen "D:/copia_del_proyecto"
python tools/copiar_recursos.py --origen "D:/copia_del_proyecto" --copiar
```

La primera orden solo informa. La segunda copia TIFF, caché de modelos, índices existentes y tres texturas; no sobreescribe archivos existentes, no descarga ni calcula índices. Debe hacerse en el equipo de destino o con acceso a esa copia. También se pueden copiar manualmente según `config/recursos.json`.

`python tools/equipo.py diagnostico --imports` distingue dependencias instaladas de recursos ausentes. Un clon de GitHub sin datos externos NO puede localizar ni volar sobre la ortofoto.

Si no se dispone de los pesos, la descarga explícita es `python piloto_agl/piloto.py modelos`. Copiar antes `config/dinov2_revision.json` a `.modelos_agl/dinov2_revision.json` para mantener la revisión fijada. Preparar índices es una operación separada y costosa; no se ejecuta automáticamente.

## Instalar o reutilizar PX4/Gazebo

En Ubuntu 24.04, desde la carpeta clonada:

```bash
bash tools/instalar_sitl.sh
bash tools/instalar_sitl.sh --instalar
```

La primera orden solo diagnostica. La segunda usa PX4 oficial v1.17.0 y su instalador Ubuntu, prepara `~/uav-sitl`, aplica el cambio emparejado del magnetómetro y compila. Puede tardar 20–60 minutos y ocupar varios GB. No instala WSL ni drivers desde Windows; WSL2/WSLg debe estar preparado previamente. Requiere sudo para paquetes del sistema. Los registros quedan en `~/uav-sitl/logs`.

Los recursos deben estar copiados antes de desplegar la escena. Un conflicto con una escena existente distinta detiene el despliegue, en lugar de sobrescribirla. El cambio magnético no se presenta como validación aislada del EKF.

## Preparar y ejecutar la demo

No hay vuelos automáticos al instalar. Con dependencias y recursos comprobados:

```text
python demo_sitl/preparar_demo.py --ruta abca
python demo_sitl/worker_nav_cuda.py --smoke --output-dir outputs/smoke
```

`ab` prepara 45 s; `abca`, 150 s. Se crea una carpeta nueva en `informes/`, sin leer informes históricos. El calentamiento no aporta una posición inicial al navegador.

Para el vuelo, abrir el trabajador en Windows con su entorno CUDA:

```text
.venv\Scripts\python.exe demo_sitl/worker_nav_cuda.py
```

En Ubuntu/WSL, usando la ruta REAL de tu clon (no copiar una ruta de otro usuario):

```bash
~/uav-sitl/venv/bin/python demo_sitl/lanzar_continuidad_wsl.py "$PWD"
```

El controlador espera al trabajador y a la grabación. Inspecciona `informes/<ejecucion>/capturas/gazebo_antes_armar.png`; solo si se ve el avión sobre la ortofoto, confirma desde el clon:

```text
python tools/confirmar_vista.py --avion-visible
```

La barrera tiene un plazo de 60 s; si caduca, NO despega. El visor existente es http://localhost:18081/ durante la ejecución. No es una web pública. GNSS se corta a los 5 s; una imagen por segundo; las coordenadas reales se reservan a evaluación. Al final se pausa, sin aterrizar. Para cerrar, en Ubuntu: `~/uav-sitl/venv/bin/python ~/uav-sitl/scripts/detener_demo.py`.

## Evaluación y Excel

Después del vuelo, en WSL ejecutar `~/uav-sitl/venv/bin/python demo_sitl/extraer_ulog_nav.py`. Después, con el entorno del proyecto, `python demo_sitl/analizar_nav_cuda.py`. Para A-B-C-A: `python demo_sitl/evaluar_ruta_abca.py`. Para Excel: `python tools/exportar_excel.py informes/<ejecucion>`.

El error transversal del analizador respecto a A-B no mide seguimiento del triángulo entero. Para la ruta completa usar las visitas en orden de `recorrido_verificado.json`.

## Dependencias y fuentes

`requirements/` separa lectura básica, runtime visual y herramientas nativas. Las versiones registradas son una referencia del equipo de desarrollo, no una garantía para toda combinación de hardware. `DEPENDENCIAS.md` distingue lo comprobado localmente y lo que debe validar el nuevo equipo.

Fuentes: [PX4 WSL2](https://docs.px4.io/v1.17/en/dev_setup/dev_env_windows_wsl), [instalación PyTorch](https://pytorch.org/get-started/locally/), [DINOv2](https://github.com/facebookresearch/dinov2), [LightGlue](https://github.com/cvg/LightGlue). Los componentes y datos externos conservan sus respectivas licencias; no se redistribuyen sus pesos o TIFF en este repositorio.
