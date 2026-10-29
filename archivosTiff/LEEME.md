# Cuatro escenarios de ortofotografia para simulacion

Fuente: Institut Cartografic Valencia (ICV), Generalitat Valenciana. Ortofoto verdadera de la provincia de Valencia de 2025.
Ficha oficial: https://dadesobertes.gva.es/es/dataset/ortofoto-de-2025-de-la-provincia-de-valencia-en-rgbi-y-de-15-cm-de-resolucion
La ficha publica licencia Creative Commons Attribution: conservar la atribucion y consultar sus condiciones antes de redistribuir.

## Contenido

- 01_montana_calderona.tif: entorno de Serra, vegetacion y paisaje de montana.
- 02_urbano_lliria.tif: nucleo urbano de Lliria y alrededores.
- 03_playa_el_saler.tif: entorno de El Saler, vegetacion, playa y costa.
- 04_mar_costa_sagunto.tif: entorno costero de Puerto de Sagunto, con agua y referencias del litoral. No es una cobertura de alta mar.
- vista_previa.jpg: vista de conjunto para elegir escenario.
- manifest.json: limites UTM, centros orientativos, solicitudes de origen, tamano y SHA-256 de cada TIFF.

## Como se han preparado

Son exportaciones RGB del WMS oficial, montadas en GeoTIFF; NO son las hojas TIFF RGBI originales. La fuente anuncia 0,15 m/pixel. Cada exportacion cubre 1.500 x 1.500 m, tiene 6.000 x 6.000 pixeles y una malla de salida de 0,25 m/pixel. El servicio puede remuestrear su imagen; la malla de salida no garantiza detalle nativo ni precision de navegacion.

Tres bandas RGB de 8 bits; sin infrarrojo ni altura. CRS EPSG:25830 (ETRS89 / UTM 30N). GeoTIFF con compresion JPEG de calidad 95, con perdida. Se descargaron bloques PNG sin perdida y se aplico JPEG al empaquetar los TIFF. Los limites y el transformado afin quedan grabados en cada archivo. No se incluye ni se ha generado un MDT, MDS ni relieve.

## Uso con el proyecto

1. Conservar el codigo, los indices y los informes actuales sin sobrescribirlos.
2. Leer el CRS de cada TIFF: estos mapas son EPSG:25830; no aplicar el EPSG:25829 de los mapas anteriores.
3. Elegir una ruta dentro de la imagen con margen para la huella completa de la camara y para los giros. No se han verificado rutas A/B ni se han creado indices o ejecutado vuelos.
4. Preparar un indice acotado separado por escenario cuando se autorice la prueba; estos mapas nuevos no corresponden a los indices antiguos.
5. En Gazebo, seguir usando un plano con textura. El aspecto montanoso de la fotografia no simula relieve 3D ni proporciona altitud del terreno.
6. La latitud/longitud debe salir del transformado del GeoTIFF y la geometria del localizador, nunca de las coordenadas de evaluacion.

## Limite del escenario marino

El agua sin costa ni referencias permanentes puede no permitir localizacion visual. Si mapa y camara muestran exactamente la misma fotografia estatica de olas o reflejos, las coincidencias pueden ser artificialmente faciles: no equivalen a navegar sobre agua real y cambiante. Usar este escenario para evaluar rechazos, propagacion limitada y recuperacion al volver a ver costa. No aceptar coincidencias debiles para fabricar continuidad.

## Comprobaciones incluidas

Se comprueba que cada GeoTIFF puede abrirse, tiene tres bandas, CRS y resolucion correctos y contenido no uniforme. Se incluye una vista previa para revisar visualmente la cobertura; no se ha validado la navegacion sobre estos mapas.
