"""Open truth only AFTER predictions, then verify original workspace preservation."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
import csv
from geometry import rotation

HERE=Path(__file__).resolve().parent

def main():
    cfg=json.loads((HERE/'config.json').read_text());out=HERE/'outputs'
    predictions=json.loads((out/'predictions.json').read_text(encoding='utf8'))
    truth={p['case_id']:p for p in json.loads((out/'truth_evaluation_only.json').read_text(encoding='utf8'))}
    rows=[];poses=[]
    for p in predictions:
        t=truth[p['case_id']]
        for method in ['baseline','oblique']:
            result=p[method];error=None;alt_error=None;camera_error=None;body_angle_error=None
            if result['accepted']:
                error=float(np.linalg.norm(np.array(result['body_utm'])-[t['body']['utm_e_m'],t['body']['utm_n_m']]))
                alt_error=result['body']['altitude_sim_datum_m']-t['body']['altitude_sim_datum_m']
                if result.get('camera_utm') is not None:camera_error=float(np.linalg.norm(np.array(result['camera_utm'])-[t['camera']['utm_e_m'],t['camera']['utm_n_m']]))
            if result['accepted'] and result['body'].get('estimated_rpy_ned_deg') is not None:
                R=rotation(*result['body']['estimated_rpy_ned_deg']);Rt=rotation(*t['body_rpy_ned_deg'])
                body_angle_error=float(np.rad2deg(np.arccos(np.clip((np.trace(Rt.T@R)-1)/2,-1,1))))
            pose=dict(case_id=p['case_id'],method=method,accepted=result['accepted'])
            for name in ['body','camera']:
                fields=(result.get(name) or {}) if result['accepted'] else {}
                for key in ['latitude_deg','longitude_deg','altitude_sim_datum_m','height_agl_m']:
                    pose[name+'_'+key]=fields.get(key)
                rpy=fields.get('estimated_rpy_ned_deg') if name=='body' else fields.get('optical_frame_rpy_in_ned_deg')
                for i,key in enumerate(['roll','pitch','yaw']):pose[name+'_'+key+'_ned_deg']=rpy[i] if rpy is not None else None
            poses.append(pose)
            negative=t['category'] in ['wrong_map_water','uniform_water']
            false=bool(result['accepted'] and (negative or error>cfg['correct_position_threshold_m']))
            rows.append(dict(case_id=p['case_id'],category=t['category'],source_map=t['source_map_id'],tilt_deg=t['nominal_gimbal_tilt_deg'],method=method,
                             accepted=result['accepted'],false_accept=false,body_error_m=error,
                             camera_error_m=camera_error,altitude_error_m=alt_error,body_orientation_error_deg=body_angle_error,total_ms=result['total_ms'],
                             reason=result['reason']))
    summary={}
    for method in ['baseline','oblique']:
        summary[method]={}
        for category in ['land_reference','water_in_map','wrong_map_water','uniform_water']:
            group=[r for r in rows if r['method']==method and r['category']==category]
            correct=[r for r in group if r['accepted'] and not r['false_accept']]
            summary[method][category]=dict(cases=len(group),accepted=sum(r['accepted'] for r in group),
                                         correctly_localized=len(correct),false_accepts=sum(r['false_accept'] for r in group),
                                         mean_correct_body_error_m=float(np.mean([r['body_error_m'] for r in correct])) if correct else None,
                                         mean_correct_camera_error_m=float(np.mean([r['camera_error_m'] for r in correct if r['camera_error_m'] is not None])) if correct else None,
                                         mean_abs_altitude_error_m=float(np.mean([abs(r['altitude_error_m']) for r in correct])) if correct else None,
                                         mean_body_orientation_error_deg=float(np.mean([r['body_orientation_error_deg'] for r in correct if r['body_orientation_error_deg'] is not None])) if correct else None,
                                         mean_ms=float(np.mean([r['total_ms'] for r in group])))
    summary['land_by_map']={}
    for map_id in sorted({r['source_map'] for r in rows if r['category']=='land_reference'}):
        summary['land_by_map'][map_id]={}
        for method in ['baseline','oblique']:
            group=[r for r in rows if r['source_map']==map_id and r['category']=='land_reference' and r['method']==method]
            summary['land_by_map'][map_id][method]=dict(cases=len(group),accepted=sum(r['accepted'] for r in group),correct=sum(r['accepted'] and not r['false_accept'] for r in group))
    manifest=json.loads((HERE/'baseline_manifest.json').read_text());source=Path(manifest['source_root'])
    changed=[name for name,digest in manifest['files'].items() if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest]
    resources_changed=[name for name,digest in manifest.get('resource_sha256',{}).items() if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest]
    index_unchanged=hashlib.sha256((source/'.git/index').read_bytes()).hexdigest()==manifest['source_index_sha256']
    head_unchanged=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==manifest['source_head']
    status=base64.b64encode(subprocess.check_output(['git','--no-optional-locks','status','--porcelain=v1','-z'],cwd=source)).decode()
    preservation=dict(changed_source_files=changed,changed_resources=resources_changed,index_unchanged=index_unchanged,
                      head_unchanged=head_unchanged,status_unchanged=status==manifest['source_status_b64'])
    summary['preservation']=preservation
    if changed or resources_changed or not all([index_unchanged,head_unchanged,preservation['status_unchanged']]):
        raise RuntimeError('Original workspace preservation check failed: '+str(preservation))
    (out/'evaluation.json').write_text(json.dumps(dict(summary=summary,rows=rows),indent=2,ensure_ascii=False),encoding='utf8')
    with (out/'estimated_poses.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(poses[0]));writer.writeheader();writer.writerows(poses)
    execution=json.loads((out/'execution.json').read_text(encoding='utf8'))
    lines=['# Synthetic oblique-camera experiment','',
           'No flights, PX4 messages, additional rangefinder or terrain were introduced. Original workspace preservation verified.',
           '', 'Both methods use the same images and noisy body attitude/height. The candidate additionally uses measured gimbal angles, absent from the baseline interface. Baseline is the frozen operational localizer fed oblique images without gimbal adaptation. Temporal state resets per case: this measures independent relocalization, not navigation continuity.',
           '', '| Method | Cases | Accepted | Correct ≤5 m | False accepts | Mean latency |', '|---|---:|---:|---:|---:|---:|']
    for method in ['baseline','oblique']:
        for category,s in summary[method].items():
            lines.append(f'| {method}: {category} | {s["cases"]} | {s["accepted"]} | {s["correctly_localized"]} | {s["false_accepts"]} | {s["mean_ms"]:.0f} ms |')
    lines += ['', '## Land views by source map', '', '| Source map | Baseline correct | Oblique correct |', '|---|---:|---:|']
    for map_id,methods in summary['land_by_map'].items():
        lines.append(f'| {map_id} | {methods["baseline"]["correct"]}/{methods["baseline"]["cases"]} | {methods["oblique"]["correct"]}/{methods["oblique"]["cases"]} |')
    lines += ['', '**The aggregate improvement does not establish coastal recovery:** performance on Sagunto coastal/port references is worse than the baseline in this first set. Investigate the rejected pose-consistency cases before claiming viability for the water-loss scenario; no thresholds were tuned using this evaluation.',
              '', '## Altitude, coordinates and orientation', '',
              '`outputs/estimated_poses.csv` contains latitude, longitude, altitude relative to the simulation datum, AGL, roll, pitch and yaw for both camera and fuselage. Rejected estimates have empty coordinate/pose fields. Camera Euler angles refer to its optical frame; full quaternions/matrices remain in predictions and truth.',
              '', '| Correctly localized land views | Body XY error | Camera XY error | Body altitude absolute error | Visual body-pose orientation error |',
              '|---|---:|---:|---:|---:|']
    for method in ['baseline','oblique']:
        s=summary[method]['land_reference']
        def fmt(value,digits=3):return '—' if value is None else f'{value:.{digits}f}'
        lines.append(f'| {method} | {fmt(s["mean_correct_body_error_m"])} m | {fmt(s["mean_correct_camera_error_m"])} m | {fmt(s["mean_abs_altitude_error_m"])} m | {fmt(s["mean_body_orientation_error_deg"],2)}° |')
    lines += ['', f'Inference run: {execution["seconds"]:.1f} seconds on {execution["gpu"]}. Maximum candidate latency observed: '+f'{max(r["total_ms"] for r in rows if r["method"]=="oblique"):.0f} ms.',
              '', 'The candidate improved correct land-reference localizations in this set, but still rejected half of them. This is a partial feasibility result, not a resolved navigation system.',
              '', '## Interpretation limits','',
              '- Water accepted in the correct map is not automatically a false geographical fix: error is checked against withheld truth. It still does not demonstrate navigation over changing real water.',
              '- Wrong-map water and uniform-water images are explicit rejection controls. Every acceptance there is a false acceptance.',
              '- This small synthetic set reuses the exact ortho texture as scene and map; no claim of real-image generalization or zero operational false-positive rate is justified.',
              '- Static independent captures and ideal pinhole intrinsics with zero distortion were used. Dynamic gimbal lag, rolling shutter, blur, altitude dropouts and near-horizon views have not been validated.',
              '- The visual body-pose orientation column does not measure PX4/IMU attitude error: the baseline interprets the added camera through its original fixed ventral mount, whereas the candidate knows the measured gimbal transform. The methods also have different accepted subsets.',
              '- Candidate latency has no 0.9-second limit; baseline retains its operational limit. Latencies are reported and cannot be interpreted as an equal-budget performance win.',
              '- Height and angle noise values are synthetic assumptions. The first-order covariance is experimental and not calibrated.',
              '- Latitude, longitude, altitude/AGL and orientation for both camera and fuselage are in withheld truth. Accepted estimates are separately stored in predictions; unknown/rejected positions are not fabricated.',
              '', 'Detailed outputs: `outputs/evaluation.json`, `outputs/estimated_poses.csv`, `outputs/predictions.json`, `outputs/truth_evaluation_only.json`, `outputs/execution.json`.']
    (HERE/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__':main()
