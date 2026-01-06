"""
Système d'analyse UI multi-modèles pour extraction de fonctionnalités WAMA
Supporte Mode 1 (parallèle) et Mode 2 (séquentiel)
Optimisé pour RTX 4090 (24GB VRAM)
"""

import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import subprocess
import concurrent.futures
from PIL import Image
import base64
import io
import torch


# ============================================================================
# CONFIGURATION DES MODÈLES
# ============================================================================

@dataclass
class ModelConfig:
    """Configuration d'un modèle d'analyse UI"""
    name: str
    model_id: str  # ID Ollama
    vram_required: int  # GB
    specialty: str  # Spécialité du modèle
    prompt_template: str


# Modèles optimisés pour analyse UI
VISION_MODELS = {
    "llava": ModelConfig(
        name="LLaVA 34B",
        model_id="llava:34b",
        vram_required=12,
        specialty="Vision générale + raisonnement",
        prompt_template="""You are an expert UI/UX analyst. Analyze this screenshot of WAMA (Web App for Media Automation) interface.

Extract ALL visible features and functionalities. For each feature:
1. Unique ID (snake_case)
2. Feature name
3. Detailed description
4. Location in UI
5. User action required
6. Expected outcome

Be exhaustive. Even small UI elements can represent important features.

Return ONLY valid JSON:
{
  "features": [
    {
      "id": "feature_id",
      "name": "Feature Name",
      "description": "What it does",
      "ui_location": "Where in the interface",
      "user_action": "How user interacts",
      "expected_outcome": "What happens"
    }
  ]
}"""
    ),

    "qwen2_vl": ModelConfig(
        name="Qwen2.5-VL 7B",
        model_id="qwen2.5vl:7b",
        vram_required=6,
        specialty="Vision spécialisée UI/texte (version améliorée)",
        prompt_template="""Analyze this web application screenshot. Focus on:
- Interactive elements (buttons, dropdowns, inputs)
- Navigation structure
- Data display components
- Upload/download mechanisms
- Processing/queue indicators

List every functionality you can identify. Format as JSON:
{
  "features": [
    {"id": "...", "name": "...", "description": "...", "type": "button|input|display|..."}
  ]
}"""
    ),

    "llama_vision": ModelConfig(
        name="Llama 3.2 Vision 11B",
        model_id="llama3.2-vision:11b",
        vram_required=8,
        specialty="Vision multimodale Meta - Excellent pour UI",
        prompt_template="""You are analyzing a media automation web application interface.

Identify ALL features visible in this screenshot:
- Media processing operations (blur, transcribe, generate, upscale, etc.)
- File management features (upload, download, delete)
- Queue/workflow management (status, progress, history)
- Settings and configuration options
- Preview and output features
- Any buttons, menus, or interactive elements

Provide comprehensive JSON list:
{
  "features": [
    {"id": "...", "name": "...", "category": "processing|file|queue|settings|output", "description": "..."}
  ]
}"""
    ),
}


# Modèle de fusion
FUSION_MODEL = ModelConfig(
    name="Llama 3.1 70B",
    model_id="llama3.1:70b",
    vram_required=40,
    specialty="Fusion et raisonnement",
    prompt_template=""  # Défini dynamiquement
)

# Modèle de critique (Mode 2)
CRITIC_MODEL = ModelConfig(
    name="DeepSeek Coder 33B",
    model_id="deepseek-coder:33b",
    vram_required=20,
    specialty="Analyse critique et validation",
    prompt_template=""  # Défini dynamiquement
)


# ============================================================================
# CLASSE DE FEATURE
# ============================================================================

class FeatureCategory(Enum):
    PROCESSING = "processing"
    FILE_MANAGEMENT = "file_management"
    QUEUE = "queue"
    SETTINGS = "settings"
    OUTPUT = "output"
    NAVIGATION = "navigation"
    OTHER = "other"


