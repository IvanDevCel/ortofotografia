"""Genera recortes y verdad de referencia; no implementa ningún localizador."""

import argparse
import json
import math
import os
import platform
import shutil
from pathlib import Path
from time import perf_counter

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from rasterio.windows import Window


SEED = 20261028
N = 512
CONTEXT = 1024
CASES = ([('original', 0, 1, 1, 0, 0)] * 10 + [
    ('giro', 20, 1, 1, 0, 0), ('giro', -35, 1, 1, 0, 0),
    ('escala', 0, 0.8, 1, 0, 0), ('escala', 0, 1.25, 1, 0, 0),
    ('brillo', 0, 1, 0.65, 0, 0), ('brillo', 0, 1, 1.35, 0, 0),
    ('sombra', 0, 1, 1, 0.45, 0), ('sombra', 0, 1, 1, 0.65, 0),
    ('desenfoque', 0, 1, 1, 0, 1.4), ('combinado', 25, 0.85, 0.8, 0.5, 1),
])


def select_windows(src, rng):
    """Sondea pequeñas ventanas distribuidas; nunca lee la matriz completa."""
    candidates = []
    for row in np.linspace(0, src.height - CONTEXT, 20, dtype=int):
        for col in np.linspace(0, src.width - CONTEXT, 24, dtype=int):
            patch = src.read([1, 2, 3], window=Window(int(col)+448, int(row)+448, 128, 128))
            gray = patch.astype(np.float32).mean(axis=0)
            if np.mean(np.any(patch > 0, axis=0)) > 0.98 and gray.std() > 10:
                candidates.append((int(row), int(col), float(gray.std())))
    if len(candidates) < 10:
        raise RuntimeError(f'Solo hay {len(candidates)} candidatos con detalle en {src.name}')
    # Orden reproducible, distribuido por distancia, empezando por mayor contraste.
    chosen, remaining = [], candidates[:]
    first = max(remaining, key=lambda item: item[2])
    chosen.append(first)
    remaining.remove(first)
    while len(chosen) < min(80, len(candidates)):
        best = max(remaining, key=lambda p: min((p[0]-q[0])**2+(p[1]-q[1])**2 for q in chosen))
        chosen.append(best)
        remaining.remove(best)
    windows = []
    for row, col, _ in chosen:
        tic = perf_counter()
        array = src.read([1, 2, 3], window=Window(col, row, CONTEXT, CONTEXT))
        read_ms = (perf_counter() - tic) * 1000
        if np.mean(np.any(array > 0, axis=0)) >= 0.98:
            windows.append((row, col, array, read_ms))
        if len(windows) == 10:
            return windows, len(candidates)
    raise RuntimeError('No hay 10 contextos completos con suficiente imagen útil')


def affine(angle, zoom):
    theta = math.radians(angle)
    a, b = math.cos(theta)/zoom, math.sin(theta)/zoom
    d, e = -math.sin(theta)/zoom, math.cos(theta)/zoom
    # Coordenadas de bordes: el centro geométrico (256,256) se conserva en (512,512).
    return (a, b, CONTEXT/2-(a+b)*N/2, d, e, CONTEXT/2-(d+e)*N/2)


def point_record(src, label, row, col):
    x, y = src.xy(row, col, offset='center')
    edge_col, edge_row = ~src.transform * (x, y)
    back_row, back_col = edge_row - 0.5, edge_col - 0.5
    return dict(mapa=Path(src.name).name, punto=label, fila=row, columna=col,
                x=x, y=y, fila_vuelta=back_row, columna_vuelta=back_col,
                error_px=math.hypot(back_row-row, back_col-col),
                error_m=math.hypot((back_row-row)*src.res[1], (back_col-col)*src.res[0]))


