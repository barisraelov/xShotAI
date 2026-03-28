# temporary runner — called by the shell to avoid encoding issues with Hebrew filenames
import os, sys

folder = r'c:\Users\baris\Desktop\פרוייקט גמר-סדנא\backend'
input_dir = os.path.join(folder, 'test_videos', 'input')
files = [f for f in os.listdir(input_dir) if f.lower().endswith('.mp4')]
if not files:
    print("No .mp4 files found in test_videos/input")
    sys.exit(1)

video_path = os.path.join(input_dir, files[0])
print(f"Found video: {files[0]}")
print(f"Full path  : {video_path}")

sys.argv = ['test_cv.py', video_path, '--debug-video']

# run test_cv.py in the same process, reading with explicit utf-8
exec(open(os.path.join(folder, 'test_cv.py'), encoding='utf-8').read())
