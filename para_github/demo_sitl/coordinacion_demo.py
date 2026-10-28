"""Pure coordination helpers; no PX4, Gazebo or model imports."""
import math

def validate_onboard(ob,*,temporal):
    required=['agl_baro_m','q_capture_wxyz','ref_lat','ref_lon']
    if temporal:required+=['capture_sim_s','velocity_ned_m_s','gyro_frd_rad_s']
    missing=[k for k in required if k not in ob]
    if missing:raise ValueError('Contrato onboard: faltan '+', '.join(missing))
    if len(ob['q_capture_wxyz'])!=4 or not all(math.isfinite(x) for x in ob['q_capture_wxyz']):raise ValueError('Cuaternion invalido')
    if temporal and not math.isfinite(ob['capture_sim_s']):raise ValueError('Marca de captura invalida')

def route_points(cfg):
    if cfg.get('mission_waypoints'):return [(cfg.get('start_label','A'),cfg['A'])]+[(p.get('label',str(i)),p) for i,p in enumerate(cfg['mission_waypoints'],1)]
    return [('A',cfg['A'])]+[(chr(ord('C')+i),p) for i,p in enumerate(cfg.get('intermediate_waypoints',[]))]+[('B',cfg['B'])]

class AbsoluteVideoClock:
    """Frame slots referenced to actual simulation start, never first poll."""
    def __init__(self,fps=5,duration=45):self.fps=fps;self.duration=duration;self.frames=0
    def slots_due(self,start_sim_s,now_sim_s,finish=False):
        if start_sim_s is None:return 0
        target=round(self.duration*self.fps) if finish else min(round(self.duration*self.fps),max(0,int((now_sim_s-start_sim_s)*self.fps)+1))
        count=max(0,target-self.frames);self.frames+=count;return count

def publication_allowed(capture,now_sim,compute_s,max_age=1.5):
    # Frozen simulation time at final pause must not hide compute latency.
    return 0<=now_sim-capture<=max_age and compute_s<=max_age

class FlightSchedule:
    """One-based file IDs 001..045 correspond to offsets 0..44 seconds."""
    duration_s=45.
    gnss_cut_s=5.
    def __init__(self,duration=45):
        if not 1<=int(duration)<=180:raise ValueError('Duracion SITL fuera de 1..180 s')
        self.duration_s=int(duration)
    def capture_index(self,start_sim_s,now_sim_s):
        elapsed=now_sim_s-start_sim_s;slot=round(elapsed)
        return slot+1 if 0<=slot<self.duration_s and abs(elapsed-slot)<=.012 else None
    def cut_due(self,start_sim_s,now_sim_s):return now_sim_s-start_sim_s>=self.gnss_cut_s
    def end_due(self,start_sim_s,now_sim_s):return now_sim_s-start_sim_s>=self.duration_s
