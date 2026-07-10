"""
Skills de prompt par application (ROADMAP §16.6, extension « skills » 2026-07-08).

UN skill = UN fichier de consignes (markdown, anglais) dans `wama/common/prompt_skills/`,
envoyé comme system prompt au LLM d'enrichissement. Centralisé → réutilisable depuis TOUTES
les sources d'appel : pipeline de prompts (au lancement de tâche), enrichissement à la demande
(bouton ✨ des apps), assistant IA et wama-dev-ai (mêmes fichiers, zéro dépendance Django).

Résolution du plus spécifique au plus générique :
    <app>-<domain>  (ex. imager-image, imager-video, composer-music)
    <app>           (ex. imager)
    default-<kind>  (ex. default-generative)
→ (name, text) ou (None, None) si rien (l'appelant garde son fallback intégré — fail-safe).

Le DOMAIN vient de la déclaration PROMPT_TARGETS (`domain` statique ou `domain_field` lu sur
l'instance, ex. imager `output_type` image|video), avec repli sur le model_type du modèle cible.

Règles du FORMAT de skill (contrat, cf. prompt_skills/README.md) :
- Le fichier EST le system prompt (pas de frontmatter) ; il doit imposer : sujet utilisateur
  PRÉSERVÉ, sortie = le prompt enrichi SEUL (pas de préambule/citations).
- La clause de langue d'émission et la préservation des mots-clés forcés (glossaire) sont
  ajoutées PAR LE CODE (prompt_enrichment) — ne pas les dupliquer dans les fichiers.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent.parent / 'prompt_skills'

# Cache process : {name: text|None}. Fichiers quasi statiques (redémarrage = rechargement).
_cache: dict = {}


def _slug(part: str) -> str:
    """Nom de fichier sûr depuis un composant (app/domain) : minuscules, [a-z0-9-]."""
    return re.sub(r'[^a-z0-9]+', '-', (part or '').strip().lower()).strip('-')


def load_skill(name: str):
    """Texte du skill `name` (sans extension), ou None. Fail-safe, mis en cache."""
    if not name:
        return None
    if name in _cache:
        return _cache[name]
    text = None
    try:
        p = SKILLS_DIR / f"{name}.md"
        if p.is_file():
            text = p.read_text(encoding='utf-8').strip() or None
    except Exception as e:
        logger.debug(f"[prompt_skills] lecture {name}: {e}")
    _cache[name] = text
    return text


def resolve_skill(app: str = None, domain: str = None, kind: str = 'generative'):
    """Skill le plus spécifique pour (app, domain, kind) → (name, text) ou (None, None)."""
    candidates = []
    a, d = _slug(app), _slug(domain)
    if a and d:
        candidates.append(f"{a}-{d}")
    if a:
        candidates.append(a)
    if kind:
        candidates.append(f"default-{_slug(kind)}")
    for name in candidates:
        text = load_skill(name)
        if text:
            return name, text
    return None, None


def skills_catalog() -> dict:
    """{name: text} de tous les skills présents — pour l'assistant IA / wama-dev-ai / debug."""
    out = {}
    try:
        for p in sorted(SKILLS_DIR.glob('*.md')):
            if p.stem.lower() == 'readme':
                continue
            t = load_skill(p.stem)
            if t:
                out[p.stem] = t
    except Exception as e:
        logger.debug(f"[prompt_skills] catalog: {e}")
    return out
