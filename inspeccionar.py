"""Consulta metadatos de GeoTIFF sin leer matrices de píxeles."""

import argparse
from pathlib import Path

import rasterio
from rasterio.warp import transform_bounds


def inspeccionar(ruta):
    with rasterio.open(ruta, "r") as src:
        b = src.bounds
        lineas = [
            f"Archivo: {ruta.name}",
            f"Tamaño en disco: {ruta.stat().st_size:,} bytes",
            f"Dimensiones: {src.width} columnas x {src.height} filas",
            f"Bandas: {src.count}",
        ]
        for i, (tipo, color) in enumerate(zip(src.dtypes, src.colorinterp), 1):
            lineas.append(f"  Banda {i}: {tipo}, interpretación={color.name}")
        lineas.extend([
            f"CRS: {src.crs}",
            f"Unidades: {src.crs.linear_units if src.crs else 'sin CRS'}",
            f"Resolución X, Y: {src.res}",
            f"Extensión: oeste={b.left}, sur={b.bottom}, este={b.right}, norte={b.top}",
            f"Tamaño del rectángulo en unidades del CRS: {b.right-b.left} x {b.top-b.bottom}",
            f"NoData por banda: {src.nodatavals}",
            f"Bloques (filas, columnas) por banda: {src.block_shapes}",
            f"Compresión: {src.compression.name if src.compression else 'ninguna'}",
            "Transformación (columna, fila) -> (X, Y):",
            str(src.transform),
        ])
        if src.crs:
            oeste, sur, este, norte = transform_bounds(src.crs, "EPSG:4326", *b)
            lineas.append(
                "Envolvente aproximada WGS84 (grados): "
                f"lon=[{oeste:.8f}, {este:.8f}], lat=[{sur:.8f}, {norte:.8f}]"
            )
        lineas.append("Solo metadatos; no se ha llamado a read().")
        return "\n".join(lineas)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archivos", type=Path, nargs="+", help="Uno o varios GeoTIFF")
    parser.add_argument("--salida", type=Path, help="Guardar también el informe en UTF-8")
    args = parser.parse_args()
    try:
        informe = "\n\n".join(inspeccionar(ruta) for ruta in args.archivos)
        if args.salida:
            args.salida.parent.mkdir(parents=True, exist_ok=True)
            args.salida.write_text(informe + "\n", encoding="utf-8")
        print(informe)
    except (OSError, rasterio.errors.RasterioError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
