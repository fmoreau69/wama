import subprocess
import json
from pathlib import Path
from typing import List, Dict, Optional


class OllamaConnector:
    """Connecteur pour intégrer les modèles Ollama dans WAMA"""

    def __init__(self):
        self.ollama_available = self._check_ollama_installed()
        self.ollama_models_path = self._get_ollama_models_path()

    def _check_ollama_installed(self) -> bool:
        """Vérifie si Ollama est installé"""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _get_ollama_models_path(self) -> Optional[Path]:
        """Récupère le chemin de stockage des modèles Ollama"""
        # Vérifier la variable d'environnement
        import os
        custom_path = os.getenv('OLLAMA_MODELS')

        if custom_path:
            return Path(custom_path)

        # Chemins par défaut selon l'OS
        if os.name == 'nt':  # Windows
            return Path.home() / '.ollama' / 'models'
        else:  # macOS/Linux
            return Path.home() / '.ollama' / 'models'

    def list_installed_models(self) -> List[Dict]:
        """Liste tous les modèles Ollama installés"""
        if not self.ollama_available:
            return []

        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )

            models = []
            lines = result.stdout.strip().split('\n')[1:]  # Skip header

            for line in lines:
                parts = line.split()
                if len(parts) >= 3:
                    name = parts[0]
                    size = parts[2]

                    models.append({
                        "ollama_model_name": name,
                        "id": name.replace(':', '-'),
                        "name": name,
                        "size": size,
                        "downloaded": True,
                        "managed_by": "ollama",
                        "source": "ollama"
                    })

            return models

        except Exception as e:
            print(f"Error listing Ollama models: {e}")
            return []

    def get_model_info(self, model_name: str) -> Optional[Dict]:
        """Récupère les infos détaillées d'un modèle Ollama"""
        try:
            result = subprocess.run(
                ["ollama", "show", model_name, "--modelfile"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                # Parser le modelfile pour extraire les infos
                modelfile = result.stdout

                return {
                    "modelfile": modelfile,
                    "available": True
                }

            return None

        except Exception as e:
            print(f"Error getting model info: {e}")
            return None

    def pull_model(self, model_name: str) -> Dict:
        """Télécharge un modèle via Ollama"""
        try:
            # Lancer ollama pull en subprocess
            process = subprocess.Popen(
                ["ollama", "pull", model_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            stdout, stderr = process.communicate(timeout=3600)  # 1h timeout

            if process.returncode == 0:
                return {
                    "status": "success",
                    "message": f"Model {model_name} downloaded successfully"
                }
            else:
                return {
                    "status": "error",
                    "message": stderr
                }

        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }

    def remove_model(self, model_name: str) -> Dict:
        """Supprime un modèle Ollama"""
        try:
            result = subprocess.run(
                ["ollama", "rm", model_name],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return {"status": "success"}
            else:
                return {"status": "error", "message": result.stderr}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def search_available_models(self) -> List[Dict]:
        """
        Recherche les modèles disponibles sur Ollama library
        Note: Ollama n'a pas d'API de recherche native,
        donc on pourrait scraper ou maintenir une liste manuelle
        """
        # Liste manuelle des modèles populaires (à mettre à jour)
        popular_models = [
            {"name": "llama3.2", "category": "language-model"},
            {"name": "llama3.2:latest", "category": "language-model"},
            {"name": "mistral", "category": "language-model"},
            {"name": "mixtral", "category": "language-model"},
            {"name": "llava", "category": "vision-language-model"},
            {"name": "llava:13b", "category": "vision-language-model"},
            {"name": "codellama", "category": "code-model"},
            {"name": "phi3", "category": "language-model"},
        ]

        return popular_models
