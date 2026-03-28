"""
Run test_cv.py on every .mp4 in test_videos/input, writing per-clip output
to test_videos/output/<name>_report.txt and a debug-annotated video.
Prints a compact summary at the end.
"""
import os, sys, subprocess, time
from pathlib import Path

backend_dir = Path(__file__).parent
input_dir   = backend_dir / "test_videos" / "input"
output_dir  = backend_dir / "test_videos" / "output"
output_dir.mkdir(parents=True, exist_ok=True)

clips = sorted(input_dir.glob("*.mp4"))
if not clips:
    print("No .mp4 files found in test_videos/input/")
    sys.exit(1)

print(f"Found {len(clips)} clip(s): {[c.name for c in clips]}\n")

results = []
for clip in clips:
    report_path = output_dir / (clip.stem + "_report.txt")
    print(f"{'='*60}")
    print(f"Processing {clip.name}  ({clip.stat().st_size / 1_048_576:.1f} MB) …")
    print(f"Report  -> {report_path.name}")
    print(f"{'='*60}")
    t0 = time.time()

    cmd = [sys.executable, str(backend_dir / "test_cv.py"),
           str(clip), "--debug-video"]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(backend_dir),
    )
    output_text = proc.stdout.decode("utf-8", errors="replace")
    report_path.write_text(output_text, encoding="utf-8")

    elapsed = time.time() - t0
    print(f"[{clip.name}] done in {elapsed:.0f}s  exit={proc.returncode}  -> {report_path.name}")
    results.append((clip.name, report_path, proc.returncode, elapsed))

print("\n" + "="*60)
print("ALL CLIPS — PROCESSING COMPLETE")
print("="*60)
for name, rpt, rc, t in results:
    status = "OK" if rc == 0 else f"ERROR (exit {rc})"
    print(f"  {name:<12}  {t:5.0f}s  {status}  report: {rpt.name}")
print()
