"""Resumen y visor HTML local de resultados ya medidos."""
import html
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from camara import camera_parameters
from comun import OUT, save_csv, save_json


def percentile(values,p):
    return float(np.percentile(values,p)) if values else None


def fmt(value,digits=2):
    return '—' if value is None else f'{value:.{digits}f}'


def summarize(records):
    groups=defaultdict(list)
    for r in records:
        groups[(r['agl_m'],r['method'])].append(r)
    rows=[]
    for (height,method),group in sorted(groups.items()):
        pos=[r for r in group if r['positive']]
        neg=[r for r in group if not r['positive']]
        errors=[r['error_m'] for r in pos if r['error_m'] is not None]
        times=[r['total_query_ms'] for r in group]
        rows.append({'agl_m':height,'method':method,'positive_queries':len(pos),
                     'retrieved_top10':sum(r['retrieval_ok_top10'] for r in pos),
                     'retrieved_footprint80_top10':sum(r['retrieval_footprint80_top10'] for r in pos),
                     'retrieval_failures':sum(r['retrieval_failure'] for r in pos),
                     'verification_failures_given_retrieval':sum(r['verification_failure_given_retrieval'] for r in pos),
                     'localized_within_5m':sum(r['localized_within_5m'] for r in pos),
                     'rejected_positives':sum(r['false_rejection'] for r in pos),
                     'wrong_accepted_positives':sum(r['wrong_acceptance_positive'] for r in pos),
                     'median_error_accepted_m':percentile(errors,50),'p95_error_accepted_m':percentile(errors,95),
                     'max_error_accepted_m':max(errors) if errors else None,
                     'negative_queries':len(neg),'false_acceptances_negative':sum(r['false_acceptance'] for r in neg),
                     'median_query_ms':percentile(times,50),'p95_query_ms':percentile(times,95),
                     'max_rss_mib':max(r['rss_peak_mib'] for r in group)})
    return rows


def contact_sheets(cfg):
    for reg in cfg['regions']:
        zones=[z for z in cfg['zones'] if z['region']==reg['id']]
        sheet=Image.new('RGB',(640,5*270),'white')
        draw=ImageDraw.Draw(sheet)
        for i,height in enumerate(cfg['camera']['heights_m']):
            for j,zone in enumerate(zones):
                ident=f"{zone['id']}_h{height:03d}_original"
                with Image.open(OUT/'entradas'/f'{ident}.png') as im:
                    sheet.paste(im.resize((320,240)),(j*320,i*270))
                draw.text((j*320+4,i*270+244),f"{zone['id']} - {height} m AGL",fill='black')
        sheet.save(OUT/f"alturas_{reg['id']}.jpg",quality=92)


