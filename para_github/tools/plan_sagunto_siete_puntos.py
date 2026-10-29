"""Una única misión de siete puntos sobre el agua, sin órbita final."""
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from rasterio.warp import transform

ROOT=Path(__file__).resolve().parent.parent
base=ROOT/'outputs/escenarios/04_mar_costa_sagunto'
cfg=json.loads((base/'demo_base.json').read_text(encoding='utf8'))
tr=cfg['source_transform'];reg=cfg['region'];geo=cfg['georeference']
U=np.array(geo['utm_to_enu_basis_per_metre']).T;origin=np.array(geo['utm_center'])
uv=[(.68,.18),(.85,.23),(.86,.44),(.72,.53),(.86,.65),(.73,.78),(.67,.69)]
def point(u,v):
    col,row=u*reg['width'],v*reg['height'];e,n=tr[0]*col+tr[2],tr[4]*row+tr[5]
    lo,la=transform(geo['crs'],'EPSG:4326',[e],[n])
    return dict(col=col,row=row,utm_e=e,utm_n=n,enu=(U@(np.array([e,n])-origin)).tolist(),lat=la[0],lon=lo[0])
points=[dict(point(*p),label=f'P{i}') for i,p in enumerate(uv,1)]
direction=np.array(points[1]['enu'])-points[0]['enu']
takeoff=point(uv[0][0]+.4*(uv[1][0]-uv[0][0]),uv[0][1]+.4*(uv[1][1]-uv[0][1]))
plan=dict(A=points[0],B=points[-1],start_label='P1',takeoff_target=takeoff,
          mission_waypoints=points[1:],initial_yaw_enu_rad=math.atan2(direction[1],direction[0]),
          flight_effective_s=180,stop_at_mission_end=True,plan_id='siete_puntos',
          route_note='P1 -> P2 -> P3 -> P4 -> P5 -> P6 -> P7; pausa al llegar a P7, sin órbita',
          planned_length_m=sum(float(np.linalg.norm(np.array(b['enu'])-a['enu'])) for a,b in zip(points,points[1:])))
path=base/'planes/siete_puntos.json';path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(plan,indent=2,ensure_ascii=False),encoding='utf8')
image=Image.open(base/'mapa.jpg').convert('RGB');d=ImageDraw.Draw(image)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
xy=[(u*image.width,v*image.height) for u,v in uv]
d.line(xy,fill='#ffde59',width=5)
for i,(x,y) in enumerate(xy,1):
    d.ellipse((x-8,y-8,x+8,y+8),fill='#ffde59',outline='black',width=2)
    d.text((x+12,y-16),f'P{i}',font=font,fill='white',stroke_width=2,stroke_fill='black')
image.save(base/'ruta_siete_puntos.jpg',quality=95)
print(path,plan['planned_length_m'])
