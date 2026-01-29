# scripts/weekly_model_discovery.py
import datetime
import json

from manager import WAMAModelManager


def weekly_discovery():
    manager = WAMAModelManager()

    # 1. Découvrir de nouveaux modèles
    categories = ["text-to-image", "speech-to-text", "text-to-speech",
                  "object-detection", "segmentation"]

    all_new = []
    for cat in categories:
        new_models = manager.discover_new_models(category=cat)
        all_new.extend(new_models)

    # 2. Vérifier les liens existants
    verification = manager.verify_model_links()

    # 3. Proposer les mises à jour
    updates = manager.suggest_updates()

    # 4. Générer un rapport
    report = {
        "date": datetime.now().isoformat(),
        "new_models_found": len(all_new),
        "new_models": all_new[:10],  # Top 10
        "broken_links": verification["broken"],
        "available_updates": updates
    }

    # 5. Sauvegarder ou notifier
    with open("reports/weekly_discovery.json", "w") as f:
        json.dump(report, indent=2)

    return report