def plots(summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    heights=sorted({r['agl_m'] for r in summary})
    fig,axs=plt.subplots(1,3,figsize=(14,4.3))
    for method,label,color in [('lightglue','DINO + SuperPoint + LightGlue','#126DAD'),('sift','DINO + SIFT','#C57319')]:
        group=[next(r for r in summary if r['agl_m']==h and r['method']==method) for h in heights]
        axs[0].plot(heights,[100*r['localized_within_5m']/r['positive_queries'] for r in group],'o-',label=label,color=color)
        axs[1].plot(heights,[r['median_query_ms']/1000 for r in group],'o-',label=label,color=color)
        axs[2].plot(heights,[r['max_error_accepted_m'] if r['max_error_accepted_m'] is not None else np.nan for r in group],'o-',label=label,color=color)
    dino=[next(r for r in summary if r['agl_m']==h) for h in heights]
    axs[0].plot(heights,[100*r['retrieved_top10']/r['positive_queries'] for r in dino],'k--',label='Recuperación DINO top 10')
    for ax,title,ylabel in zip(axs,['Localización dentro de 5 m','Tiempo por consulta','Mayor error entre aceptadas'],['Positivos (%)','Mediana (s)','Error (m)']):
        ax.set_title(title)
        ax.set_xlabel('Altura AGL (m)')
        ax.set_ylabel(ylabel)
        ax.grid(alpha=.25)
    axs[0].set_ylim(0,105)
    handles,labels=axs[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc='lower center',ncol=3,fontsize=8)
    fig.tight_layout(rect=(0,.1,1,1))
    fig.savefig(OUT/'resumen_alturas.png',dpi=150)
    plt.close(fig)


def report(cfg):
    records=json.loads((OUT/'resultados.json').read_text(encoding='utf8'))
    prep=json.loads((OUT/'preparacion.json').read_text(encoding='utf8'))
    machine=json.loads((OUT/'equipo.json').read_text(encoding='utf8'))
    loading=json.loads((OUT/'carga_localizador.json').read_text(encoding='utf8'))
    memory_file=OUT/'memoria_evaluacion.json'
    os_memory=json.loads(memory_file.read_text(encoding='utf8')) if memory_file.exists() else {}
    duration=json.loads((OUT/'duracion_consultas.json').read_text(encoding='utf8'))
    peak_windows=duration.get('peak_process_working_set_mib',os_memory.get('peak_windows_working_set_mib'))
    summary=summarize(records)
    save_csv(OUT/'resumen_alturas.csv',summary)
    save_json(OUT/'resumen_alturas.json',summary)
    terrain=[]
    for name in sorted({r['terrain'] for r in records if r['positive']}):
        for method in ['lightglue','sift']:
            rows=[r for r in records if r['terrain']==name and r['positive'] and r['method']==method]
            terrain.append({'terrain':name,'method':method,'queries':len(rows),
                            'retrieved_top10':sum(r['retrieval_ok_top10'] for r in rows),
                            'localized_within_5m':sum(r['localized_within_5m'] for r in rows),
                            'rejected':sum(r['false_rejection'] for r in rows),
                            'wrong_accepted':sum(r['wrong_acceptance_positive'] for r in rows)})
    save_csv(OUT/'resumen_terreno.csv',terrain)
    contact_sheets(cfg)
    plots(summary)
    camera=camera_parameters(cfg['camera'])
    text=['# Piloto de localización con altura AGL','',
          '**Pruebas sintéticas de funcionamiento con la propia ortofoto. No validación con imágenes independientes.**','',
          f"Equipo: {machine['cpu']}; {machine['ram_gib']:.1f} GiB RAM; CPU, {machine['torch_threads']} hilos. CUDA no usada.",
          f"Cámara ideal cenital {camera['width']} × {camera['height']} px; FOV horizontal {camera['hfov_deg']:.2f}°, vertical {camera['vfov_deg']:.2f}°; fx=fy={camera['fx_px']:.3f} px.",
          'Terreno horizontal, sin distorsión, relieve, oclusiones ni inclinación de cámara. A 50 m se interpola el TIFF de 15 cm; no se crea detalle nuevo.','',
          '## Huella física','',
          'Ancho = 2 × AGL × tan(FOV horizontal / 2). Alto = ancho × 480 / 640. GSD = ancho / 640.',
          'Cambiar altura cambia el área muestreada del TIFF, antes de producir la entrada de cámara.','',
          '| AGL (m) | Ancho × alto (m) | Superficie (m²) | GSD (m/px) |',
          '|---:|---:|---:|---:|']
    for fp in camera['heights']:
        text.append(f"| {fp['agl_m']} | {fp['width_m']:.2f} × {fp['height_m']:.2f} | {fp['area_m2']:.0f} | {fp['gsd_m_px']:.4f} |")
    text+=['','## Resultados por altura','',
           'Cada método evalúa 20 positivos y 4 negativos por altura. Ambos comparten las mismas candidatas DINO: la referencia SIFT compara verificadores, no una búsqueda global SIFT independiente.',
           'Recuperación del centro: alguna candidata contiene el centro real. Además se mide la condición más estricta de cubrir al menos el 80% de la huella. Ambas se comprueban después de guardar predicciones; nunca se entregan al localizador. Una geometría parcial puede localizar bien aunque no cumpla el 80%.',
           'Error calculado sobre posiciones aceptadas. Se muestran rechazos y aceptaciones erróneas para evitar que las medianas oculten fallos.','',
           '| AGL | Método | Top10 centro / huella80 | Dentro de 5 m | Rechazos positivos | Aceptadas erróneas | Error mediano / máximo (m) | Consulta mediana (s) |',
           '|---:|---|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        text.append(f"| {r['agl_m']} | {r['method']} | {r['retrieved_top10']}/{r['positive_queries']} / {r['retrieved_footprint80_top10']}/{r['positive_queries']} | {r['localized_within_5m']}/{r['positive_queries']} | {r['rejected_positives']} | {r['wrong_accepted_positives']} | {fmt(r['median_error_accepted_m'],3)} / {fmt(r['max_error_accepted_m'],3)} | {r['median_query_ms']/1000:.3f} |")
    text+=['','![Resultados por altura](resumen_alturas.png)','','## Separación de fallos y rechazo','',
           '| AGL | Método | Fallos recuperación | Fallos verificación tras recuperar | Falsas aceptaciones negativas |',
           '|---:|---|---:|---:|---:|']
    for r in summary:
        text.append(f"| {r['agl_m']} | {r['method']} | {r['retrieval_failures']} | {r['verification_failures_given_retrieval']} | {r['false_acceptances_negative']}/{r['negative_queries']} |")
    text+=['','## Terrenos repetitivos','',
           '| Terreno | Método | Positivos | Top10 | Dentro de 5 m | Rechazos | Aceptadas erróneas |',
           '|---|---|---:|---:|---:|---:|---:|']
    for r in terrain:
        text.append(f"| {r['terrain']} | {r['method']} | {r['queries']} | {r['retrieved_top10']} | {r['localized_within_5m']} | {r['rejected']} | {r['wrong_accepted']} |")
    total_prep=sum(p['seconds'] for p in prep)
    full_seconds=sum(p['full_tiff_seconds_linear_estimate'] for p in prep)
    full_tiles=sum(p['full_tiff_tiles_estimate'] for p in prep)
    text+=['','## Preparación, memoria y ampliación de cobertura','',
           f"Se han indexado dos regiones de 1,44 km²: {sum(p['tiles'] for p in prep)} teselas en {total_prep:.2f} s, sin incluir descarga ni carga inicial del modelo.",
           f"Pico RSS de indexación: {max(p['rss_peak_mib'] for p in prep):.1f} MiB. Cargar y calentar ambos modelos e índices para consultas: {loading['seconds']:.2f} s.",
           f"Pico RSS muestreado en etapas de verificación: {max(r['rss_peak_mib'] for r in records):.1f} MiB. Es memoria del proceso con ambos verificadores residentes; no memoria exclusiva de un método. Muestreo cada 20 ms.",
           f"Pico de working set del proceso principal informado por Windows: {fmt(peak_windows,1)} MiB. El contador del sistema conserva el máximo del proceso, incluidas búsqueda y carga. En esta ejecución se recogió también mediante un monitor externo.",
           f"Extrapolación lineal a los rectángulos completos de ambos TIFF y las cinco escalas: {full_tiles:,} teselas, aproximadamente {full_seconds/60:.1f} minutos de indexación DINO. Es una estimación, no una ejecución medida sobre los TIFF completos.",
           'La extrapolación depende de caché, compresión, contenido y disco; incluye zonas negras/mar porque no se ha construido una máscara de cobertura útil. La RAM no tiene que crecer con el raster completo si se mantienen lotes y ventanas.',
           'Para ampliar: añadir regiones y medir tiempo por 1 km², persistir descriptores, procesar por lotes, construir máscara útil y cargar por región. La mayor parte del coste de esta rejilla proviene de la escala de 50 m. Si crece mucho, usar búsqueda gruesa previa con descriptor y refinar subregiones; esa etapa necesitaría su propia métrica de recuperación.',
           'La extracción local del mapa se hace bajo demanda y está incluida en el tiempo de consulta cuando falta en caché. Cada método mantiene una caché LRU de 96 teselas; se guardan fallos de caché por intento.','',
           '| AGL | Teselas en dos regiones | Preparación (s) | Pico RSS (MiB) | Extrapolación dos TIFF (min) |',
           '|---:|---:|---:|---:|---:|']
    for height in cfg['camera']['heights_m']:
        group=[p for p in prep if p['agl_m']==height]
        text.append(f"| {height} | {sum(p['tiles'] for p in group)} | {sum(p['seconds'] for p in group):.2f} | {max(p['rss_peak_mib'] for p in group):.1f} | {sum(p['full_tiff_seconds_linear_estimate'] for p in group)/60:.1f} |")
    text+=['',
           '## Medición repetida','']
    benchmark_file=OUT/'benchmark_resultados.json'
    if benchmark_file.exists():
        benchmark=json.loads(benchmark_file.read_text(encoding='utf8'))
        save_csv(OUT/'benchmark_resumen.csv',summarize(benchmark))
        text+=['Diez consultas representativas (una por región y altura), cinco repeticiones de cada una. Los tiempos individuales están en `benchmark_resultados.csv`; hay caché y calentamiento explícitos.',
               '| Método | Mediana (s) | P95 (s) |', '|---|---:|---:|']
        for method in ['lightglue','sift']:
            vals=[r['total_query_ms']/1000 for r in benchmark if r['method']==method]
            text.append(f'| {method} | {np.median(vals):.3f} | {np.percentile(vals,95):.3f} |')
    else:
        text.append('No se ha ejecutado el bloque adicional de repeticiones. La prueba principal guarda una medición por consulta y método.')
    text+=['','## Límites y problemas que hay que mantener visibles','',
           '- Hay cuatro posiciones de terreno, repetidas a cinco alturas y con cinco apariencias; las imágenes no son observaciones independientes.',
           '- Uniforme y ruido son controles sintéticos sin terreno real: su huella y GSD son los nominales de cámara a la altura ensayada, no una georreferencia de esas imágenes.',
           '- Los umbrales geométricos están prefijados en config.json. Este piloto no los calibra ni demuestra una tasa de rechazo segura.',
           '- La confianza es una puntuación heurística de inliers y cobertura; no es una probabilidad calibrada.',
           '- Las teselas a 400 m son grandes: sólo hay 15 por región y el top10 es una fracción alta del índice. El aumento de recuperación con altura puede deberse también a esta facilidad del conjunto.',
           '- La altura es AGL sobre un plano local. Para relieve real se necesita un modelo de elevación, pose y trazado de rayos; una ortofoto RGB por sí sola no proporciona esas alturas.',
           '- SuperPoint se ejecuta con lado mayor 448 y hasta 384 puntos, devolviendo coordenadas a la imagen 640×480. SIFT usa 640×480 y hasta 1024 puntos. Se documentan estos ajustes al comparar coste.',
           '- Una comprobación inicial a 640 px y 512 puntos mostró unos 8 s por consulta LightGlue en dos imágenes de mar. Se redujo el tamaño de trabajo antes de congelar la configuración de la evaluación principal.',
           '- Los originales conservan texturas exactas de la ortofoto. Sus errores muy pequeños no equivalen a precisión en un vuelo real ni a exactitud del GeoTIFF.',
           '- No se ha incorporado Gazebo.','',
           '## Archivos y ejecución','',
           'El código está en `piloto_agl/`. `camara.py` calcula huella; `datos.py` genera capturas y separa verdad de consultas; `indice.py` prepara DINO; `localizador.py` busca y verifica sin leer verdad; `evaluar.py` mide y después compara; `informe.py` resume.',
           'Desde la raíz del proyecto, con el entorno ya instalado:',
           '```powershell',
           r'.\.venv\Scripts\python.exe piloto_agl/piloto.py generar',
           r'.\.venv\Scripts\python.exe piloto_agl/piloto.py indexar',
           r'.\.venv\Scripts\python.exe piloto_agl/piloto.py evaluar',
           r'.\.venv\Scripts\python.exe piloto_agl/piloto.py evaluar --benchmark --repeticiones 5',
           r'.\.venv\Scripts\python.exe piloto_agl/piloto.py informe',
           '```',
           'Para comprobar rápidamente el flujo: `evaluar --limite 2`. Se guarda con prefijo `comprobacion_` y no sustituye los resultados completos.',
           'Los comandos sustituyen sus resultados previos. Cambiar configuración exige regenerar datos e índices antes de evaluar. Para otra ejecución, conserva primero la carpeta de resultados.',
           'Los pesos ya están en `.modelos_agl/`. En otro equipo, instalar `piloto_agl/requirements.txt` y ejecutar primero el comando `modelos` con acceso a Internet.',
           'En resultados.csv hay una fila por imagen, método y repetición, con altura, huella, GSD, verdad, estimación, error, confianza, tiempos, memoria y rutas de imágenes. Las 10 candidatas y todos sus diagnósticos geométricos están en predicciones.jsonl.',
           'Fuentes: [DINOv2 oficial](https://github.com/facebookresearch/dinov2), [LightGlue oficial](https://github.com/cvg/LightGlue), [homografía y RANSAC en OpenCV](https://docs.opencv.org/4.x/d1/de0/tutorial_py_feature_homography.html).']
    (OUT/'INFORME.md').write_text('\n'.join(text),encoding='utf8')
    write_html(records,summary,camera,prep)
    print('Informe, visor HTML local, figuras y resúmenes CSV creados.',flush=True)


def write_html(records,summary,camera,prep):
    esc=html.escape
    table=''.join(f"<tr><td>{r['agl_m']}</td><td>{r['method']}</td><td>{r['retrieved_top10']}/{r['positive_queries']}</td><td>{r['retrieved_footprint80_top10']}/{r['positive_queries']}</td><td>{r['localized_within_5m']}/{r['positive_queries']}</td><td>{r['rejected_positives']}</td><td>{fmt(r['median_error_accepted_m'],3)} / {fmt(r['max_error_accepted_m'],3)}</td><td>{r['median_query_ms']/1000:.2f}</td></tr>" for r in summary)
    rows=[]
    for r in records:
        status='Aceptada' if r['accepted'] else 'Rechazada'
        if r['wrong_acceptance_positive'] or r['false_acceptance']:
            status='Aceptación errónea'
        cells=[f"<a href='{esc(r['input_image'])}'><img loading='lazy' src='{esc(r['input_image'])}' width='128' height='96'></a>",
               esc(r['id']),r['agl_m'],r['method'],esc(r['terrain']),status,
               'Sí' if r['retrieval_ok_top10'] else ('No' if r['positive'] else 'No aplica'),fmt(r['error_m'],3),
               f"{r['total_query_ms']/1000:.2f}",f"{r['x_real']:.3f}, {r['y_real']:.3f}" if r['x_real'] is not None else 'Sin posición',
               f"{r['x_est']:.3f}, {r['y_est']:.3f}" if r['x_est'] is not None else 'No sé dónde estoy',
               f"<a href='{esc(r['found_map_image'])}'>Ver candidata y geometría</a>",esc(r['reason'])]
        rows.append(f"<tr data-height='{r['agl_m']}' data-method='{r['method']}' data-status='{esc(status)}'>"+''.join(f'<td>{c}</td>' for c in cells)+'</tr>')
    body=f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Piloto UAV: altura AGL</title><style>
body{{font:15px/1.5 Segoe UI,Arial,sans-serif;margin:0;background:#f2f5f7;color:#203344}}main{{max-width:1500px;margin:auto;padding:32px}}h1{{font-size:32px}}section{{background:white;padding:24px;margin:20px 0;border-radius:10px}}.notice{{background:#fff2cc;padding:16px;border-left:4px solid #bd8b00}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%;font-size:13px}}th{{text-align:left;background:#243c50;color:white;white-space:nowrap}}td,th{{padding:10px;border-bottom:1px solid #dce3e8}}tbody tr:nth-child(even){{background:#f5f8fa}}select{{padding:8px;margin:8px}}a{{color:#126dad}}.chart{{width:100%;max-width:1400px}}.cards{{display:flex;gap:24px;flex-wrap:wrap}}.cards span{{padding:12px;background:#edf3f8;border-radius:6px}}.catalog{{max-width:45%;vertical-align:top}}td img{{object-fit:contain}}header p{{max-width:900px}}
</style><main><header><h1>Localización UAV hasta 400 m AGL</h1>
<p class="notice">Pruebas sintéticas con recortes de la propia ortofoto. Estos resultados no validan todavía capturas de un UAV real.</p>
<p>Cámara cenital de 640 × 480 px, FOV horizontal 70° y vertical {camera['vfov_deg']:.2f}°. La altura modifica la superficie de terreno muestreada y los metros por píxel.</p>
<div class="cards"><span>100 entradas positivas</span><span>20 controles de rechazo</span><span>5 alturas</span><span>2 regiones de 1,44 km²</span><span>Índice DINO: {sum(r['seconds'] for r in prep):.1f} s</span></div>
<p><a href="INFORME.md">Informe completo y comandos</a> · <a href="resultados.csv">Todos los resultados CSV</a> · <a href="alturas.csv">Huella y GSD</a> · <a href="preparacion.csv">Preparación y memoria</a></p></header>
<section><h2>Resultados por altura</h2><p>Ambos métodos comparten las diez candidatas DINO. Se distingue recuperar el centro de cubrir al menos el 80% de la huella. Una coincidencia parcial puede bastar para localizar. El error muestra mediana y máximo entre posiciones aceptadas; los rechazos se cuentan aparte.</p><div class="scroll"><table><thead><tr><th>AGL (m)</th><th>Verificador</th><th>Top10 centro</th><th>Top10 huella ≥80%</th><th>Dentro de 5 m</th><th>Positivos rechazados</th><th>Error mediano / máximo (m)</th><th>Consulta mediana (s)</th></tr></thead><tbody>{table}</tbody></table></div><img class="chart" src="resumen_alturas.png"></section>
<section><h2>Cómo cambia la vista con la altura</h2><p>Las columnas conservan el centro observado; las filas recorren 50, 100, 200, 300 y 400 m.</p><img class="catalog" src="alturas_T1.jpg"><img class="catalog" src="alturas_T2.jpg"></section>
<section><h2>Revisión por intento</h2><p>La coordenada real sólo se utiliza al evaluar. «Ver candidata» muestra también los casos rechazados: una candidata rechazada no es una posición aceptada.</p>
<label>Altura <select id="height"><option value="">Todas</option>{''.join(f'<option>{h}</option>' for h in camera['heights_m'])}</select></label>
<label>Método <select id="method"><option value="">Ambos</option><option>lightglue</option><option>sift</option></select></label>
<label>Estado <select id="status"><option value="">Todos</option><option>Aceptada</option><option>Rechazada</option><option>Aceptación errónea</option></select></label>
<div class="scroll"><table><thead><tr><th>Entrada</th><th>ID</th><th>AGL</th><th>Método</th><th>Terreno</th><th>Respuesta</th><th>Top10 correcto</th><th>Error (m)</th><th>Tiempo (s)</th><th>UTM real</th><th>UTM estimada</th><th>Diagnóstico</th><th>Motivo</th></tr></thead><tbody id="attempts">{''.join(rows)}</tbody></table></div></section></main>
<script>const fields=['height','method','status'];function filter(){{document.querySelectorAll('#attempts tr').forEach(r=>{{r.hidden=fields.some(f=>document.getElementById(f).value&&r.dataset[f]!==document.getElementById(f).value)}})}}fields.forEach(f=>document.getElementById(f).addEventListener('change',filter));</script></html>'''
    (OUT/'informe.html').write_text(body,encoding='utf8')
