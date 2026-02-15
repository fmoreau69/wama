"""
WAMA - Rosbag Video Extractor (version finale corrigée)
=========================================================
Extraction de vidéos depuis des fichiers .bag ROS1

✅ Fonctionne sans installation ROS (pure Python)
✅ Compatible Python 3.12
✅ Supporte CompressedImage (JPEG/PNG compressé)
✅ Multi-caméras

Dépendances :
    pip install rosbags opencv-python numpy

Usage :
    python rosbag_extractor.py --inspect -i votre_fichier.bag
    python rosbag_extractor.py -i votre_fichier.bag -o ./videos/
    python rosbag_extractor.py -i votre_fichier.bag -t /camera_front_center_tele/image_color/compressed -o ./videos/
"""

import argparse
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Tuple


# =============================================================================
# 1. INSPECTION DU BAG
# =============================================================================

def inspect_bag(bag_path: Path) -> List[Dict]:
    """Liste tous les topics et calcule le FPS."""
    from rosbags.rosbag1 import Reader

    topics: Dict[str, Dict] = {}

    with Reader(str(bag_path)) as reader:
        duration_s = reader.duration / 1e9

        # Collecter les types de messages
        for conn in reader.connections:
            if conn.topic not in topics:
                topics[conn.topic] = {
                    "topic": conn.topic,
                    "msgtype": conn.msgtype,
                    "count": 0,
                    "is_image": "CompressedImage" in conn.msgtype or "Image" in conn.msgtype,
                }

        # Compter les messages
        for conn, timestamp, rawdata in reader.messages():
            topics[conn.topic]["count"] += 1

    # Calculer le FPS
    result = []
    for t in topics.values():
        if t["is_image"] and duration_s > 0:
            t["fps_estimated"] = round(t["count"] / duration_s, 2)
        else:
            t["fps_estimated"] = None
        result.append(t)

    return result


def print_inspection(bag_path: Path, topics: List[Dict]):
    """Affiche l'inspection du bag."""
    print(f"\n{'=' * 80}")
    print(f"📋  Contenu du bag : {bag_path.name}")
    print(f"{'=' * 80}")
    print(f"{'Topic':<50} {'Type':<30} {'Msgs':>7} {'FPS':>7}")
    print(f"{'-' * 80}")

    for t in topics:
        fps_str = f"{t['fps_estimated']}" if t["fps_estimated"] else "   -"
        marker = " 🎬" if t["is_image"] else ""
        print(f"{t['topic']:<50} {t['msgtype']:<30} {t['count']:>7} {fps_str:>7}{marker}")

    print(f"{'-' * 80}")

    image_topics = [t for t in topics if t["is_image"]]
    print(f"\n🎬 Topics vidéo détectés : {len(image_topics)}")
    for t in image_topics:
        duration_s = t["count"] / t["fps_estimated"] if t["fps_estimated"] else 0
        print(f"   → {t['topic']}")
        print(f"      Type     : {t['msgtype']}")
        print(f"      Frames   : {t['count']}")
        print(f"      FPS      : ~{t['fps_estimated']}")
        print(f"      Durée    : ~{duration_s:.1f}s")
    print()


# =============================================================================
# 2. EXTRACTION DES FRAMES
# =============================================================================

def extract_frames_compressed(bag_path: Path, topic: str) -> Tuple[List[np.ndarray], float]:
    """
    Extrait les frames d'un topic CompressedImage.
    Parse directement les bytes JPEG/PNG depuis les données brutes.
    """
    from rosbags.rosbag1 import Reader

    frames = []
    timestamps = []

    print(f"  📖 Lecture de {topic}...")

    with Reader(str(bag_path)) as reader:
        # Filtrer les connections
        connections = [c for c in reader.connections if c.topic == topic]

        if not connections:
            raise ValueError(f"❌ Topic '{topic}' introuvable dans le bag.")

        conn = connections[0]
        print(f"     Type : {conn.msgtype}")

        # Compter le total
        total = sum(1 for c, t, r in reader.messages(connections=connections))
        print(f"     Total : {total} messages")

        # Extraire les images
        for i, (conn, timestamp, rawdata) in enumerate(reader.messages(connections=connections)):
            # Parser les bytes bruts - chercher JPEG ou PNG
            data_bytes = bytes(rawdata)

            # Chercher signature JPEG (0xFF 0xD8)
            jpeg_start = data_bytes.find(b'\xff\xd8')
            if jpeg_start != -1:
                img_data = data_bytes[jpeg_start:]
                img_array = np.frombuffer(img_data, dtype=np.uint8)
                img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

                if img is not None:
                    frames.append(img)
                    timestamps.append(timestamp)
                else:
                    print(f"     ⚠️  Frame {i} : décodage JPEG échoué")
            else:
                # Chercher signature PNG (0x89 'PNG')
                png_start = data_bytes.find(b'\x89PNG')
                if png_start != -1:
                    img_data = data_bytes[png_start:]
                    img_array = np.frombuffer(img_data, dtype=np.uint8)
                    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

                    if img is not None:
                        frames.append(img)
                        timestamps.append(timestamp)
                    else:
                        print(f"     ⚠️  Frame {i} : décodage PNG échoué")
                else:
                    if i == 0:  # Afficher seulement pour la première frame
                        print(f"     ⚠️  Frame {i} : aucune signature JPEG/PNG trouvée")

            # Progression
            if (i + 1) % 500 == 0:
                print(f"     ... {i + 1}/{total} frames extraites ({100 * (i + 1) / total:.1f}%)", end="\r")

        print(f"     ✅ {len(frames)} frames extraites sur {total}")

    # Calculer le FPS
    fps = 30.0
    if len(timestamps) > 1:
        diffs = np.diff(timestamps)
        median_dt = np.median(diffs)
        if median_dt > 0:
            fps = round(1e9 / median_dt, 2)

    return frames, fps


