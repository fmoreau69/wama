"""LocateAnything-3B (NVIDIA) — détection open-vocabulary par prompt TEXTE, au contrat commun.

ROADMAP §17 étape 1→2. Écrit le 2026-09-08 après une mesure qui débloque la question que le §17
laissait ouverte : *« backend officiel = transformers 4.57.1 + trust_remote_code (venv_linux à
4.57.6 — écart mineur, TESTER AVANT de créer un venv isolé) »*. Test fait — `AutoConfig` résout
`LocateAnythingConfig` sur le snapshot local avec le venv actuel : **aucun venv isolé n'est
nécessaire**. C'est le SEUL des six modèles prospectés sans backend qui soit chargeable ici ;
les cinq autres exigent transformers 5.x ou un toolkit absent (NeMo, fastvideo).

CE QUE CE FICHIER N'EST PAS. Il ne réimplémente pas l'inférence : la classe officielle NVIDIA est
recopiée verbatim dans `scripts/locate_anything_worker.py` (« ne pas modifier »), et ce backend
l'ADAPTE au contrat WAMA — chargement, cycle de vie, VRAM déclarée, sortie normalisée. C'est la
même frontière que pour les autres moteurs vendorisés : le code tiers d'un côté, l'adaptateur de
l'autre.

⚠⚠ LICENCE NVIDIA NON COMMERCIALE (+ Qwen Research sur le LLM interne) : recherche Lescot
d'accord, **EXCLU de tout livrable partenaire ou valorisation** (ROADMAP §17, LICENSING §2). Le
catalogue porte la licence — c'est lui qui doit filtrer, jamais la mémoire de quelqu'un.

⚠ LATENCE VLM (~1,5–7 s/image) : **jamais image par image sur une vidéo**. Usages viables selon
le §17 — image unique, keyframes fenêtrés, et l'auto-étiquetage de classes rares vers des YOLO
spécialisés (le vrai goulot des modèles faces/plaques).

⚠ NON ÉPROUVÉ DE BOUT EN BOUT : le chargement réel demande ~9 Go de VRAM, et aucune charge GPU
n'est lancée depuis cette session (crashs hôte, cf. INFRA_WSL_VS_WINDOWS). Ce qui EST vérifié :
la résolution du modèle vers ce backend, la disponibilité déclarative, la présence des poids, et
la résolution de la config par transformers. Ce qui ne l'est pas : `load()` et `process()` en
conditions réelles. *Un backend qui n'a jamais tourné se dit tel quel.*
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)

#: Dépôt HF servi — même graphie que la clé de catalogue (`huggingface:<hf_id>`).
HF_ID = 'nvidia/LocateAnything-3B'

#: Tâches du modèle, telles que la classe officielle les expose (`LocateAnythingWorker`).
TACHES = ('detect', 'ground_single', 'ground_multi', 'ground_text', 'detect_text',
          'ground_gui', 'point')


def _dossier_poids() -> Path:
    """Dossier de famille des poids — DÉCLARÉ dans `settings.MODEL_PATHS`, jamais deviné."""
    from django.conf import settings
    declare = (settings.MODEL_PATHS.get('vision') or {}).get('locate_anything')
    return Path(declare) if declare else (
        Path(settings.AI_MODELS_DIR) / 'models' / 'vision' / 'locate-anything')


class LocateAnythingBackend(BaseModelBackend):
    """Détection open-vocabulary : l'utilisateur décrit ce qu'il cherche, le modèle le localise."""

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'transformers'

    #: Modèle SERVI — le DÉPARTAGE, puisque `transformers` est piloté par 6 backends désormais.
    #: ⚠ Clé en LITTÉRAL : l'inventaire lit par AST, sans importer (une clé portée par la
    #: constante `HF_ID` serait invisible — défaut mesuré le 07/09 sur table-transformer).
    #: ⚠ Le segment attendu est celui qui suit `<source>:` dans `model_key`, donc `org/nom`
    #: entier pour un modèle prospecté (`huggingface:nvidia/LocateAnything-3B`).
    SUPPORTED_MODELS = {'nvidia/LocateAnything-3B': {}}

    name = 'locate_anything'
    display_name = 'LocateAnything-3B (NVIDIA)'
    description = ("LocateAnything-3B — détection open-vocabulary : décrire en langage naturel "
                   "ce qu'on cherche, le modèle rend les boîtes. Complément de YOLO/SAM3, pas "
                   "remplaçant. ⚠ Licence NON COMMERCIALE (recherche seulement).")
    description_long = (
        "LocateAnything-3B (NVIDIA) : modèle vision-langage qui GÉNÈRE les boîtes englobantes "
        "en tokens plutôt que de les régresser — on lui décrit une catégorie libre ou une "
        "expression référentielle (« l'écran allumé au fond »), il la localise. Il couvre aussi "
        "la détection de texte de scène et le pointage. Là où YOLO exige des classes apprises et "
        "SAM3 un point ou une boîte d'amorce, celui-ci part du LANGAGE. "
        "En contrepartie il est LENT (~1,5 à 7 s par image) : à réserver aux images uniques, aux "
        "images-clés d'une vidéo, ou à l'étiquetage automatique de classes rares pour entraîner "
        "un détecteur spécialisé. ⚠ Licence NVIDIA non commerciale : usage recherche uniquement."
    )

    # Dépendances DÉCLARATIVES — `is_available()` en dérive (find_spec, sans import réel).
    REQUIRED_PACKAGES = ['transformers', 'torch', 'PIL']
    PIP_PACKAGES = ['transformers', 'torch', 'pillow']

    #: ~8 Go de poids BF16 + activations. Mesuré au catalogue : 7,3 Go sur disque, 9,4 estimés.
    recommended_vram_gb = 9.4
    min_vram_gb = 8

    def __init__(self):
        super().__init__()
        self._worker = None
        self._current_model = None

    # ── Cycle de vie ────────────────────────────────────────────────────────────────
    def load(self, model: Optional[str] = None) -> bool:
        """Charge le worker officiel. `model` est ignoré : ce backend ne sert qu'un dépôt.

        Les poids sont résolus par la 3ᵉ voie (`poids_locaux`) : un CHEMIN local, jamais une
        mutation d'environnement — la règle du socle HF (ROADMAP §5b). C'est déjà ce que fait le
        PoC, on ne réinvente pas son chemin.
        """
        if self._worker is not None:
            return True
        try:
            import sys

            import torch
            from django.conf import settings

            from wama.common.utils.hf_weights import poids_locaux

            # La classe d'inférence est le code OFFICIEL, gardé verbatim hors du paquet backends.
            racine = Path(settings.BASE_DIR) / 'scripts'
            if str(racine) not in sys.path:
                sys.path.insert(0, str(racine))
            from locate_anything_worker import LocateAnythingWorker

            chemin = poids_locaux(HF_ID, _dossier_poids())
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            dtype = torch.bfloat16 if device == 'cuda' else torch.float32
            logger.info('[LocateAnything] chargement depuis %s sur %s', chemin, device)
            self._worker = LocateAnythingWorker(chemin, device=device, dtype=dtype)
            self._current_model = HF_ID
            self._loaded = True
            return True
        except Exception as e:
            logger.error('[LocateAnything] chargement impossible : %s', e, exc_info=True)
            self._worker = None
            self._loaded = False
            return False

    @property
    def is_loaded(self) -> bool:
        return self._worker is not None

    def unload(self) -> None:
        self._worker = None
        self._current_model = None
        self._loaded = False
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # ── Verbe métier ────────────────────────────────────────────────────────────────
    def process(self, image_path: str = None, prompt: str = '', task: str = 'detect',
                generation_mode: str = 'hybrid', **kwargs) -> dict:
        """Localise ce que `prompt` décrit dans `image_path`.

        Rend la forme NORMALISÉE que la brique commune de détection attendra (ROADMAP §17
        étape 2) : `{'boxes': [{'x1','y1','x2','y2','label'}], 'answer': <texte brut>}`.
        Les coordonnées sont en PIXELS de l'image d'origine — le modèle, lui, raisonne en
        millièmes ; la conversion vit dans la classe officielle (`parse_boxes`), pas ici.

        ⚠ `prompt` est attendu en ANGLAIS (le modèle y est entraîné). La traduction éventuelle
        est du ressort de la pipeline de prompts commune (`PROMPT_TARGETS`), pas d'un backend.
        """
        if not image_path:
            raise ValueError('LocateAnything : `image_path` est requis')
        if task not in TACHES:
            raise ValueError(f'LocateAnything : tâche inconnue {task!r} — parmi {TACHES}')
        if not self.load():
            raise RuntimeError('LocateAnything : modèle non chargé')

        from PIL import Image

        image = Image.open(image_path).convert('RGB')
        if task == 'detect':
            categories = [c.strip() for c in (prompt or '').split(',') if c.strip()]
            if not categories:
                raise ValueError('LocateAnything : `prompt` vide — décrire ce qu’on cherche')
            res = self._worker.detect(image, categories, generation_mode=generation_mode,
                                      verbose=False)
        else:
            res = getattr(self._worker, task)(image, prompt, generation_mode=generation_mode,
                                              verbose=False)

        texte = res.get('answer') or ''
        boites = self._worker.parse_boxes(texte, image.width, image.height)
        return {'boxes': boites, 'answer': texte, 'task': task}

    # ── Capacités déclarées ─────────────────────────────────────────────────────────
    @classmethod
    def taches(cls) -> List[str]:
        """Tâches exposées — lues par l'UI plutôt que recopiées dans un gabarit."""
        return list(TACHES)
