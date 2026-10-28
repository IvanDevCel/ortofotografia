# Resultados de las simulaciones

## Llíria: A → B → A

Se verificaron las visitas en orden a B y de vuelta a A. La distancia mínima a B fue 1,76 m y a A, 1,06 m. Se aceptaron 136 de 150 imágenes, con error visual medio de 0,47 m y máximo de 1,98 m. Los tres modelos se ejecutaron en la RTX 5080. Hubo interrupciones de visión: no supera la validación estricta de fusión continua.

- [Informe y registros](para_github/informes/demo_02_urbano_lliria_aba_20261029_001730_994824/)
- [Vídeo](para_github/informes/demo_02_urbano_lliria_aba_20261029_001730_994824/vuelo_visor.mp4)
- [Excel](para_github/informes/demo_02_urbano_lliria_aba_20261029_001730_994824/informe.xlsx)

## Sagunto: una simulación, siete puntos

La misión P1 → P2 → P3 → P4 → P5 → P6 → P7 no se completó. Se verificaron P2 y P3 en orden; la aproximación a P4 quedó a 26,49 m, fuera del radio de 20 m. Tras 86,56 s, PX4 declaró baja precisión de posición y entró en retorno. El supervisor pausó la prueba al abandonar el modo de misión, sin permitir una órbita libre.

Se procesaron 87 imágenes y se rechazaron las 87. En 56 no hubo ni cuatro correspondencias. La inferencia media fue de 269 ms y la máxima, de 566 ms: el problema observado fue la falta de referencias visuales, no un incumplimiento del presupuesto de cálculo. DINOv2, SuperPoint y LightGlue se ejecutaron en CUDA en la RTX 5080; no se rebajaron los umbrales de aceptación. GNSS se cortó a los 5,03 s. No se demostró navegación visual sobre el agua.

- [Ruta de siete puntos](para_github/outputs/escenarios/04_mar_costa_sagunto/ruta_siete_puntos.jpg)
- [Resultado detallado](para_github/informes/demo_04_mar_costa_sagunto_siete_puntos_20261029_002921_029285/resumen_sagunto.json)
- [Vídeo de 86,6 segundos](para_github/informes/demo_04_mar_costa_sagunto_siete_puntos_20261029_002921_029285/vuelo_visor.mp4)
- [Visor local](http://localhost:18081/)

La foto del agua es estática y se utiliza como escena y mapa; estos ensayos no validan navegación sobre un mar real y cambiante. Se conservaron también los registros de los arranques anteriores; el lote de vuelos separados se canceló al aclararse que se querían siete puntos en una única simulación.

## Estado y sensores

Los cuatro mapas tienen índices CUDA a 50, 100, 200, 300 y 400 m, texturas y escenas separadas en `para_github/outputs/escenarios/`. Solo se han volado Llíria y Sagunto. La IMU, el barómetro, el magnetómetro, GNSS y la cámara se mantienen en el SDF del avión. Se guardan sus frecuencias, ruido y montaje en `sensores.json` dentro de cada escenario. La verdad de Gazebo se usa para evaluar el recorrido y los errores, fuera del localizador.

Dos simulaciones simultáneas no se han validado: la GPU tiene margen de memoria en estas pruebas, pero los lanzadores comparten puertos, archivos de coordinación e instancia PX4 y necesitan aislamiento antes de ejecutarse en paralelo.
