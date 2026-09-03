"""
Table Transformer (Microsoft, DETR) — détection de tableaux + reconstruction de structure.

B2 « backends de modèles connus mais manquants » (GO Fabien 02/09, ROADMAP §23.5 étage 2) :
les DEUX modèles étaient INSTALLÉS et catalogués (628/629) sans backend — « CONNU :
architecture native transformers » (handoff installs). Ce fichier les rend lançables.

⚠ Ce n'est PAS un moteur OCR de plus : Table Transformer ne LIT pas le texte — il détecte
les tableaux d'une page (poids `detection`) et leur grille lignes×colonnes (poids
`structure-recognition`). Sa place est l'ENRICHISSEMENT : croiser ses cellules avec les
mots-boîtes qu'un OCR fournit (docTR les rend déjà) pour reconstruire un tableau Markdown.
Il ne rejoint donc pas le select `Backend` du reader (auto/olmocr/doctr/glm-ocr) — il se
déclare comme option (`extract_tables`, à câbler au schéma), jamais comme moteur.

CENTRALISÉ (la manière demandée) :
- contrat `BaseModelBackend` commun (is_available/missing_packages/load/unload,
  comptabilité VRAM héritée) ;
- le CHEMIN des poids vient du CATALOGUE (`AIModel.local_path` par hf_id — la source que
  l'installeur peuple), repli sur la convention `AI-models/models/vision/<nom>` ;
- CPU explicite : deux DETR ~110M tournent en secondes sur CPU — et aucune charge GPU
  n'est prise sans passer par le gouverneur (les crashs du 02/09 imposent la prudence).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)

HF_DETECTION = 'microsoft/table-transformer-detection'
HF_STRUCTURE = 'microsoft/table-transformer-structure-recognition'


def _cache_dir_for(hf_id: str) -> Optional[str]:
    """Racine de cache HF du modèle — le CATALOGUE d'abord (local_path posé par
    l'installeur, format `…/<nom>/models--org--repo`), la convention en repli."""
    try:
        from wama.model_manager.models import AIModel
        m = AIModel.objects.filter(hf_id=hf_id).exclude(local_path='').first()
        if m and m.local_path:
            p = Path(m.local_path)
            racine = p.parent if p.name.startswith('models--') else p
            if racine.is_dir():
                return str(racine)
    except Exception:                      # catalogue indisponible (script hors Django…)
        pass
    from django.conf import settings
    conv = Path(settings.AI_MODELS_DIR) / 'models' / 'vision' / hf_id.split('/')[-1]
    return str(conv) if conv.is_dir() else None


