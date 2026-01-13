import os
import json
import csv
from pathlib import Path

# === CONFIGURATION ===
BASE_DIR = Path(__file__).parent.parent  # Répertoire du script
AI_MODELS_DIR = BASE_DIR / "AI-models"
ANONYMIZER_MODELS_DIR = BASE_DIR / "wama" / "anonymizer" / "models"
OLLAMA_DIR = Path(r"D:\.ollama")  # Chemin externe pour wama-dev-ai

# Fichiers de sortie
OUTPUT_CSV = "wama_models_list.csv"
OUTPUT_JSON = "wama_models_list.json"

# === MODELS DATABASE ===
# Liste des modèles par application (basé sur les fichiers trouvés)
models_data = []

# === 1. Analyse du dossier AI-models ===
def scan_ai_models():
    if not AI_MODELS_DIR.exists():
        print(f"⚠️ Dossier non trouvé : {AI_MODELS_DIR}")
        return
    print(f"🔍 Analyse du dossier : {AI_MODELS_DIR}")
    for file_path in AI_MODELS_DIR.rglob("*"):
        if file_path.is_file():
            ext = file_path.suffix.lower()
            if ext in {".pt", ".onnx", ".bin", ".json", ".yaml", ".yml"}:
                models_data.append({
                    "Application": "AI-models",
                    "Model Name": file_path.name,
                    "Path": str(file_path.relative_to(BASE_DIR)),
                    "Type": ext[1:].upper(),
                    "Status": "local"
                })

# === 2. Analyse du dossier anonymizer/models ===
def scan_anonymizer_models():
    if not ANONYMIZER_MODELS_DIR.exists():
        print(f"⚠️ Dossier non trouvé : {ANONYMIZER_MODELS_DIR}")
        return
    print(f"🔍 Analyse du dossier : {ANONYMIZER_MODELS_DIR}")
    for file_path in ANONYMIZER_MODELS_DIR.rglob("*"):
        if file_path.is_file():
            ext = file_path.suffix.lower()
            if ext in {".pt", ".onnx", ".bin"}:
                models_data.append({
                    "Application": "anonymizer",
                    "Model Name": file_path.name,
                    "Path": str(file_path.relative_to(BASE_DIR)),
                    "Type": ext[1:].upper(),
                    "Status": "local"
                })

# === 3. Analyse du dossier D:\.ollama (wama-dev-ai) ===
def scan_ollama_models():
    if not OLLAMA_DIR.exists():
        print(f"⚠️ Dossier externe non trouvé : {OLLAMA_DIR}")
        return
    print(f"🔍 Analyse du dossier externe : {OLLAMA_DIR}")
    for file_path in OLLAMA_DIR.rglob("*"):
        if file_path.is_file():
            ext = file_path.suffix.lower()
            if ext in {".pt", ".onnx", ".bin", ".json"}:
                # On suppose que les modèles dans .ollama sont des modèles de développement
                models_data.append({
                    "Application": "wama_lab",
                    "Model Name": file_path.name,
                    "Path": str(file_path.relative_to(OLLAMA_DIR)),
                    "Type": ext[1:].upper(),
                    "Status": "external"
                })

# === 4. Export vers CSV et JSON ===
def export_to_files():
    # Export CSV
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as csvfile:
        fieldnames = ["Application", "Model Name", "Path", "Type", "Status"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(models_data)
    print(f"✅ Export CSV terminé : {OUTPUT_CSV}")

    # Export JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as jsonfile:
        json.dump(models_data, jsonfile, indent=4, ensure_ascii=False)
    print(f"✅ Export JSON terminé : {OUTPUT_JSON}")

# === MAIN ===
def main():
    print("📊 Analyse des modèles WAMA par application...\n")
    scan_ai_models()
    scan_anonymizer_models()
    scan_ollama_models()

    if not models_data:
        print("❌ Aucun modèle trouvé dans les dossiers analysés.")
        return

    print(f"\n📋 Total de modèles trouvés : {len(models_data)}")
    print("\nRésumé des applications trouvées :")
    apps = set(m["Application"] for m in models_data)
    for app in sorted(apps):
        count = sum(1 for m in models_data if m["Application"] == app)
        print(f"  - {app}: {count} modèle(s)")

    export_to_files()

if __name__ == "__main__":
    main()