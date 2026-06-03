import time, sys, logging
logging.basicConfig(level=logging.WARNING)
sys.path.insert(0, '.')
import cv_pipeline

video = r'C:\Users\ben21\OneDrive\Desktop\final project3_5L.mp4'
out_path = r'C:\Users\ben21\OneDrive\Desktop\test_output.txt'

t0 = time.time()
diag = cv_pipeline._run_pipeline_verbose(video)
elapsed = time.time() - t0
shot_points = diag.get("shot_points", [])

made   = sum(1 for s in shot_points if s["result"] == "made")
missed = len(shot_points) - made
fg_pct = round(made / len(shot_points) * 100, 1) if shot_points else 0.0

lines = []
lines.append("=== xShot AI — Test Run ===")
lines.append(f"Video  : {video}")
lines.append(f"Runtime: {elapsed:.1f}s")
lines.append(f"Shots  : {len(shot_points)}  |  Made: {made}  |  Missed: {missed}  |  FG%: {fg_pct}%")
lines.append("")
lines.append("--- Shot Details ---")

for s in shot_points:
    z    = s.get("zone")
    org  = s.get("origin", {})
    px   = org.get("pixel") or {}
    traj = s.get("trajectory") or {}

    zone_str  = z["label"] if z else "no calibration (zone N/A)"
    pixel_str = f'pixel=({px.get("u")},{px.get("v")})' if px else "pixel=N/A"
    arc       = traj.get("arc_height_px")
    arc_str   = f"arc={arc}px" if arc is not None else ""

    lines.append(
        f"  {s['shot_id']}  {s['result'].upper():6}  zone={zone_str:<30}  {pixel_str}  {arc_str}"
    )

output = "\n".join(lines)
print(output)

with open(out_path, "w", encoding="utf-8") as f:
    f.write(output)

print(f"\nSaved to: {out_path}")
