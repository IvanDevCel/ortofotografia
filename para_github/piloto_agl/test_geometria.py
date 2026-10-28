"""Contratos físicos y separación de verdad; no descarga modelos."""
import unittest

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from camara import camera_parameters, footprint
from comun import config
from datos import capture
from evaluar import retrieval_coverage
from localizador import Localizer


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.camera=config()['camera']

    def test_physical_scaling(self):
        low=footprint(self.camera,50)
        high=footprint(self.camera,400)
        self.assertAlmostEqual(high['width_m']/low['width_m'],8)
        self.assertAlmostEqual(high['area_m2']/low['area_m2'],64)
        self.assertAlmostEqual(high['gsd_m_px']/low['gsd_m_px'],8)
        self.assertAlmostEqual(high['width_m'],560.1660305677677)

    def test_camera_square_pixels(self):
        params=camera_parameters(self.camera)
        self.assertAlmostEqual(params['fx_px'],params['fy_px'])
        self.assertAlmostEqual(params['vfov_deg'],55.412927352596554)

    def test_agl_limits(self):
        for height in [0,-1,400.001]:
            with self.assertRaises(ValueError):
                footprint(self.camera,height)

    def test_capture_actually_changes_sampled_surface(self):
        yy,xx=np.indices((1024,1024))
        data=np.stack([xx//4,yy//4,(xx+yy)//8]).astype(np.uint8)
        with MemoryFile() as memory:
            with memory.open(driver='GTiff',width=1024,height=1024,count=3,dtype='uint8',
                             crs='EPSG:25829',transform=from_origin(500000,4800000,1,1)) as src:
                src.write(data)
                low,lp,_=capture(src,512,512,50,0,self.camera)
                high,hp,_=capture(src,512,512,400,0,self.camera)
                self.assertEqual(low.shape,(480,640,3))
                self.assertEqual(high.shape,(480,640,3))
                self.assertGreater(int(high[240,-1,0])-int(high[240,0,0]),5*(int(low[240,-1,0])-int(low[240,0,0])))
                for angle in [0,25,-35,90]:
                    _,corners,fp=capture(src,512,512,400,angle,self.camera)
                    corners=np.asarray(corners)
                    np.testing.assert_allclose(corners.mean(axis=0),[512,512],atol=1e-8)
                    self.assertAlmostEqual(np.linalg.norm(corners[1]-corners[0]),fp['width_m'])
                    self.assertAlmostEqual(np.linalg.norm(corners[2]-corners[1]),fp['height_m'])

    def test_correct_retrieval_requires_center_and_coverage(self):
        t={'positive':True,'corners_px':[[10,10],[30,10],[30,30],[10,30]],'col_real':20,'row_real':20}
        tile={'col':0,'row':0,'width':40,'height':40}
        self.assertAlmostEqual(retrieval_coverage(t,tile),1)
        self.assertEqual(retrieval_coverage(t,{**tile,'col':25}),0)
        self.assertAlmostEqual(retrieval_coverage(t,{**tile,'width':20}),.5)

    def test_localizer_rejects_generation_coordinates(self):
        with self.assertRaisesRegex(ValueError,'verdad'):
            Localizer(config())


if __name__=='__main__':
    unittest.main()