class TableTransformerBackend(BaseModelBackend):
    """Détection + structure de tableaux — enrichisseur, pas moteur OCR (cf. module)."""

    REQUIRED_PACKAGES = ['transformers', 'torch']
    recommended_vram_gb = 0.6          # 2 DETR ~110M ; tournés CPU (voir load)
    description = ("Table Transformer (Microsoft, DETR) — détecte les tableaux d'une page "
                   "et reconstruit leur grille ; croisé avec les mots d'un OCR pour rendre "
                   "un tableau Markdown.")

    def __init__(self):
        self._detector = None
        self._structurer = None
        self._processor = None

    @classmethod
    def is_available(cls) -> bool:
        try:
            import torch                                    # noqa: F401
            from transformers.models import table_transformer  # noqa: F401
            return True
        except Exception:
            return False

    @property
    def is_loaded(self) -> bool:
        return self._detector is not None

    def load(self, model: Optional[str] = None) -> bool:
        cache_det = _cache_dir_for(HF_DETECTION)
        cache_str = _cache_dir_for(HF_STRUCTURE)
        if not cache_det or not cache_str:
            raise RuntimeError('poids table-transformer absents du disque '
                               '(catalogue local_path vide et convention vide)')
        # ⚠ PAS de `os.environ['HF_HUB_CACHE'] = cache_det` ici — retiré le 2026-09-03,
        # premier pas du ROADMAP §5b. `HF_HOME`/`HF_HUB_CACHE` sont posés UNE FOIS au
        # démarrage (`settings.py:165`, vers le cache partagé) et `cache_dir=` suffit à
        # ranger les DEUX modèles principaux dans leur dossier de catégorie.
        #
        # Ce que la mutation cassait, MESURÉ ici même : Table Transformer est un DETR dont
        # la config déclare un backbone timm. Celui-ci se résout par le hub, donc par
        # `HF_HUB_CACHE` — et non par le `cache_dir=` passé au modèle principal. Avec la
        # mutation, `models--timm--resnet18.a1_in1k` atterrissait DANS le dossier de
        # table-transformer (constaté sur disque, aux deux endroits), d'où une ligne de
        # catalogue fantôme pour une simple SOUS-DÉPENDANCE. La var d'env est globale au
        # processus : elle emporte les dépendances avec le modèle.
        # Même famille que le « dump de modèles dans speech/kokoro » (`wama/views.py:223`)
        # et que la commande `dedup_models` (« séquelle de la course HF_HUB_CACHE »).
        from transformers import AutoImageProcessor, TableTransformerForObjectDetection
        self._processor = AutoImageProcessor.from_pretrained(
            HF_DETECTION, cache_dir=cache_det, local_files_only=True)
        self._detector = TableTransformerForObjectDetection.from_pretrained(
            HF_DETECTION, cache_dir=cache_det, local_files_only=True)
        self._structurer = TableTransformerForObjectDetection.from_pretrained(
            HF_STRUCTURE, cache_dir=cache_str, local_files_only=True)
        self._detector.eval()
        self._structurer.eval()
        return True

    def unload(self) -> None:
        self._detector = self._structurer = self._processor = None

    def process(self, **kwargs):
        return self.extract_tables(**kwargs)

    # ── Cœur ─────────────────────────────────────────────────────────────────
    def _boxes(self, model, image, seuil: float):
        import torch
        inputs = self._processor(images=image, return_tensors='pt')
        with torch.no_grad():
            sorties = model(**inputs)
        cible = torch.tensor([image.size[::-1]])
        res = self._processor.post_process_object_detection(
            sorties, threshold=seuil, target_sizes=cible)[0]
        etiquettes = model.config.id2label
        return [(etiquettes[int(l)], [float(x) for x in b])
                for l, b in zip(res['labels'], res['boxes'])]

    def extract_tables(self, image_path: str, words: Optional[list] = None,
                       seuil: float = 0.7) -> list:
        """[{'bbox', 'n_rows', 'n_cols', 'markdown'}] pour chaque tableau détecté.

        `words` : [{'text', 'bbox': [x0, y0, x1, y1]}] en coordonnées de LA PAGE (ce que
        docTR rend) — croisés aux cellules par leur centre. Sans mots, la grille est rendue
        avec des cellules vides (la géométrie seule).
        """
        from PIL import Image
        if not self.is_loaded:
            self.load()
        page = Image.open(image_path).convert('RGB')
        out = []
        for label, bbox in self._boxes(self._detector, page, seuil):
            if label != 'table':
                continue
            x0, y0, x1, y1 = bbox
            # ⚠ Marge d'élargissement OBLIGATOIRE (mesuré le 02/09) : le bbox du détecteur
            # SOUS-ESTIME le tableau (sur une page de test : x1 détecté 530 pour un tableau
            # jusqu'à 744) — le crop tronqué ampute des colonnes et le croisement mots→
            # cellules rate tout ce qui déborde. 10 % de marge par côté, borné à la page
            # (pratique standard des intégrations de ce modèle).
            mx, my = 0.10 * (x1 - x0), 0.10 * (y1 - y0)
            x0, y0 = max(0, x0 - mx), max(0, y0 - my)
            x1, y1 = min(page.width, x1 + mx), min(page.height, y1 + my)
            crop = page.crop((x0, y0, x1, y1))
            lignes, colonnes = [], []
            for s_label, s_box in self._boxes(self._structurer, crop, 0.5):
                if s_label == 'table row':
                    lignes.append(s_box)
                elif s_label == 'table column':
                    colonnes.append(s_box)
            lignes.sort(key=lambda b: b[1])
            colonnes.sort(key=lambda b: b[0])
            out.append({
                'bbox': [x0, y0, x1, y1],
                'n_rows': len(lignes), 'n_cols': len(colonnes),
                'markdown': rows_cols_to_markdown(
                    lignes, colonnes, words or [], offset=(x0, y0)),
            })
        return out


def rows_cols_to_markdown(lignes: list, colonnes: list, words: list,
                          offset: tuple = (0, 0)) -> str:
    """Grille (boîtes lignes × colonnes, coordonnées du CROP) + mots (coordonnées de la
    PAGE) → tableau Markdown. Fonction PURE — testable sans modèle ni poids.

    Un mot appartient à la cellule qui contient son CENTRE. Les mots d'une même cellule
    se concatènent dans l'ordre de lecture (y puis x)."""
    if not lignes or not colonnes:
        return ''
    ox, oy = offset
    grille = [[[] for _ in colonnes] for _ in lignes]
    for w in words:
        bx0, by0, bx1, by1 = w['bbox']
        cx, cy = (bx0 + bx1) / 2 - ox, (by0 + by1) / 2 - oy
        i = next((k for k, r in enumerate(lignes) if r[1] <= cy <= r[3]), None)
        j = next((k for k, c in enumerate(colonnes) if c[0] <= cx <= c[2]), None)
        if i is not None and j is not None:
            grille[i][j].append((by0, bx0, w['text']))
    rendu = []
    for i, rangee in enumerate(grille):
        cellules = [' '.join(t for _, _, t in sorted(c)) for c in rangee]
        rendu.append('| ' + ' | '.join(cellules) + ' |')
        if i == 0:
            rendu.append('|' + '|'.join(' --- ' for _ in colonnes) + '|')
    return '\n'.join(rendu)
