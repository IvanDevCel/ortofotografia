"""Comprueba mapas aportados; no cambia la configuración de la demo histórica."""
import hashlib
import json
from pathlib import Path
import argparse

import numpy as np
import rasterio
from rasterio.windows import Window

ROOT = Path(__file__).resolve().parent.parent


def inspect(folder):
    manifest_path = folder / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else []
    expected = {item['archivo']: item for item in manifest}
    rows = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in ['.tif', '.tiff']:
            continue
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        with rasterio.open(path) as src:
            assert src.crs is not None, f'Falta CRS: {path}'
            assert src.count >= 3, f'Faltan bandas RGB: {path}'
            sample = src.read([1, 2, 3], window=Window(src.width // 2 - 128,
                              src.height // 2 - 128, 256, 256))
            assert np.std(sample) > 0, f'Mapa uniforme: {path}'
            item = expected.get(path.name)
            if item:
                assert digest == item['sha256'], f'SHA256 diferente: {path}'
                assert src.crs.to_string() == item['crs'], f'CRS diferente: {path}'
                assert [src.width, src.height] == item['pixeles'], f'Dimensiones diferentes: {path}'
                assert np.allclose(src.bounds, item['bounds_utm']), f'Límites diferentes: {path}'
            rows.append(dict(file=str(path.resolve()), width=src.width, height=src.height,
                             crs=src.crs.to_string(), bounds=list(src.bounds),
                             resolution=list(src.res), sha256=digest,
                             manifest_verified=item is not None,
                             compatible_demo_original=src.crs.to_epsg() == 25829 and
                             path.name in ['PNOA_MA_OF_ETRS89_HU29_h25_0001_2.tif',
                                           'PNOA_MA_OF_ETRS89_HU29_h25_0002_4.tif']))
    if not rows:
        raise RuntimeError(f'No hay TIFF en {folder}')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--salida', type=Path, default=ROOT / 'outputs/instalacion/mapas_disponibles.json')
    args = parser.parse_args()
    rows = inspect(args.folder)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding='utf8')
    for row in rows:
        print(Path(row['file']).name, row['crs'], f"{row['width']}x{row['height']}",
              'SHA256 verificado' if row['manifest_verified'] else 'sin manifiesto')


if __name__ == '__main__':
    main()
