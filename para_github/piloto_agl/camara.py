"""Geometría de cámara cenital, pinhole, sin relieve ni distorsión."""
import math


def footprint(camera, agl):
    if not 0 < agl <= camera['max_agl_m']:
        raise ValueError('La altura AGL debe ser mayor que 0 y como máximo 400 m')
    width = 2 * agl * math.tan(math.radians(camera['hfov_deg']/2))
    height = width * camera['height']/camera['width']
    return {'agl_m': agl, 'width_m': width, 'height_m': height,
            'area_m2': width*height, 'gsd_m_px': width/camera['width']}


def camera_parameters(camera):
    fx = camera['width']/(2*math.tan(math.radians(camera['hfov_deg']/2)))
    return {**camera, 'vfov_deg': math.degrees(2*math.atan(camera['height']/(2*fx))),
            'fx_px': fx, 'fy_px': fx, 'cx_edge_px': camera['width']/2,
            'cy_edge_px': camera['height']/2, 'projection': 'pinhole, nadir, plano horizontal',
            'heights': [footprint(camera,h) for h in camera['heights_m']]}
