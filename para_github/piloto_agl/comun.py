import csv
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT/'outputs'/'piloto_agl'
MODELS = ROOT/'.modelos_agl'


def config():
    return json.loads((ROOT/'piloto_agl/config.json').read_text(encoding='utf8'))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')


def save_csv(path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class Resources:
    """RSS muestreado cada 20 ms, no sumado entre procesos ni confundido con VRAM."""
    def __enter__(self):
        import psutil
        self.process=psutil.Process()
        self.start_rss=self.process.memory_info().rss
        self.peak=self.start_rss
        self.stop=threading.Event()
        self.start=time.perf_counter()
        def poll():
            while not self.stop.wait(.02):
                self.peak=max(self.peak,self.process.memory_info().rss)
        self.thread=threading.Thread(target=poll,daemon=True)
        self.thread.start()
        return self

    def __exit__(self,*args):
        self.seconds=time.perf_counter()-self.start
        self.peak=max(self.peak,self.process.memory_info().rss)
        self.stop.set()
        self.thread.join()

    def result(self):
        return {'seconds':self.seconds,'rss_start_mib':self.start_rss/2**20,
                'rss_peak_mib':self.peak/2**20,'rss_increase_mib':(self.peak-self.start_rss)/2**20}


def setup():
    os.environ.setdefault('TORCH_HOME',str(MODELS/'torch'))
    os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'.mplconfig'))
    OUT.mkdir(parents=True,exist_ok=True)
    import cv2
    import torch
    import numpy as np
    cfg=config()
    torch.set_num_threads(cfg['threads'])
    cv2.setNumThreads(cfg['threads'])
    torch.manual_seed(cfg['seed'])
    np.random.seed(cfg['seed'])
    cv2.setRNGSeed(cfg['seed'])
    return cfg
