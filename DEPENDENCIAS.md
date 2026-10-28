# Dependencias y limites de validacion

Windows: Python 3.14.5 en el equipo original; torch 2.14.1+cu130 y torchvision 0.29.1+cu130 en el entorno CUDA separado. NVIDIA RTX 5060 Laptop 8 GB. La distribucion usa una sola .venv nueva y elimina el desvio privado .cuda_runtime.

Ubuntu/WSL2: 24.04, PX4 v1.17.0, Gazebo Harmonic, Python 3.12, pymavlink y pyulog. Los modulos gz se instalan con los paquetes oficiales de Gazebo; la venv nativa usa --system-site-packages. Las fuentes y binarios nativos se guardan bajo ~/uav-sitl.

Python directo: numpy, rasterio, Pillow, matplotlib, OpenCV, psutil, torch, torchvision, einops, omegaconf y LightGlue. Excel nuevo: openpyxl. No hay dependencia de @oai/artifact-tool ni de una instalacion de Codex. El XLSX de ejemplo es un resultado ya generado.

Faltan en Git deliberadamente: ortofotos, indices, fuentes/pesos descargados de DINOv2/SuperPoint/LightGlue, texturas grandes, compilacion PX4 y registros completos. Se reutilizan de la copia local mediante copiar_recursos.py. Los modelos conservan su procedencia/licencia, incluida la revision DINOv2 fijada.

La preparacion no instala dependencias aqui ni lanza vuelos. Validacion local: ver VERIFICACION.json. Quedan por validar en el equipo de destino: disponibilidad de ruedas para su Python, driver CUDA, rendimiento, WSLg/OpenGL, instalacion/compilacion PX4 y un ensayo autorizado. La instalacion puede fallar con equipos o versiones diferentes; los scripts conservan el registro y no fuerzan CPU para la demo.

Los intentos historicos, videos, TIFF y entornos de trabajo originales siguen intactos fuera de esta distribucion. No borrar outputs/ ni informes/ del proyecto original: sus lanzadores antiguos aun los referencian.
