"""Monte la vidéo de présentation à partir des enregistrements de record_gestures.py.

Étape 1 (décimation) : retire les images quasi identiques (attentes réseau, temporisations)
— il ne reste que les moments où l'écran bouge.
Étape 2 : chaque clip est accéléré pour tenir dans le budget, légendé, puis tout est concaténé
entre une carte de titre et une carte de fin.
Usage : python edit_video.py <rec_dir> <plan.json> <out.mp4> [target_s]
plan.json : {"title": [...], "end": [...], "clips": [{"id":..., "label":..., "sub":...}, ...]}
"""
import json
import subprocess
import sys
from pathlib import Path

REC = Path(sys.argv[1]).resolve()
PLAN = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
OUT = Path(sys.argv[3])
TARGET = float(sys.argv[4]) if len(sys.argv) > 4 else 120.0
WORK = REC / '_work'
WORK.mkdir(exist_ok=True)
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
W, H, FPS = 1920, 1080, 30
BG = '0x0b1220'
CARD_S = 4.0
MAX_SPEED = 16.0
MIN_SPEED = 1.0
MIN_OUT = 2.8


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"ffmpeg failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r


def duration(p):
    r = run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(p)])
    return float(r.stdout.strip() or 0)


def textfile(name, text):
    p = WORK / f'{name}.txt'
    p.write_text(text, encoding='utf-8')
    return str(p).replace(':', r'\:')


manifest = {r['id']: r for r in json.loads((REC / 'manifest.json').read_text(encoding='utf-8'))}

# ── Étape 1 : concat des contextes d'un geste + décimation ────────────────────
decimated = []
for i, clip in enumerate(PLAN['clips']):
    row = manifest.get(clip['id'])
    if not row or not row['videos']:
        print('skip (no video)', clip['id'])
        continue
    vids = sorted(row['videos'], key=lambda v: Path(v).stat().st_mtime)
    dst = WORK / f'dec_{i:02d}.mp4'
    if not dst.exists():
        cmd = ['ffmpeg', '-v', 'error', '-y']
        for v in vids:
            cmd += ['-i', v]
        parts = ''.join(
            f'[{k}:v]scale=1500:1000:force_original_aspect_ratio=decrease,'
            f'pad=1500:1000:(ow-iw)/2:(oh-ih)/2:color={BG},fps=25,setsar=1[v{k}];'
            for k in range(len(vids)))
        concat = ''.join(f'[v{k}]' for k in range(len(vids)))
        filt = (f'{parts}{concat}concat=n={len(vids)}:v=1:a=0,'
                f'mpdecimate=hi=64*24:lo=64*8:frac=0.5,setpts=N/25/TB[out]')
        run(cmd + ['-filter_complex', filt, '-map', '[out]', '-c:v', 'libx264', '-preset',
                   'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', str(dst)])
    d = duration(dst)
    clip['_raw'] = sum(duration(v) for v in vids)
    print(f'{clip["id"]:40s} raw {clip["_raw"]:6.1f}s  decimated {d:6.1f}s')
    decimated.append((clip, dst, d))

# ── Budget : vitesse par clip ────────────────────────────────────────────────
budget = TARGET - 2 * CARD_S
per = budget / len(decimated)


def plan_speeds(per_clip):
    out = []
    for clip, src, d in decimated:
        # Un clip trop court pour lire sa légende est ralenti jusqu'à MIN_OUT (images figées).
        floor = MIN_SPEED if d >= MIN_OUT else max(d / MIN_OUT, 0.25)
        out.append(max(min(d / per_clip, MAX_SPEED), floor))
    return out


# Ajuste la cible par clip pour que la somme colle au budget (clips courts = moins de temps).
lo, hi = per * 0.3, per * 4
for _ in range(40):
    mid = (lo + hi) / 2
    total = sum(d / s for (_, _, d), s in zip(decimated, plan_speeds(mid)))
    lo, hi = (mid, hi) if total < budget else (lo, mid)
speeds = plan_speeds((lo + hi) / 2)

# ── Étape 2 : rendu légendé ──────────────────────────────────────────────────
VW, VH = 1620, 1080
segments = []


def card(name, lines):
    dst = WORK / f'{name}.mp4'
    draws = []
    y0 = H / 2 - (len(lines) * 70) / 2
    for k, (txt, size, bold, color) in enumerate(lines):
        tf = textfile(f'{name}_{k}', txt)
        draws.append(f"drawtext=fontfile={BOLD if bold else FONT}:textfile='{tf}':fontsize={size}:"
                     f"fontcolor={color}:x=(w-text_w)/2:y={y0 + k * 70:.0f}")
    vf = ','.join(draws + [f'fade=t=in:st=0:d=0.5,fade=t=out:st={CARD_S - 0.5}:d=0.5'])
    run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={BG}:s={W}x{H}:r={FPS}:d={CARD_S}',
         '-vf', vf, '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', str(dst)])
    return dst


def lines_of(spec):
    return [(l['text'], l.get('size', 44), l.get('bold', False), l.get('color', 'white')) for l in spec]


segments.append(card('title', lines_of(PLAN['title'])))
n = len(decimated)
for k, ((clip, src, d), s) in enumerate(zip(decimated, speeds)):
    dst = WORK / f'seg_{k:02d}.mp4'
    t_label = textfile(f'lab_{k}', clip['label'])
    t_sub = textfile(f'sub_{k}', clip.get('sub', ''))
    out_d = d / s
    eff = clip['_raw'] / out_d if out_d else 1
    t_speed = textfile(f'spd_{k}', f'×{eff:.0f}')
    t_idx = textfile(f'idx_{k}', f'{k + 1}/{n}')
    vf = (f'setpts=PTS/{s:.4f},fps={FPS},scale={VW}:{VH},pad={W}:{H}:{(W - VW) // 2}:0:color={BG},'
          f'drawbox=x=0:y={H - 110}:w={W}:h=110:color=black@0.72:t=fill,'
          f"drawtext=fontfile={BOLD}:textfile='{t_label}':fontsize=40:fontcolor=white:x=60:y={H - 98},"
          f"drawtext=fontfile={FONT}:textfile='{t_sub}':fontsize=26:fontcolor=0x9fb3d1:x=60:y={H - 46},"
          f"drawtext=fontfile={BOLD}:textfile='{t_speed}':fontsize=36:fontcolor=0xffb347:x=w-text_w-60:y={H - 92},"
          f"drawtext=fontfile={FONT}:textfile='{t_idx}':fontsize=24:fontcolor=0x9fb3d1:x=w-text_w-60:y={H - 44},"
          f'fade=t=in:st=0:d=0.25,fade=t=out:st={max(0, out_d - 0.25):.3f}:d=0.25')
    run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-vf', vf, '-an', '-c:v', 'libx264',
         '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', str(FPS), str(dst)])
    print(f'{clip["id"]:40s} ×{s:5.1f} (effectif ×{eff:4.1f}) → {out_d:5.1f}s')
    segments.append(dst)
segments.append(card('end', lines_of(PLAN['end'])))

lst = WORK / 'concat.txt'
lst.write_text(''.join(f"file '{p}'\n" for p in segments), encoding='utf-8')
run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(lst), '-c:v', 'libx264',
     '-preset', 'slow', '-crf', '21', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(OUT)])
print('OUT', OUT, f'{duration(OUT):.1f}s')
