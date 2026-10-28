"""Lee una ventana RGB pequeña de un GeoTIFF y muestra sus coordenadas."""

import argparse
import os
from pathlib import Path

import rasterio
from rasterio.enums import ColorInterp
from rasterio.warp import transform
from rasterio.windows import Window, bounds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archivo", type=Path, help="GeoTIFF RGB que se abrirá en modo lectura")
    parser.add_argument("--fila", type=int, help="Fila inicial, desde 0; por defecto, ventana centrada")
    parser.add_argument("--columna", type=int, help="Columna inicial, desde 0; por defecto, ventana centrada")
    parser.add_argument("--tamano", type=int, default=512, help="Lado en píxeles: 1 a 1024 (defecto: 512)")
    parser.add_argument("--salida", type=Path, default=Path("salida/ventana.png"))
    parser.add_argument("--sin-mostrar", action="store_true", help="Guardar PNG sin abrir la ventana gráfica")
    args = parser.parse_args()
    if not 1 <= args.tamano <= 1024:
        parser.error("--tamano debe estar entre 1 y 1024 para mantener pequeña la lectura")

    try:
        with rasterio.open(args.archivo, "r") as src:
            if not src.crs:
                parser.error("El TIFF no tiene un sistema de coordenadas definido")
            if src.transform.b != 0 or src.transform.d != 0 or src.transform.a <= 0 or src.transform.e >= 0:
                parser.error("Este ejemplo requiere una ortofoto orientada al norte, sin giro")
            colores = list(src.colorinterp)
            if not all(color in colores for color in (ColorInterp.red, ColorInterp.green, ColorInterp.blue)):
                parser.error("Este ejemplo requiere bandas identificadas como rojo, verde y azul")
            bandas = [colores.index(color) + 1 for color in (ColorInterp.red, ColorInterp.green, ColorInterp.blue)]
            if any(src.dtypes[i - 1] != "uint8" for i in bandas):
                parser.error("Este ejemplo requiere RGB de 8 bits (uint8)")

            n = args.tamano
            fila = args.fila if args.fila is not None else (src.height - n) // 2
            columna = args.columna if args.columna is not None else (src.width - n) // 2
            if fila < 0 or columna < 0 or fila + n > src.height or columna + n > src.width:
                parser.error(f"La ventana debe caber dentro de {src.width} columnas x {src.height} filas")

            ventana = Window(columna, fila, n, n)
            # Única lectura de píxeles: nunca se llama a src.read() sin window.
            rgb = src.read(indexes=bandas, window=ventana)
            oeste, sur, este, norte = bounds(ventana, src.transform)
            fila_pixel, columna_pixel = fila + n // 2, columna + n // 2
            x, y = src.xy(fila_pixel, columna_pixel, offset="center")
            longitudes, latitudes = transform(src.crs, "EPSG:4326", [x], [y])
            crs = src.crs.to_string()
            unidad = src.crs.linear_units if src.crs.is_projected else "grados"

        print(f"Archivo: {args.archivo.name}")
        print(f"Ventana: fila={fila}, columna={columna}, tamaño={n} x {n} píxeles")
        print(f"Matriz leída: {rgb.shape} (bandas, filas, columnas); {rgb.nbytes / 1024**2:.2f} MiB")
        if rgb.min() == rgb.max():
            print("La ventana tiene un único valor: prueba otra fila y columna para ver detalle.")
        print(f"Límites exteriores ({crs}): oeste={oeste:.3f}, sur={sur:.3f}, este={este:.3f}, norte={norte:.3f}")
        print(f"Terreno cubierto: {este-oeste:.3f} x {norte-sur:.3f} {unidad}")
        print(f"Píxel marcado: fila={fila_pixel}, columna={columna_pixel}")
        print(f"Centro de ese píxel: X={x:.3f}, Y={y:.3f} ({crs})")
        print(f"WGS84 aproximado: longitud={longitudes[0]:.8f}, latitud={latitudes[0]:.8f} grados")

        # La caché de Matplotlib queda dentro del proyecto.
        os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".mplconfig"))
        import matplotlib
        if args.sin_mostrar:
            matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(9, 9))
        # imshow espera (filas, columnas, canales), no (bandas, filas, columnas).
        ax.imshow(rgb.transpose(1, 2, 0), extent=(oeste, este, sur, norte), origin="upper")
        ax.plot(x, y, "+", color="red", markersize=14, markeredgewidth=2)
        ax.set_title(f"{args.archivo.name}\nVentana {n} × {n} px · {crs}")
        ax.set_xlabel(f"X / Este ({unidad})")
        ax.set_ylabel(f"Y / Norte ({unidad})")
        ax.ticklabel_format(style="plain", useOffset=False)
        ax.tick_params(axis="x", labelrotation=25)
        fig.text(0.5, 0.02,
                 f"Inicio: fila {fila}, columna {columna} (índices desde 0)\n"
                 f"Cruz: centro del píxel ({fila_pixel}, {columna_pixel}) · X={x:.3f}, Y={y:.3f}\n"
                 f"Longitud {longitudes[0]:.8f}°, latitud {latitudes[0]:.8f}° (WGS84 aprox.)",
                 ha="center", fontsize=9)
        fig.tight_layout(rect=(0, 0.10, 1, 1))
        args.salida.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(args.salida, dpi=150)
        print(f"Imagen guardada: {args.salida.resolve()}")
        if not args.sin_mostrar:
            plt.show()
        plt.close(fig)
    except (OSError, rasterio.errors.RasterioError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
