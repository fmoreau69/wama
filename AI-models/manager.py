import json
from pathlib import Path
from typing import List, Dict, Optional
from huggingface_hub import HfApi, hf_hub_download, snapshot_download, list_models
import requests

from sources.ollama import OllamaConnector


class WAMAModelManager:
    def __init__(self, base_path="AI-models"):
        self.base_path = Path(base_path)
        self.registry_path = self.base_path / "registry.json"
        self.download_path = self.base_path / "downloaded"
        self.registry = self.load_registry()
        self.hf_api = HfApi()
        self.ollama = OllamaConnector()

    def sync_ollama_models(self):
        """Synchronise le registre avec les modèles Ollama installés"""
        if not self.ollama.ollama_available:
            print("Ollama is not available")
            return

        ollama_models = self.ollama.list_installed_models()

        for model in ollama_models:
            model_id = model["id"]

            # Ajouter ou mettre à jour dans le registre
            if model_id not in self.registry["models"]:
                # Nouveau modèle détecté
                self.registry["models"][model_id] = {
                    **model,
                    "local_path": str(self.ollama.ollama_models_path),
                    "compatible_apps": self._infer_compatible_apps(model_id)
                }
            else:
                # Mettre à jour le statut
                self.registry["models"][model_id]["downloaded"] = True

        self.save_registry()

    def _infer_compatible_apps(self, model_name: str) -> List[str]:
        """Déduit les apps compatibles selon le nom du modèle"""
        apps = []

        if "llava" in model_name.lower():
            apps.append("describer")  # Vision-Language
        elif any(x in model_name.lower() for x in ["llama", "mistral", "phi", "gemma"]):
            apps.append("chatbot")  # LLM classique
        elif "codellama" in model_name.lower():
            apps.extend(["chatbot", "code-assistant"])

        return apps

    def load_registry(self) -> Dict:
        """Charge le registre des modèles"""
        if self.registry_path.exists():
            with open(self.registry_path, 'r') as f:
                return json.load(f)
        return {"models": {}, "app_models_mapping": {}}

    def save_registry(self):
        """Sauvegarde le registre"""
        with open(self.registry_path, 'w') as f:
            json.dump(self.registry, f, indent=2)

    def get_models_for_app(self, app_name: str, task: Optional[str] = None) -> List[Dict]:
        """
        Récupère tous les modèles compatibles avec une application

        Args:
            app_name: nom de l'app (ex: "anonymizer", "detector")
            task: tâche spécifique (ex: "face_detection", "object_detection")

        Returns:
            Liste des modèles avec leurs métadonnées
        """
        if app_name not in self.registry.get("app_models_mapping", {}):
            return []

        app_mapping = self.registry["app_models_mapping"][app_name]

        # Si une tâche spécifique est demandée
        if task and task in app_mapping:
            model_ids = app_mapping[task]
        else:
            # Tous les modèles de l'app
            model_ids = []
            for task_models in app_mapping.values():
                model_ids.extend(task_models)

        # Récupérer les infos complètes
        models = []
        for model_id in model_ids:
            if model_id in self.registry["models"]:
                model = self.registry["models"][model_id].copy()
                model["available"] = model.get("downloaded", False)
                models.append(model)

        return models

    def get_downloaded_models_for_app(self, app_name: str, task: Optional[str] = None) -> List[Dict]:
        """Récupère uniquement les modèles téléchargés pour une app"""
        all_models = self.get_models_for_app(app_name, task)
        return [m for m in all_models if m.get("downloaded", False)]

    def download_model(self, model_id: str, force: bool = False) -> Dict:
        """Télécharge un modèle"""
        if model_id not in self.registry["models"]:
            return {"status": "error", "message": f"Model {model_id} not found in registry"}

        model = self.registry["models"][model_id]

        if model.get("downloaded") and not force:
            return {
                "status": "already_downloaded",
                "path": model.get("local_path")
            }

        try:
            # Créer le dossier de destination
            model_dir = self.download_path / model_id
            model_dir.mkdir(parents=True, exist_ok=True)

            if model["source"] == "huggingface":
                # Téléchargement depuis HuggingFace
                local_path = snapshot_download(
                    repo_id=model["repo"],
                    local_dir=str(model_dir),
                    local_dir_use_symlinks=False
                )

            elif model["source"] == "github":
                # Téléchargement direct depuis URL
                response = requests.get(model["url"], stream=True)
                file_path = model_dir / Path(model["url"]).name

                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                local_path = str(file_path)

            # Mettre à jour le registre
            self.registry["models"][model_id]["downloaded"] = True
            self.registry["models"][model_id]["local_path"] = str(model_dir)
            self.save_registry()

            return {
                "status": "success",
                "path": local_path,
                "model_id": model_id
            }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }

    def populate_app_dropdown(self, app_name: str, task: Optional[str] = None) -> List[Dict]:
        """
        Génère les options pour le menu déroulant d'une application

        Returns:
            Liste de dictionnaires {id, name, downloaded, size_gb}
        """
        models = self.get_models_for_app(app_name, task)

        dropdown_options = []
        for model in models:
            dropdown_options.append({
                "value": model["id"],
                "label": f"{model['name']} {'✓' if model.get('downloaded') else '⬇'}",
                "downloaded": model.get("downloaded", False),
                "size": model.get("size_gb", 0),
                "performance": model.get("performance", {})
            })

        # Trier : téléchargés en premier
        dropdown_options.sort(key=lambda x: (not x["downloaded"], x["label"]))

        return dropdown_options

    def add_model_to_registry(self, model_data: Dict, compatible_apps: List[str]):
        """Ajoute un nouveau modèle au registre"""
        model_id = model_data["id"]

        # Ajouter le modèle
        self.registry["models"][model_id] = model_data

        # Ajouter aux apps compatibles
        for app in compatible_apps:
            if app not in self.registry["app_models_mapping"]:
                self.registry["app_models_mapping"][app] = {}

            # Déterminer la tâche (simplifié ici)
            task = model_data.get("category", "default")
            if task not in self.registry["app_models_mapping"][app]:
                self.registry["app_models_mapping"][app][task] = []

            if model_id not in self.registry["app_models_mapping"][app][task]:
                self.registry["app_models_mapping"][app][task].append(model_id)

        self.save_registry()

    def discover_new_models(self, category=None):
        """Découvre de nouveaux modèles depuis HuggingFace"""
        # Mapping des catégories WAMA vers tâches HF
        task_mapping = {
            "text-to-image": "text-to-image",
            "speech-to-text": "automatic-speech-recognition",
            "text-to-speech": "text-to-speech",
            "object-detection": "object-detection",
            "segmentation": "image-segmentation"
        }

        new_models = []
        for wama_cat, hf_task in task_mapping.items():
            if category and category != wama_cat:
                continue

            # Recherche sur HF avec filtres
            models = list_models(
                task=hf_task,
                sort="downloads",
                direction=-1,
                limit=20,
                library="transformers"  # ou "diffusers", etc.
            )

            for model in models:
                if not self.is_in_registry(model.modelId):
                    new_models.append({
                        "id": self.generate_id(model.modelId),
                        "name": model.modelId,
                        "category": wama_cat,
                        "source": "huggingface",
                        "repo": model.modelId,
                        "downloads": model.downloads,
                        "last_updated": model.lastModified.isoformat()
                    })

        return new_models

    def verify_model_links(self):
        """Vérifie que tous les liens de téléchargement sont valides"""
        results = {"valid": [], "broken": []}

        for model in self.registry["models"]:
            try:
                if model["source"] == "huggingface":
                    # Vérifier l'existence du repo HF
                    info = self.hf_api.model_info(model["repo"])
                    results["valid"].append(model["id"])
                else:
                    # Vérifier l'URL directe
                    response = requests.head(model["url"], timeout=5)
                    if response.status_code == 200:
                        results["valid"].append(model["id"])
                    else:
                        results["broken"].append(model["id"])
            except:
                results["broken"].append(model["id"])

        return results

    def suggest_updates(self):
        """Propose des mises à jour pour les modèles téléchargés"""
        suggestions = []

        for model in self.registry["models"]:
            if not model.get("downloaded"):
                continue

            if model["source"] == "huggingface":
                info = self.hf_api.model_info(model["repo"])
                if info.lastModified.isoformat() > model["last_updated"]:
                    suggestions.append({
                        "id": model["id"],
                        "current_version": model["last_updated"],
                        "new_version": info.lastModified.isoformat(),
                        "size": model.get("size_gb", "unknown")
                    })

        return suggestions

    def auto_update(self, model_id):
        """Met à jour automatiquement un modèle"""
        return self.download_model(model_id, force=True)