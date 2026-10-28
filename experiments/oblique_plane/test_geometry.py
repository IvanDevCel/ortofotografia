"""Analytic geometry tests, independent of learned matching and evaluation labels."""
import unittest
import json
from pathlib import Path
import numpy as np
import cv2
from geometry import chain,K_from,plane_rays,rotation,quaternion,matrix,ENU_FROM_NED,orthorectify,rpy_ned

CFG=json.loads((Path(__file__).parent/'config.json').read_text())

class GeometryTests(unittest.TestCase):
    def test_quaternion_round_trip(self):
        for rpy in [[0,0,0],[10,-20,150],[179,0,90],[-5,35,-90]]:
            R=rotation(*rpy);np.testing.assert_allclose(matrix(quaternion(R)),R,atol=1e-12)

    def test_known_vertical_and_tilted_rays(self):
        simple=dict(CFG,mount_origin_body_frd_m=[0,0,0],camera_offset_gimbal_frd_m=[0,0,0])
        for angle in [0,15,30,45]:
            R,lever=chain([0,0,0],[0,angle,0],simple)
            ground=plane_rays([[319.5,239.5]],K_from(CFG),R,50)[0]
            np.testing.assert_allclose(ground,[0,50*np.tan(np.deg2rad(angle))],atol=1e-10)

    def test_camera_center_differs_from_body(self):
        R,lever=chain([5,-3,20],[0,30,45],CFG)
        self.assertGreater(np.linalg.norm(lever),.1)
        np.testing.assert_allclose(R.T@R,np.eye(3),atol=1e-12)
        np.testing.assert_allclose(rpy_ned(ENU_FROM_NED@rotation(5,-3,20)),[5,-3,20],atol=1e-10)

    def test_invalid_height_and_horizon_rejected(self):
        R,_=chain([0,0,0],[0,0,0],CFG)
        with self.assertRaises(ValueError):plane_rays([[0,0]],K_from(CFG),R,0)
        R,_=chain([0,0,0],[0,90,0],CFG)
        with self.assertRaises(ValueError):plane_rays([[319.5,239.5]],K_from(CFG),R,50)

    def test_rectification_matches_independent_ground_projection(self):
        measurement=dict(body_rpy_deg=[3,-2,10],gimbal_rpy_deg=[0,30,45],height_body_agl_m=50)
        U=np.array([[1.0002,.015],[-.015,1.0002]])
        _,mask,H,_,R,lever=orthorectify(np.zeros((480,640,3),np.uint8),measurement,CFG,U)
        self.assertGreater((mask>0).mean(),.25)
        pixels=np.array([[100,100],[500,100],[500,350],[100,350],[319.5,239.5]],np.float64)
        ground=plane_rays(pixels,K_from(CFG),R,50+lever[2])@np.linalg.inv(U).T
        projected=cv2.perspectiveTransform(pixels[None],H)[0]
        # A single affine transform must map metric ground points to rectified pixels.
        A=np.column_stack([ground[:4],np.ones(4)]);fit=np.linalg.lstsq(A,projected[:4],rcond=None)[0]
        np.testing.assert_allclose(np.r_[ground[4],1]@fit,projected[4],atol=1e-4)

if __name__=='__main__':unittest.main()