@dataclass
class Feature:
    """Représentation d'une fonctionnalité"""
    id: str
    name: str
    description: str
    category: FeatureCategory = FeatureCategory.OTHER
    ui_location: str = ""
    user_action: str = ""
    expected_outcome: str = ""
    confidence: float = 1.0  # 0-1, basé sur le consensus
    detected_by: List[str] = field(default_factory=list)  # Quels modèles l'ont trouvée

    def to_dict(self) -> Dict:
        d = asdict(self)
        d['category'] = self.category.value
        return d


# ============================================================================
# GESTIONNAIRE OLLAMA
# ============================================================================

class OllamaManager:
    """Gère les interactions avec Ollama"""

    def __init__(self):
        self.check_ollama_installed()
        self.available_models = self.list_available_models()

    def check_ollama_installed(self):
        """Vérifie qu'Ollama est installé"""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                check=True,
                text=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError(
                "Ollama n'est pas installé. "
                "Installe-le depuis https://ollama.ai ou via: curl https://ollama.ai/install.sh | sh"
            )

    def list_available_models(self) -> List[str]:
        """Liste les modèles déjà téléchargés"""
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True
        )

        lines = result.stdout.strip().split('\n')[1:]  # Skip header
        return [line.split()[0] for line in lines if line]

    def pull_model(self, model_id: str):
        """Télécharge un modèle si pas déjà présent"""
        if model_id not in self.available_models:
            print(f"📥 Téléchargement de {model_id}...")
            subprocess.run(["ollama", "pull", model_id], check=True)
            self.available_models.append(model_id)

    def analyze_image(self, model_id: str, image_path: Path, prompt: str) -> str:
        """Analyse une image avec un modèle vision"""
        # Encode l'image en base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Crée le payload pour Ollama
        import requests

        # IMPORTANT: Bypass proxy pour localhost
        session = requests.Session()
        session.trust_env = False  # Ignore les variables d'environnement proxy

        response = session.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model_id,
                "prompt": prompt,
                "images": [image_data],
                "stream": False,
                "options": {
                    "temperature": 0.3,  # Moins de créativité, plus de précision
                    "num_predict": 2048
                }
            },
            timeout=180  # 3 minutes max par image
        )

        if response.status_code == 200:
            return response.json()["response"]
        else:
            raise RuntimeError(f"Erreur Ollama: {response.text}")

    def generate_text(self, model_id: str, prompt: str) -> str:
        """Génère du texte avec un modèle LLM standard"""
        import requests

        # IMPORTANT: Bypass proxy pour localhost
        session = requests.Session()
        session.trust_env = False  # Ignore les variables d'environnement proxy

        response = session.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model_id,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 4096
                }
            },
            timeout=300
        )

        if response.status_code == 200:
            return response.json()["response"]
        else:
            raise RuntimeError(f"Erreur Ollama: {response.text}")


# ============================================================================
# MODE 1 : ANALYSE PARALLÈLE + FUSION
# ============================================================================

