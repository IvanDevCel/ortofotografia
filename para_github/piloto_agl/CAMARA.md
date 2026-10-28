# Cámara simulada y altura AGL

La cámara es un modelo pinhole ideal, apuntando al nadir, con imagen RGB de
640 × 480 píxeles, campo horizontal de 70°, píxeles cuadrados y distorsión nula.
No representa una cámara comercial concreta. La distancia focal equivalente
en píxeles es suficiente para definir la proyección; no hace falta suponer un
tamaño de sensor en milímetros.

La distancia focal es `fx = 640 / (2*tan(70°/2)) = 457,007362 px`, con `fy=fx`.
El punto principal está en `(320,240)` en coordenadas de bordes de píxel, o
`(319,5;239,5)` en coordenadas de centros. El FOV vertical se deriva de la
misma focal: `2*atan(480/(2*fy)) = 55,412927°`.

Para altura `h` sobre un plano horizontal:

```text
ancho visible = 2*h*tan(FOV_horizontal/2)
alto visible  = 2*h*tan(FOV_vertical/2)
superficie    = ancho*alto
GSD_x         = ancho/640
GSD_y         = alto/480
```

| AGL | Ancho × alto visible | Superficie aprox. | GSD |
| ---: | ---: | ---: | ---: |
| 50 m | 70,02 × 52,52 m | 3.677 m² | 0,1094 m/px |
| 100 m | 140,04 × 105,03 m | 14.709 m² | 0,2188 m/px |
| 200 m | 280,08 × 210,06 m | 58.835 m² | 0,4376 m/px |
| 300 m | 420,12 × 315,09 m | 132.378 m² | 0,6564 m/px |
| 400 m | 560,17 × 420,12 m | 235.339 m² | 0,8753 m/px |

El TIFF original tiene GSD de 0,15 m/píxel. Sin giro, la huella de cámara a
100 m abarca aproximadamente 934 × 700 píxeles del TIFF, y a 400 m abarca
3.734 × 2.801. Ambos se remuestrean a la misma salida 640 × 480. Así la altura
cambia los detalles visibles y su tamaño en la imagen, no sólo los metadatos.
A 50 m el TIFF se interpola: no contiene el detalle real de una captura nativa
de 10,94 cm/píxel.

Para girar se lee una ventana que contiene la diagonal de la huella, se
remuestrea a la resolución física de cámara y después se gira alrededor del
centro. La salida conserva el centro geométrico. Las esquinas reales y la
coordenada de ese centro se guardan en `verdad.json`, fuera de las consultas.
Cambios de brillo, sombra y desenfoque se aplican después de la proyección.

La altura AGL se considera conocida por telemetría y se entrega al localizador,
como también la región de búsqueda autorizada. No se entrega la posición real,
el giro aplicado, el tipo de terreno ni las posiciones del generador. Se usa el
índice correspondiente a esa altura. Este piloto no prueba error del altímetro
ni robustez a una altura desconocida; eso requerirá añadir perturbaciones de
telemetría y buscar también en escalas vecinas.

La huella se mide sobre un plano. Para montaña, cámara inclinada o altitud
distinta a lo largo de la imagen, hay que usar un modelo de elevación y trazar
los rayos de cámara hasta el terreno. Un GeoTIFF RGB no proporciona ese modelo.
La altitud máxima configurada es 400 m AGL; se rechazan alturas superiores.

`test_geometria.py` comprueba que multiplicar altura por ocho multiplica el
ancho y el GSD por ocho y la superficie por 64. También comprueba que la región
realmente muestreada cambia, que giros conservan el centro y que el localizador
rechaza recibir la configuración que contiene posiciones de generación.
