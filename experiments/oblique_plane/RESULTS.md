# Synthetic oblique-camera experiment

No flights, PX4 messages, additional rangefinder or terrain were introduced. Original workspace preservation verified.

Both methods use the same images and noisy body attitude/height. The candidate additionally uses measured gimbal angles, absent from the baseline interface. Baseline is the frozen operational localizer fed oblique images without gimbal adaptation. Temporal state resets per case: this measures independent relocalization, not navigation continuity.

| Method | Cases | Accepted | Correct ≤5 m | False accepts | Mean latency |
|---|---:|---:|---:|---:|---:|
| baseline: land_reference | 16 | 4 | 4 | 0 | 439 ms |
| baseline: water_in_map | 8 | 0 | 0 | 0 | 294 ms |
| baseline: wrong_map_water | 8 | 0 | 0 | 0 | 281 ms |
| baseline: uniform_water | 4 | 0 | 0 | 0 | 226 ms |
| oblique: land_reference | 16 | 8 | 8 | 0 | 377 ms |
| oblique: water_in_map | 8 | 0 | 0 | 0 | 155 ms |
| oblique: wrong_map_water | 8 | 0 | 0 | 0 | 246 ms |
| oblique: uniform_water | 4 | 0 | 0 | 0 | 116 ms |

## Land views by source map

| Source map | Baseline correct | Oblique correct |
|---|---:|---:|
| 02_urbano_lliria | 1/8 | 7/8 |
| 04_mar_costa_sagunto | 3/8 | 1/8 |

**The aggregate improvement does not establish coastal recovery:** performance on Sagunto coastal/port references is worse than the baseline in this first set. Investigate the rejected pose-consistency cases before claiming viability for the water-loss scenario; no thresholds were tuned using this evaluation.

## Altitude, coordinates and orientation

`outputs/estimated_poses.csv` contains latitude, longitude, altitude relative to the simulation datum, AGL, roll, pitch and yaw for both camera and fuselage. Rejected estimates have empty coordinate/pose fields. Camera Euler angles refer to its optical frame; full quaternions/matrices remain in predictions and truth.

| Correctly localized land views | Body XY error | Camera XY error | Body altitude absolute error | Visual body-pose orientation error |
|---|---:|---:|---:|---:|
| baseline | 0.570 m | 0.590 m | 0.137 m | 34.12° |
| oblique | 0.582 m | 0.582 m | 0.316 m | 0.64° |

Inference run: 28.3 seconds on NVIDIA GeForce RTX 5080. Maximum candidate latency observed: 575 ms.

The candidate improved correct land-reference localizations in this set, but still rejected half of them. This is a partial feasibility result, not a resolved navigation system.

## Interpretation limits

- Water accepted in the correct map is not automatically a false geographical fix: error is checked against withheld truth. It still does not demonstrate navigation over changing real water.
- Wrong-map water and uniform-water images are explicit rejection controls. Every acceptance there is a false acceptance.
- This small synthetic set reuses the exact ortho texture as scene and map; no claim of real-image generalization or zero operational false-positive rate is justified.
- Static independent captures and ideal pinhole intrinsics with zero distortion were used. Dynamic gimbal lag, rolling shutter, blur, altitude dropouts and near-horizon views have not been validated.
- The visual body-pose orientation column does not measure PX4/IMU attitude error: the baseline interprets the added camera through its original fixed ventral mount, whereas the candidate knows the measured gimbal transform. The methods also have different accepted subsets.
- Candidate latency has no 0.9-second limit; baseline retains its operational limit. Latencies are reported and cannot be interpreted as an equal-budget performance win.
- Height and angle noise values are synthetic assumptions. The first-order covariance is experimental and not calibrated.
- Latitude, longitude, altitude/AGL and orientation for both camera and fuselage are in withheld truth. Accepted estimates are separately stored in predictions; unknown/rejected positions are not fabricated.

Detailed outputs: `outputs/evaluation.json`, `outputs/estimated_poses.csv`, `outputs/predictions.json`, `outputs/truth_evaluation_only.json`, `outputs/execution.json`.