class ParallelAnalyzer:
    """Analyse UI avec plusieurs modèles en parallèle puis fusionne"""

    def __init__(self, models: List[str] = None):
        """
        Args:
            models: Liste des modèles à utiliser (défaut: tous)
        """
        self.ollama = OllamaManager()

        if models is None:
            self.models = list(VISION_MODELS.keys())
        else:
            self.models = models

        # Vérifie/télécharge les modèles
        for model_key in self.models:
            model = VISION_MODELS[model_key]
            self.ollama.pull_model(model.model_id)

        # Modèle de fusion
        self.ollama.pull_model(FUSION_MODEL.model_id)

    def analyze_screenshot(self, image_path: Path) -> Dict[str, List[Feature]]:
        """
        Analyse un screenshot avec tous les modèles en parallèle

        Returns:
            Dict mapping model_name → list of features
        """
        print(f"\n🔍 Analyse de {image_path.name} avec {len(self.models)} modèles...")

        results = {}

        def analyze_with_model(model_key: str) -> Tuple[str, List[Feature]]:
            """Fonction pour thread"""
            model = VISION_MODELS[model_key]
            print(f"   🤖 {model.name} : démarrage...")

            start = time.time()

            try:
                response = self.ollama.analyze_image(
                    model.model_id,
                    image_path,
                    model.prompt_template
                )

                # Parse JSON
                features = self._parse_response(response, model_key)

                duration = time.time() - start
                print(f"   ✅ {model.name} : {len(features)} features ({duration:.1f}s)")

                return model_key, features

            except Exception as e:
                print(f"   ❌ {model.name} : erreur - {e}")
                return model_key, []

        # Analyse en parallèle avec ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.models)) as executor:
            futures = [executor.submit(analyze_with_model, mk) for mk in self.models]

            for future in concurrent.futures.as_completed(futures):
                model_key, features = future.result()
                results[model_key] = features

        return results

    def _parse_response(self, response: str, model_key: str) -> List[Feature]:
        """Parse la réponse JSON d'un modèle"""
        import re

        # Extrait le JSON
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            return []

        try:
            data = json.loads(json_match.group())
            features = []

            for f_data in data.get("features", []):
                # Normalise les champs
                category = FeatureCategory.OTHER
                if "category" in f_data:
                    try:
                        category = FeatureCategory(f_data["category"])
                    except ValueError:
                        pass
                elif "type" in f_data:
                    # Mapping des types
                    type_map = {
                        "processing": FeatureCategory.PROCESSING,
                        "file": FeatureCategory.FILE_MANAGEMENT,
                        "queue": FeatureCategory.QUEUE,
                        "settings": FeatureCategory.SETTINGS,
                        "output": FeatureCategory.OUTPUT
                    }
                    category = type_map.get(f_data["type"], FeatureCategory.OTHER)

                feature = Feature(
                    id=f_data.get("id", "unknown"),
                    name=f_data.get("name", "Unknown"),
                    description=f_data.get("description", ""),
                    category=category,
                    ui_location=f_data.get("ui_location", ""),
                    user_action=f_data.get("user_action", ""),
                    expected_outcome=f_data.get("expected_outcome", ""),
                    detected_by=[model_key]
                )
                features.append(feature)

            return features

        except json.JSONDecodeError:
            return []

    def fuse_results(self, all_results: Dict[str, List[Feature]]) -> List[Feature]:
        """
        Fusionne les résultats de tous les modèles
        Utilise Llama 3.1 70B pour la fusion intelligente
        """
        print(f"\n🔗 Fusion des résultats de {len(all_results)} modèles...")

        # Prépare les données pour le prompt de fusion
        fusion_data = {}
        for model_key, features in all_results.items():
            model_name = VISION_MODELS[model_key].name
            fusion_data[model_name] = [f.to_dict() for f in features]

        prompt = f"""You are an expert data analyst. You have received feature lists from {len(all_results)} different AI models analyzing the same UI screenshot.

Your task: Create a SINGLE, COMPREHENSIVE, DEDUPLICATED list of all unique features.

INPUT DATA:
{json.dumps(fusion_data, indent=2)}

RULES:
1. Merge duplicate features (same functionality, different wording)
2. Keep the best description from all versions
3. Assign confidence score based on how many models detected it:
   - 1 model: 0.5 confidence
   - 2 models: 0.75 confidence  
   - 3+ models: 1.0 confidence
4. Preserve detected_by list
5. Choose most accurate category

OUTPUT FORMAT (JSON only):
{{
  "fused_features": [
    {{
      "id": "unique_id",
      "name": "Best name",
      "description": "Most complete description",
      "category": "processing|file_management|queue|settings|output|navigation|other",
      "ui_location": "Merged location info",
      "user_action": "How user interacts",
      "expected_outcome": "What happens",
      "confidence": 0.5-1.0,
      "detected_by": ["model1", "model2"]
    }}
  ]
}}

Return ONLY the JSON, no explanation."""

        # Génère avec Llama 3.1 70B
        print("   🤖 Llama 3.1 70B : fusion en cours...")
        response = self.ollama.generate_text(FUSION_MODEL.model_id, prompt)

        # Parse
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())

            fused_features = []
            for f_data in data.get("fused_features", []):
                try:
                    category = FeatureCategory(f_data.get("category", "other"))
                except ValueError:
                    category = FeatureCategory.OTHER

                feature = Feature(
                    id=f_data["id"],
                    name=f_data["name"],
                    description=f_data["description"],
                    category=category,
                    ui_location=f_data.get("ui_location", ""),
                    user_action=f_data.get("user_action", ""),
                    expected_outcome=f_data.get("expected_outcome", ""),
                    confidence=f_data.get("confidence", 0.5),
                    detected_by=f_data.get("detected_by", [])
                )
                fused_features.append(feature)

            print(f"   ✅ Fusion terminée : {len(fused_features)} features uniques")
            return fused_features

        # Fallback: fusion simple si parsing échoue
        return self._simple_merge(all_results)

    def _simple_merge(self, all_results: Dict[str, List[Feature]]) -> List[Feature]:
        """Fusion simple basée sur similarité d'ID"""
        merged = {}

        for model_key, features in all_results.items():
            for feature in features:
                if feature.id in merged:
                    # Déjà vu, augmente confidence
                    merged[feature.id].confidence = min(1.0, merged[feature.id].confidence + 0.25)
                    merged[feature.id].detected_by.append(model_key)
                else:
                    merged[feature.id] = feature

        return list(merged.values())

    def analyze_multiple_screenshots(self, screenshots: List[Path]) -> List[Feature]:
        """Analyse plusieurs screenshots et fusionne tout"""
        all_features = []

        for screenshot in screenshots:
            # Analyse avec tous les modèles
            results = self.analyze_screenshot(screenshot)

            # Fusionne les résultats pour ce screenshot
            fused = self.fuse_results(results)

            all_features.extend(fused)

        # Déduplique entre screenshots
        print(f"\n🔗 Déduplication finale entre {len(screenshots)} screenshots...")
        final_features = self._deduplicate_across_screenshots(all_features)

        return final_features

    def _deduplicate_across_screenshots(self, features: List[Feature]) -> List[Feature]:
        """Déduplique les features vues dans plusieurs screenshots"""
        seen = {}

        for feature in features:
            if feature.id in seen:
                # Garde celle avec la meilleure confidence
                if feature.confidence > seen[feature.id].confidence:
                    seen[feature.id] = feature
            else:
                seen[feature.id] = feature

        return list(seen.values())


