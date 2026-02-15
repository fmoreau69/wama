#!/usr/bin/env python3
import subprocess
from pathlib import Path

input_file = "videos/all_2022-12-23-09-06-05#7_camera_mirror_left_image_raw_compressed.mp4"
output_file = input_file.replace(".mp4", "_rotated.mp4")

cmd = [
    "ffmpeg", "-i", input_file,
    "-vf", "hflip,vflip",
    "-c:a", "copy",
    output_file, "-y"
]

print(f"🔄 Rotation de {input_file}...")
subprocess.run(cmd)
print(f"✅ Vidéo retournée : {output_file}")