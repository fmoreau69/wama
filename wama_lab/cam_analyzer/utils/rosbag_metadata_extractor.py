"""
Extracteur de métadonnées complètes d'un fichier rosbag
Génère un fichier JSON avec toutes les infos pour debug
"""

import json
import sys
from pathlib import Path
from datetime import datetime


def sanitize_for_json(obj):
    """Convertit n'importe quel objet en quelque chose de JSON-safe."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    elif isinstance(obj, (list, tuple)):
        return [sanitize_for_json(x) for x in obj]
    elif isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, bytes):
        return f"<bytes len={len(obj)}>"
    elif hasattr(obj, '__dict__'):
        return str(obj)
    else:
        return str(obj)


def extract_metadata(bag_path: str, output_json: str = "bag_metadata.json"):
    """
    Extrait TOUTES les métadonnées d'un rosbag et les sauvegarde en JSON.
    """
    from rosbags.rosbag1 import Reader

    bag_path = Path(bag_path)
    metadata = {
        "file_info": {
            "filename": bag_path.name,
            "size_mb": round(bag_path.stat().st_size / (1024**2), 2),
            "path": str(bag_path.absolute()),
        },
        "bag_info": {},
        "connections": [],
        "topics": {},
        "sample_messages": {},
    }

    print(f"📦 Analyse de : {bag_path.name}")
    print(f"   Taille : {metadata['file_info']['size_mb']} MB\n")

    with Reader(str(bag_path)) as reader:
        # === Infos générales du bag ===
        print("🔍 Extraction des métadonnées générales...")

        try:
            metadata["bag_info"]["duration_s"] = reader.duration / 1e9
            metadata["bag_info"]["start_time"] = reader.start_time
            metadata["bag_info"]["end_time"] = reader.end_time
            metadata["bag_info"]["message_count"] = reader.message_count

            print(f"   Durée : {metadata['bag_info']['duration_s']:.2f} secondes")
            print(f"   Messages : {metadata['bag_info']['message_count']}")
        except AttributeError as e:
            print(f"   ⚠️  Certains attributs manquants : {e}")
            metadata["bag_info"]["error"] = str(e)

        # === Connections (topics + types) ===
        print("\n🔌 Extraction des connections...")

        for conn in reader.connections:
            conn_info = {
                "id": conn.id,
                "topic": conn.topic,
                "msgtype": conn.msgtype,
                "msgdef": conn.msgdef[:500] if hasattr(conn, 'msgdef') and conn.msgdef else None,  # Tronqué
                "md5sum": conn.md5sum if hasattr(conn, 'md5sum') else None,
                "msgcount": getattr(conn, 'msgcount', 0),
            }

            # Essayer d'extraire plus d'infos si disponibles
            for attr in dir(conn):
                if not attr.startswith('_') and attr not in conn_info:
                    try:
                        val = getattr(conn, attr)
                        # Filtrer les callables et objets complexes
                        if not callable(val):
                            conn_info[attr] = sanitize_for_json(val)
                    except:
                        pass

            metadata["connections"].append(conn_info)
            print(f"   {conn.topic:40} → {conn.msgtype}")

        # === Compter les messages par topic ===
        print("\n📊 Comptage des messages par topic...")

        topic_counts = {}
        topic_timestamps = {}

        for conn, timestamp, rawdata in reader.messages():
            topic = conn.topic

            # Compter
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

            # Garder les timestamps pour calculer le FPS
            if topic not in topic_timestamps:
                topic_timestamps[topic] = []
            topic_timestamps[topic].append(timestamp)

        # === Calculer le FPS par topic ===
        print("\n⏱️  Calcul du FPS par topic...")

        for topic, count in topic_counts.items():
            timestamps = topic_timestamps[topic]

            fps = None
            if len(timestamps) > 1:
                import numpy as np
                diffs = np.diff(timestamps)
                median_dt = np.median(diffs)
                if median_dt > 0:
                    fps = round(1e9 / median_dt, 2)

            # Trouver le msgtype
            msgtype = next(
                (c["msgtype"] for c in metadata["connections"] if c["topic"] == topic),
                "unknown"
            )

            metadata["topics"][topic] = {
                "msgtype": msgtype,
                "count": count,
                "fps_estimated": fps,
                "is_image": "Image" in msgtype,
                "first_timestamp": timestamps[0],
                "last_timestamp": timestamps[-1],
            }

            is_img = " 🎬" if "Image" in msgtype else ""
            fps_str = f"{fps} fps" if fps else "-"
            print(f"   {topic:40} {count:>6} msgs  {fps_str:>10}{is_img}")

        # === Échantillonner quelques messages ===
        print("\n📝 Échantillonnage de messages (premiers de chaque topic)...")

        sampled_topics = set()

        with Reader(str(bag_path)) as reader2:
            for conn, timestamp, rawdata in reader2.messages():
                topic = conn.topic

                if topic not in sampled_topics:
                    try:
                        msg = reader2.deserialize(rawdata, conn.msgtype)

                        # Sérialiser le message en dict (limité à 1000 chars)
                        msg_str = str(msg)[:1000]

                        # Essayer d'extraire les champs principaux
                        msg_fields = {}
                        if hasattr(msg, '__slots__'):
                            for field in msg.__slots__:
                                try:
                                    val = getattr(msg, field, None)
                                    # Limiter la longueur des valeurs
                                    if isinstance(val, (list, bytes)):
                                        msg_fields[field] = f"<{type(val).__name__} len={len(val)}>"
                                    else:
                                        msg_fields[field] = str(val)[:200]
                                except:
                                    pass

                        metadata["sample_messages"][topic] = {
                            "msgtype": conn.msgtype,
                            "timestamp": timestamp,
                            "fields": msg_fields,
                            "preview": msg_str,
                        }

                        sampled_topics.add(topic)
                        print(f"   ✅ {topic}")

                        # Arrêter après avoir échantillonné tous les topics
                        if len(sampled_topics) >= len(metadata["topics"]):
                            break

                    except Exception as e:
                        print(f"   ⚠️  {topic} : {e}")

    # === Sauvegarder en JSON ===
    output_path = Path(output_json)

    # Nettoyer les métadonnées pour JSON
    metadata_clean = sanitize_for_json(metadata)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metadata_clean, f, indent=2, ensure_ascii=False)

    print(f"\n💾 Métadonnées sauvegardées : {output_path}")
    print(f"   Taille : {output_path.stat().st_size / 1024:.1f} KB")

    # === Résumé ===
    print(f"\n{'='*70}")
    print("📋 RÉSUMÉ")
    print(f"{'='*70}")
    print(f"Fichier      : {bag_path.name}")
    print(f"Taille       : {metadata['file_info']['size_mb']} MB")
    print(f"Durée        : {metadata['bag_info'].get('duration_s', 'N/A')} s")
    print(f"Messages     : {metadata['bag_info'].get('message_count', 'N/A')}")
    print(f"Topics       : {len(metadata['topics'])}")
    print(f"Images       : {sum(1 for t in metadata['topics'].values() if t['is_image'])}")
    print(f"{'='*70}\n")

    return metadata


def print_debug_info(metadata: dict):
    """Affiche les infos importantes pour le debug."""
    print("\n🔧 INFOS DEBUG IMPORTANTES :\n")

    print("1️⃣  Topics Image :")
    image_topics = {k: v for k, v in metadata["topics"].items() if v["is_image"]}
    for topic, info in image_topics.items():
        print(f"   {topic}")
        print(f"      Type    : {info['msgtype']}")
        print(f"      Frames  : {info['count']}")
        print(f"      FPS     : {info.get('fps_estimated', 'N/A')}")

        # Si on a un échantillon de message
        if topic in metadata["sample_messages"]:
            sample = metadata["sample_messages"][topic]
            print(f"      Champs  : {', '.join(sample['fields'].keys())}")

    print("\n2️⃣  Structure d'un message image (exemple) :")
    if image_topics:
        first_topic = list(image_topics.keys())[0]
        if first_topic in metadata["sample_messages"]:
            sample = metadata["sample_messages"][first_topic]
            print(f"   Topic : {first_topic}")
            for field, value in sample["fields"].items():
                print(f"      {field:20} = {value}")

    print("\n3️⃣  Attributs du Reader disponibles :")
    if "bag_info" in metadata:
        for key, val in metadata["bag_info"].items():
            print(f"   {key:20} = {val}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python rosbag_metadata_extractor.py <fichier.bag> [output.json]")
        sys.exit(1)

    bag_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "bag_metadata.json"

    try:
        metadata = extract_metadata(bag_file, output_file)
        print_debug_info(metadata)

        print(f"\n✅ Envoyez-moi le fichier '{output_file}' pour debug !")

    except Exception as e:
        print(f"\n❌ Erreur : {e}")
        import traceback
        traceback.print_exc()