# ============================================================================
# MODE 2 : ANALYSE SÉQUENTIELLE + CRITIQUE
# ============================================================================

class SequentialAnalyzer:
    """Analyse UI puis critique/améliore avec un 2ème modèle"""

    def __init__(self, analyzer_model: str = "llava", critic_model: str = "deepseek-coder"):
        self.ollama = OllamaManager()

        # Modèle d'analyse initial
        self.analyzer = VISION_MODELS[analyzer_model]
        self.ollama.pull_model(self.analyzer.model_id)

        # Modèle critique
        self.critic = CRITIC_MODEL
        self.ollama.pull_model(self.critic.model_id)

    def analyze_screenshot(self, image_path: Path) -> List[Feature]:
        """Analyse un screenshot en 2 étapes"""
        print(f"\n🔍 Analyse de {image_path.name} en mode séquentiel...")

        # Étape 1: Analyse initiale
        print(f"   🤖 Étape 1: {self.analyzer.name}...")
        initial_response = self.ollama.analyze_image(
            self.analyzer.model_id,
            image_path,
            self.analyzer.prompt_template
        )

        initial_features = self._parse_response(initial_response)
        print(f"   ✅ {len(initial_features)} features initiales détectées")

        # Étape 2: Critique et enrichissement
        print(f"   🤖 Étape 2: {self.critic.name} (critique)...")
        final_features = self._critique_and_improve(initial_features, image_path)
        print(f"   ✅ {len(final_features)} features après critique")

        return final_features

    def _parse_response(self, response: str) -> List[Feature]:
        """Parse la réponse JSON"""
        import re

        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            return []

        try:
            data = json.loads(json_match.group())
            features = []

            for f_data in data.get("features", []):
                category = FeatureCategory.OTHER
                if "category" in f_data:
                    try:
                        category = FeatureCategory(f_data["category"])
                    except ValueError:
                        pass

                feature = Feature(
                    id=f_data.get("id", "unknown"),
                    name=f_data.get("name", "Unknown"),
                    description=f_data.get("description", ""),
                    category=category,
                    ui_location=f_data.get("ui_location", ""),
                    user_action=f_data.get("user_action", ""),
                    expected_outcome=f_data.get("expected_outcome", ""),
                    confidence=0.8  # Confidence initiale
                )
                features.append(feature)

            return features
        except json.JSONDecodeError:
            return []

    def _critique_and_improve(self, features: List[Feature], image_path: Path) -> List[Feature]:
        """Le modèle critique analyse et améliore la liste"""

        # Prépare les features pour le prompt
        features_json = json.dumps([f.to_dict() for f in features], indent=2)

        prompt = f"""You are an expert UI analyst performing a critical review.

INITIAL ANALYSIS from another AI:
{features_json}

Your tasks:
1. VALIDATE each feature:
   - Is it a real feature or a misinterpretation?
   - Is the description accurate?
   - Is it complete?

2. IDENTIFY MISSING features:
   - What obvious features were missed?
   - What small but important UI elements were overlooked?

3. IMPROVE existing features:
   - Better descriptions
   - More accurate categories
   - Better IDs

4. REMOVE false positives:
   - Not real features
   - Duplicate entries

OUTPUT FORMAT (JSON only):
{{
  "validated_features": [
    {{
      "id": "...",
      "name": "...",
      "description": "...",
      "category": "...",
      "ui_location": "...",
      "user_action": "...",
      "expected_outcome": "...",
      "validation_status": "approved|improved|new",
      "confidence": 0.0-1.0,
      "critique_note": "Why this validation decision"
    }}
  ],
  "removed_features": [
    {{"id": "...", "reason": "Why removed"}}
  ]
}}

Be thorough but fair. Return ONLY JSON."""

        response = self.ollama.generate_text(self.critic.model_id, prompt)

        # Parse
        import re
        json_match = re.search(r'\{.*\}', response, re.DOTALL)

        if json_match:
            data = json.loads(json_match.group())

            validated = []
            for f_data in data.get("validated_features", []):
                try:
                    category = FeatureCategory(f_data.get("category", "other"))
                except ValueError:
                    category = FeatureCategory.OTHER

                feature = Feature(
                    id=f_data["id"],
                    name=f_data["name"],
                    description=f_data["description"],
                    category=category,
                    ui_location=f_data.get("ui_location", ""),
                    user_action=f_data.get("user_action", ""),
                    expected_outcome=f_data.get("expected_outcome", ""),
                    confidence=f_data.get("confidence", 0.9)
                )
                validated.append(feature)

            # Affiche les features supprimées
            removed = data.get("removed_features", [])
            if removed:
                print(f"   ℹ️  {len(removed)} features supprimées par critique")
                for r in removed[:3]:  # Affiche les 3 premières
                    print(f"      - {r['id']}: {r['reason']}")

            return validated

        # Fallback
        return features

    def analyze_multiple_screenshots(self, screenshots: List[Path]) -> List[Feature]:
        """Analyse plusieurs screenshots"""
        all_features = []

        for screenshot in screenshots:
            features = self.analyze_screenshot(screenshot)
            all_features.extend(features)

        # Déduplique
        seen = {}
        for feature in all_features:
            if feature.id in seen:
                if feature.confidence > seen[feature.id].confidence:
                    seen[feature.id] = feature
            else:
                seen[feature.id] = feature

        return list(seen.values())


