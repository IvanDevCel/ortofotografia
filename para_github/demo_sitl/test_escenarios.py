"""Regresiones de CRS, aislamiento de índices y calibración de sensores."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import numpy as np
from rasterio.warp import transform

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'piloto_agl'))
from indice import load_indices
from busqueda_orientaciones import body_from_ground


class EscenariosTests(unittest.TestCase):
    def test_conversion_usa_huso_del_mapa(self):
        for crs, e, n in [('EPSG:25830',706325.,4389232.),('EPSG:25829',609810.,4839670.)]:
            lo,la=transform(crs,'EPSG:4326',[e],[n])
            cal=dict(crs=crs,utm_to_enu_basis_per_metre=[[1.,0.],[0.,1.]])
            ob=dict(q_capture_wxyz=[1.,0.,0.,0.],agl_baro_m=100.,ref_lat=la[0],ref_lon=lo[0])
            result=dict(accepted=True,x_est=e,y_est=n+.05,confidence_score=1.,rectified_fraction=1.)
            body_from_ground(result,ob['q_capture_wxyz'],ob,cal)
            self.assertAlmostEqual(result['lon_visual'],lo[0],places=9)
            self.assertAlmostEqual(result['lat_visual'],la[0],places=9)
            np.testing.assert_allclose(result['ned'],[0.,0.],atol=1e-5)

    def test_indices_se_leen_del_escenario(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/'lliria_h100.json').write_text(json.dumps([{'id':'solo_lliria'}]))
            np.savez_compressed(folder/'lliria_h100.npz',descriptors=np.ones((1,384),np.float32))
            cfg=dict(index_directory=str(folder),regions=[dict(id='lliria')],camera=dict(heights_m=[100]))
            indices=load_indices(cfg)
            self.assertEqual(list(indices),[('lliria',100)])
            self.assertEqual(indices[('lliria',100)][0][0]['id'],'solo_lliria')

    def test_camara_y_sensores_del_avion(self):
        root=ET.parse(ROOT/'sitl_assets/models/rc_cessna_ortho/model.sdf').getroot()
        sensors={s.get('name'):s for s in root.iter('sensor')}
        self.assertEqual({s.get('type') for s in sensors.values()}, {'imu','navsat','air_pressure','magnetometer','camera'})
        camera=sensors['nadir']
        self.assertEqual(camera.findtext('camera/image/width'),'640')
        self.assertEqual(camera.findtext('camera/image/height'),'480')
        self.assertAlmostEqual(float(camera.findtext('camera/horizontal_fov')),np.deg2rad(70))
        pose=list(map(float,camera.findtext('pose').split()))
        np.testing.assert_allclose(pose[:3],[.05,0,-.15])
        self.assertEqual(float(sensors['imu_sensor'].findtext('update_rate')),250)
        self.assertGreater(len(list(sensors['imu_sensor'].iter('noise'))),0)


if __name__=='__main__':unittest.main()