def save_reference(context, coeffs, path, label):
    ref = context.copy()
    draw = ImageDraw.Draw(ref)
    a, b, c, d, e, f = coeffs
    polygon = [(a*u+b*v+c, d*u+e*v+f) for u, v in [(0,0),(N,0),(N,N),(0,N)]]
    draw.line(polygon+[polygon[0]], fill='yellow', width=5)
    draw.line((492,512,532,512), fill='red', width=5)
    draw.line((512,492,512,532), fill='red', width=5)
    draw.rectangle((0,0,1024,44), fill='black')
    draw.text((12,12), f'REFERENCIA REAL - {label} - no es una estimacion', fill='white')
    ref.resize((768,768), Image.Resampling.LANCZOS).save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida', type=Path, default=Path('outputs/ensayo_uav_20261028'))
    args = parser.parse_args()
    root = args.salida
    for folder in ('entradas', 'referencias', 'miniaturas'):
        (root/folder).mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    files = sorted(Path('.').glob('*.tif'))
    if len(files) != 2:
        parser.error('Se esperan los dos TIFF de este proyecto en la carpeta actual')
    rows, points, maps, scan_times = [], [], [], []
    for map_index, path in enumerate(files, 1):
        tic_scan = perf_counter()
        with rasterio.open(path, 'r') as src:
            if src.crs.to_epsg() != 25829 or src.count != 3 or src.dtypes != ('uint8',)*3:
                raise RuntimeError('Este ensayo espera los TIFF RGB uint8 EPSG:25829 inspeccionados')
            windows, candidate_count = select_windows(src, rng)
            scan_ms = (perf_counter()-tic_scan)*1000
            scan_times.append(dict(mapa=path.name, sondeo_y_seleccion_ms=scan_ms, candidatos=candidate_count))
            maps.append(dict(archivo=path.name, ancho=src.width, alto=src.height,
                             crs=src.crs.to_string(), resolucion=list(src.res), limites=list(src.bounds)))
            for name, r, c in [('superior_izquierda',0,0), ('superior_derecha',0,src.width-1),
                               ('inferior_izquierda',src.height-1,0), ('inferior_derecha',src.height-1,src.width-1),
                               ('central',src.height//2,src.width//2)]:
                points.append(point_record(src, name, r, c))
            for index, ((row, col, array, read_ms), case) in enumerate(zip(windows + windows, CASES), 1):
                start = perf_counter()
                kind, angle, zoom, brightness, shadow, blur = case
                image_id = f'T{map_index}_{index:02d}'
                context = Image.fromarray(array.transpose(1,2,0))
                coeffs = affine(angle, zoom)
                image = context.transform((N,N), Image.Transform.AFFINE, coeffs, Image.Resampling.BICUBIC)
                image = ImageEnhance.Brightness(image).enhance(brightness)
                if shadow:
                    mask = Image.new('L', (N,N), 0)
                    ImageDraw.Draw(mask).polygon([(0,64),(360,0),(512,360),(128,512)], fill=255)
                    mask = mask.filter(ImageFilter.GaussianBlur(18))
                    image = Image.composite(ImageEnhance.Brightness(image).enhance(shadow), image, mask)
                if blur:
                    image = image.filter(ImageFilter.GaussianBlur(blur))
                image.save(root/'entradas'/f'{image_id}.png')
                save_reference(context, coeffs, root/'referencias'/f'{image_id}.png', image_id)
                image.resize((80,80), Image.Resampling.LANCZOS).save(root/'miniaturas'/f'{image_id}.png')
                generation_ms = (perf_counter()-start)*1000
                p = point_record(src, image_id, row+CONTEXT/2-0.5, col+CONTEXT/2-0.5)
                points.append(p)
                rows.append(dict(id=image_id, mapa=path.name, prueba=kind, esperado='Localizar',
                    entrada=f'entradas/{image_id}.png', referencia=f'referencias/{image_id}.png',
                    x_real=p['x'], y_real=p['y'], x_estimada=None, y_estimada=None,
                    confianza=None, tiempo_localizacion_ms=None, aceptada=None,
                    estado='Pendiente de modelo', lugar_encontrado=None, motivo_rechazo=None,
                    familia=f'T{map_index}_Z{(index-1)%10+1:02d}', origen='Recorte sintético de la ortofoto', archivo_origen=path.name,
                    fila_contexto=row, columna_contexto=col, lado_contexto=CONTEXT, lado_entrada=N,
                    giro_grados=angle, escala_zoom=zoom, brillo_factor=brightness,
                    sombra_factor=shadow if shadow else 1, desenfoque_radio_px=blur,
                    lectura_ms=read_ms, generacion_ms=generation_ms,
                    matriz_salida_a_contexto=list(coeffs), semilla=SEED))
        print(f'{path.name}: 20 imágenes; {candidate_count} candidatos útiles; sondeo {scan_ms:.0f} ms', flush=True)

    # Dos negativos de otra zona: misma entrada positiva, pero contra el otro mapa.
    for index, (source, target) in enumerate([(rows[20], files[0]), (rows[0], files[1])],1):
        start = perf_counter()
        item = dict(source)
        image_id = f'R{index:02d}'
        shutil.copyfile(root/source['entrada'], root/'entradas'/f'{image_id}.png')
        shutil.copyfile(root/source['referencia'], root/'referencias'/f'{image_id}.png')
        shutil.copyfile(root/'miniaturas'/f"{source['id']}.png", root/'miniaturas'/f'{image_id}.png')
        item.update(id=image_id, mapa=target.name, prueba='otra_zona', esperado='Rechazar',
                    entrada=f'entradas/{image_id}.png', referencia=f'referencias/{image_id}.png',
                    lectura_ms=None, generacion_ms=(perf_counter()-start)*1000)
        rows.append(item)
    for index, target in enumerate(files,3):
        start = perf_counter()
        image_id = f'R{index:02d}'
        image = Image.new('RGB',(N,N),(128,128,128)) if index == 3 else Image.fromarray(rng.integers(0,256,(N,N,3),dtype=np.uint8))
        image.save(root/'entradas'/f'{image_id}.png')
        image.resize((80,80)).save(root/'miniaturas'/f'{image_id}.png')
        item = {key: None for key in rows[0]}
        item.update(id=image_id, mapa=target.name, prueba='uniforme' if index == 3 else 'ruido',
                    esperado='Rechazar', entrada=f'entradas/{image_id}.png',
                    estado='Pendiente de modelo', familia=image_id, origen='Sintética sin posición real',
                    lado_entrada=N, generacion_ms=(perf_counter()-start)*1000, semilla=SEED)
        rows.append(item)

    # Láminas para revisar las 20 entradas de cada TIFF sin abrirlas una a una.
    for map_index in (1,2):
        sheet = Image.new('RGB',(5*210,4*240),'white')
        draw = ImageDraw.Draw(sheet)
        for j, item in enumerate(rows[(map_index-1)*20:map_index*20]):
            x, y = (j%5)*210, (j//5)*240
            with Image.open(root/item['entrada']) as im:
                sheet.paste(im.resize((200,200)),(x,y))
            draw.text((x+4,y+205), f"{item['id']} {item['prueba']}", fill='black')
        sheet.save(root/f'catalogo_T{map_index}.png')
    metadata = dict(semilla=SEED, imagenes=rows, coordenadas=points, mapas=maps,
        seleccion=scan_times, equipo=dict(sistema=platform.platform(), cpu=os.environ.get('PROCESSOR_IDENTIFIER'),
        hilos=os.cpu_count(), gpu='No comprobada', python=platform.python_version()),
        nota_tiempos='lectura_ms y generacion_ms miden creación de datos, NO preparación del mapa ni localización')
    (root/'datos.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    assert len(rows) == 44 and len(points) == 50
    assert all(p['error_px'] < 1e-6 for p in points)
    print(f'44 entradas y 50 pruebas de coordenadas guardadas en {root}')


if __name__ == '__main__':
    main()