# ============================================================================
# SCRIPT PRINCIPAL
# ============================================================================

class WAMAFeatureExtractor:
    """Extracteur de fonctionnalités WAMA"""

    def __init__(self, mode: str = "parallel", output_dir: Path = None):
        """
        Args:
            mode: "parallel" ou "sequential"
            output_dir: Répertoire de sortie
        """
        self.mode = mode
        self.output_dir = output_dir or Path("wama_features_output")
        self.output_dir.mkdir(exist_ok=True)

        if mode == "parallel":
            self.analyzer = ParallelAnalyzer()
        elif mode == "sequential":
            self.analyzer = SequentialAnalyzer()
        else:
            raise ValueError(f"Mode inconnu: {mode}. Utilise 'parallel' ou 'sequential'")

    def extract_features(self, screenshots_dir: Path) -> List[Feature]:
        """Extrait les fonctionnalités depuis les screenshots"""

        # Trouve tous les screenshots
        screenshots = list(screenshots_dir.glob("*.png")) + \
                     list(screenshots_dir.glob("*.jpg")) + \
                     list(screenshots_dir.glob("*.jpeg"))

        if not screenshots:
            raise ValueError(f"Aucun screenshot trouvé dans {screenshots_dir}")

        print("=" * 70)
        print(f"🚀 EXTRACTION DE FONCTIONNALITÉS WAMA - MODE {self.mode.upper()}")
        print("=" * 70)
        print(f"Screenshots: {len(screenshots)}")
        print(f"Output: {self.output_dir}")
        print("=" * 70)

        start_time = time.time()

        # Analyse
        features = self.analyzer.analyze_multiple_screenshots(screenshots)

        duration = time.time() - start_time

        # Sauvegarde
        self._save_results(features, duration)

        # Rapport
        self._print_summary(features, duration)

        return features

    def _save_results(self, features: List[Feature], duration: float):
        """Sauvegarde les résultats"""

        # JSON complet
        output_file = self.output_dir / "features_extracted.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump({
                "mode": self.mode,
                "total_features": len(features),
                "extraction_time_seconds": duration,
                "features": [f.to_dict() for f in features]
            }, f, indent=2, ensure_ascii=False)

        print(f"\n💾 Résultats sauvegardés dans {output_file}")

        # CSV pour faciliter la révision
        csv_file = self.output_dir / "features_extracted.csv"
        with open(csv_file, 'w', encoding='utf-8') as f:
            f.write("ID,Name,Category,Confidence,Description,UI Location\n")
            for feat in sorted(features, key=lambda x: x.confidence, reverse=True):
                f.write(f'"{feat.id}","{feat.name}","{feat.category.value}",{feat.confidence},"{feat.description}","{feat.ui_location}"\n')

        print(f"💾 CSV sauvegardé dans {csv_file}")

        # Rapport Markdown
        md_file = self.output_dir / "FEATURES_REPORT.md"
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(f"# WAMA - Features Extracted ({self.mode.upper()} mode)\n\n")
            f.write(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Duration**: {duration:.1f}s\n")
            f.write(f"**Total Features**: {len(features)}\n\n")

            # Par catégorie
            from collections import defaultdict
            by_category = defaultdict(list)
            for feat in features:
                by_category[feat.category].append(feat)

            for category in FeatureCategory:
                feats = by_category[category]
                if feats:
                    f.write(f"## {category.value.upper().replace('_', ' ')} ({len(feats)})\n\n")
                    for feat in sorted(feats, key=lambda x: x.confidence, reverse=True):
                        conf_emoji = "🟢" if feat.confidence >= 0.8 else "🟡" if feat.confidence >= 0.5 else "🔴"
                        f.write(f"### {conf_emoji} {feat.name} (`{feat.id}`)\n\n")
                        f.write(f"**Confidence**: {feat.confidence:.2f}\n\n")
                        f.write(f"**Description**: {feat.description}\n\n")
                        if feat.ui_location:
                            f.write(f"**Location**: {feat.ui_location}\n\n")
                        if feat.user_action:
                            f.write(f"**User Action**: {feat.user_action}\n\n")
                        if feat.expected_outcome:
                            f.write(f"**Expected Outcome**: {feat.expected_outcome}\n\n")
                        if self.mode == "parallel" and feat.detected_by:
                            f.write(f"**Detected By**: {', '.join(feat.detected_by)}\n\n")
                        f.write("---\n\n")

        print(f"📄 Rapport Markdown dans {md_file}")

    def _print_summary(self, features: List[Feature], duration: float):
        """Affiche le résumé"""
        print("\n" + "=" * 70)
        print("✨ EXTRACTION TERMINÉE")
        print("=" * 70)
        print(f"Mode: {self.mode.upper()}")
        print(f"Temps: {duration:.1f}s ({duration/60:.1f} min)")
        print(f"Features totales: {len(features)}")

        # Par catégorie
        from collections import Counter
        category_counts = Counter(f.category for f in features)
        print("\nPar catégorie:")
        for category, count in category_counts.most_common():
            print(f"  • {category.value}: {count}")

        # Par confidence
        high_conf = sum(1 for f in features if f.confidence >= 0.8)
        med_conf = sum(1 for f in features if 0.5 <= f.confidence < 0.8)
        low_conf = sum(1 for f in features if f.confidence < 0.5)

        print("\nPar confidence:")
        print(f"  🟢 Haute (≥0.8): {high_conf}")
        print(f"  🟡 Moyenne (0.5-0.8): {med_conf}")
        print(f"  🔴 Basse (<0.5): {low_conf}")

        if self.mode == "parallel":
            # Consensus
            detected_by_all = sum(1 for f in features if len(f.detected_by) >= 3)
            print(f"\n🎯 Consensus (3+ modèles): {detected_by_all} features")

        print("=" * 70)
        print(f"\n📁 Fichiers générés dans: {self.output_dir}")
        print("  • features_extracted.json (format complet)")
        print("  • features_extracted.csv (pour révision Excel)")
        print("  • FEATURES_REPORT.md (rapport lisible)")
        print("\n💡 Prochaine étape: Révise manuellement les features et ajoute les manquantes")
        print("=" * 70)


# ============================================================================
# CLI
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extraction de fonctionnalités WAMA depuis screenshots UI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Mode parallèle (recommandé avec RTX 4090)
  python wama_feature_extractor.py --screenshots ui_screenshots/ --mode parallel
  
  # Mode séquentiel (plus rapide)
  python wama_feature_extractor.py --screenshots ui_screenshots/ --mode sequential
  
  # Avec output personnalisé
  python wama_feature_extractor.py --screenshots ui/ --output results/ --mode parallel
        """
    )

    parser.add_argument(
        "--screenshots",
        type=Path,
        required=True,
        help="Répertoire contenant les screenshots UI"
    )

    parser.add_argument(
        "--mode",
        choices=["parallel", "sequential"],
        default="parallel",
        help="Mode d'analyse (défaut: parallel)"
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("wama_features_output"),
        help="Répertoire de sortie (défaut: wama_features_output)"
    )

    args = parser.parse_args()

    # Vérifie que le répertoire existe
    if not args.screenshots.exists():
        print(f"❌ Erreur: Le répertoire {args.screenshots} n'existe pas")
        return

    # Lance l'extraction
    extractor = WAMAFeatureExtractor(mode=args.mode, output_dir=args.output)
    features = extractor.extract_features(args.screenshots)

    print(f"\n✅ {len(features)} fonctionnalités extraites avec succès !")


if __name__ == "__main__":
    main()