# =============================================================================
# 3. ÉCRITURE VIDÉO
# =============================================================================

def write_video(frames: List[np.ndarray], output_path: Path, fps: float):
    """Écrit les frames en fichier MP4."""
    if not frames:
        print(f"  ⚠️  Aucune frame à écrire")
        return

    h, w = frames[0].shape[:2]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Codec H264 pour MP4
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

    if not writer.isOpened():
        print(f"  ❌ Impossible d'ouvrir le writer vidéo")
        return

    print(f"  💾 Écriture de la vidéo...")
    for i, frame in enumerate(frames):
        writer.write(frame)
        if (i + 1) % 500 == 0:
            print(f"     ... {i + 1}/{len(frames)} frames écrites ({100*(i+1)/len(frames):.1f}%)", end="\r")

    writer.release()

    # Stats
    size_mb = output_path.stat().st_size / (1024 ** 2)
    duration_s = len(frames) / fps
    print(f"  ✅ Vidéo créée : {output_path.name}")
    print(f"     Résolution : {w}x{h}")
    print(f"     Frames     : {len(frames)}")
    print(f"     FPS        : {fps}")
    print(f"     Durée      : {duration_s:.1f}s")
    print(f"     Taille     : {size_mb:.1f} MB")


# =============================================================================
# 4. ORCHESTRATEUR
# =============================================================================

class WAMABagExtractor:
    """Extracteur de vidéos depuis un rosbag."""

    def __init__(self, bag_path: str):
        self.bag_path = Path(bag_path)
        if not self.bag_path.exists():
            raise FileNotFoundError(f"❌ Fichier introuvable : {self.bag_path}")

        size_mb = self.bag_path.stat().st_size / (1024**2)
        print(f"📦 Fichier : {self.bag_path.name} ({size_mb:.1f} MB)")

    def inspect(self) -> List[Dict]:
        """Inspecte le bag."""
        topics = inspect_bag(self.bag_path)
        print_inspection(self.bag_path, topics)
        return topics

    def extract_topic(self, topic: str, output_dir: Path, fps_override: Optional[float] = None):
        """Extrait une vidéo depuis un topic."""
        print(f"\n🔄 Extraction : {topic}")

        # Extraire les frames
        frames, fps_detected = extract_frames_compressed(self.bag_path, topic)

        fps = fps_override if fps_override else fps_detected
        print(f"  FPS détecté : {fps_detected} | FPS utilisé : {fps}")

        # Nom de sortie
        safe_name = topic.replace("/", "_").strip("_")
        output_path = output_dir / f"{self.bag_path.stem}_{safe_name}.mp4"

        # Écrire
        write_video(frames, output_path, fps)

    def extract_all(self, output_dir: Path, fps_override: Optional[float] = None):
        """Extrait toutes les caméras."""
        topics = inspect_bag(self.bag_path)
        image_topics = [t["topic"] for t in topics if t["is_image"]]

        if not image_topics:
            print("\n❌ Aucun topic vidéo trouvé.")
            return

        print(f"\n📁 Dossier de sortie : {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

        for topic in image_topics:
            self.extract_topic(topic, output_dir, fps_override)

        print(f"\n{'='*80}")
        print(f"🎉 Extraction terminée !")
        print(f"   {len(image_topics)} vidéo(s) générée(s) dans : {output_dir}")
        print(f"{'='*80}\n")


# =============================================================================
# 5. CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="🎬 WAMA Rosbag Video Extractor"
    )
    parser.add_argument("--input", "-i", required=True,
                        help="Chemin vers le fichier .bag")
    parser.add_argument("--output", "-o", default="./extracted_videos/",
                        help="Dossier de sortie")
    parser.add_argument("--topic", "-t", default=None,
                        help="Topic spécifique (sinon : tous les topics vidéo)")
    parser.add_argument("--fps", "-f", type=float, default=None,
                        help="FPS forcé (sinon : détecté automatiquement)")
    parser.add_argument("--inspect", action="store_true",
                        help="Inspecter le bag sans extraire")

    args = parser.parse_args()

    extractor = WAMABagExtractor(args.input)

    if args.inspect:
        extractor.inspect()
        return

    output_dir = Path(args.output)

    if args.topic:
        extractor.extract_topic(args.topic, output_dir, args.fps)
    else:
        extractor.extract_all(output_dir, args.fps)


if __name__ == "__main__":
    main()