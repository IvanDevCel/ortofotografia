"""Política sin cola FIFO: sólo puede quedar una imagen pendiente, la última."""
from dataclasses import dataclass

@dataclass
class LatestFramePolicy:
    last_selected:int=0
    max_start_age_s:float=1.
    max_publish_age_s:float=1.5

    def select(self,newest_available:int):
        if newest_available<=self.last_selected:return None,[]
        skipped=list(range(self.last_selected+1,newest_available))
        self.last_selected=newest_available
        return newest_available,skipped

    def may_start(self,capture_s,now_s):return 0<=now_s-capture_s<=self.max_start_age_s
    def may_publish(self,capture_s,now_s):return 0<=now_s-capture_s<=self.max_publish_age_s

def replay_policy(captures,durations,latest=True):
    """Discrete-event replay of measured compute durations, not a new flight."""
    n=len(captures);finished=0.;last=0;rows=[];skipped=[];policy=LatestFramePolicy()
    while last<n:
        if latest:
            available=[i+1 for i,t in enumerate(captures) if t<=finished+1e-9]
            newest=max(available) if available else last
            if newest<=last:finished=max(finished,captures[last]);newest=last+1
            chosen,dropped=policy.select(newest);skipped.extend(dropped);i=chosen-1
        else:i=last
        start=max(finished,captures[i]);finish=start+durations[i];age=finish-captures[i]
        rows.append({'second':i+1,'capture_s':captures[i],'start_s':start,'finish_s':finish,'publish_age_s':age,
                     'published':not latest or policy.may_publish(captures[i],finish),'queue_policy':'latest' if latest else 'fifo'})
        finished=finish;last=i+1
    return rows,skipped
