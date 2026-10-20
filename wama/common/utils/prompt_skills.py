"""
Skills de prompt par application (ROADMAP §16.6, extension « skills » 2026-07-08).

UN skill = UN fichier de consignes (markdown, anglais) dans `wama/common/prompt_skills/`,
envoyé comme system prompt au LLM d'enrichissement. Centralisé → réutilisable depuis TOUTES
les sources d'appel : pipeline de prompts (au lancement de tâche), enrichissement à la demande
(bouton ✨ des apps), assistant IA et wama-dev-ai (mêmes fichiers, zéro dépendance Django).

⚠ **« et wama-dev-ai » a été FAUX du 2026-07-08 au 2026-09-09** — cette phrase énonçait une
intention, pas un état. Le pont existe désormais pour de bon (`role_utils.skill_wama()` /
`catalogue_skills()`), et la promesse est vérifiable : `wama-dev-ai/config.py` ne déclare plus
de chemin vers ce dossier, il APPELLE ces accesseurs. La clause « zéro dépendance Django »,
elle, a été mesurée le 2026-09-09 et TIENT : ce module n'importe que `pathlib`/`re`/`logging`,
et `from wama.common.utils.prompt_skills import resolve_skill` réussit avec
`DJANGO_SETTINGS_MODULE` non défini.

🔒 CE FICHIER-CI N'A PAS DE FRONTMATTER, ET C'EST UN CONTRAT (tranché le 2026-09-09) : le
consommateur final de ces skills est un modèle qui ne sait pas CHOISIR (diffusion, SAM3, TTS),
donc c'est le CODE qui choisit pour lui (`resolve_skill`). Le format `SKILL.md` à frontmatter
sert l'autre cas — une consigne de DÉVELOPPEMENT qu'un AGENT sélectionne d'après sa description
(`.claude/skills/`). Deux mécanismes de sélection, deux formats. Cf. `WAMA_LLM §0bis 🔒`.

Résolution du plus spécifique au plus générique :
    <app>-<domain>  (ex. imager-image, imager-video, composer-music)
    <app>           (ex. imager)
    default-<kind>  (ex. default-generative)
→ (name, text) ou (None, None) si rien (l'appelant garde son fallback intégré — fail-safe).

À CHAQUE NOM, trois sources, dans cet ordre (`ROADMAP §29`, 2026-10-20 — piste 2 de Fabien) :
le skill de L'AUTEUR (`common.PromptSkill`, `user=`), le skill SYSTÈME promu (même table, sans
propriétaire), le FICHIER du dépôt. Un skill PARTAGÉ par un autre compte ne s'applique pas tout
seul : il se copie dans les siens (`skills_catalog`), il ne s'impose à personne. La table n'est
lue que si Django est prêt — wama-dev-ai importe ce module sans lui, et n'y lit que le système
des fichiers.

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


def is_valid_name(name: str) -> bool:
    """Le nom d'un skill suit la grammaire des fichiers : ce que `_slug` produit, non vide."""
    return bool(name) and len(name) <= 64 and _slug(name) == name


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


def _row_texts(names, user=None) -> dict:
    """{nom: texte} des skills en TABLE qui s'appliquent pour `user` : les siens d'abord, puis
    ceux du système (sans propriétaire). Sans compte, le système seul. Vide hors Django (ou si
    la table manque encore) : la résolution retombe sur les fichiers, comme avant."""
    try:
        from django.apps import apps
        if not apps.ready:
            return {}
        from django.db.models import Q

        from wama.common.models import PromptSkill
        mine = Q(owner__isnull=True)
        if getattr(user, 'is_authenticated', False):
            mine |= Q(owner=user)
        rows = PromptSkill.objects.filter(mine, name__in=list(names)).values_list(
            'name', 'text', 'owner_id')
        out = {}
        # Le sien passe devant le système : trié propriétaire d'abord (`None` en dernier).
        for name, text, owner_id in sorted(rows, key=lambda r: r[2] is None):
            if text and text.strip() and name not in out:
                out[name] = text.strip()
        return out
    except Exception as e:
        logger.debug(f"[prompt_skills] skills en table illisibles : {e}")
        return {}


def resolve_skill(app: str = None, domain: str = None, kind: str = 'generative', user=None):
    """Skill le plus spécifique pour (app, domain, kind) → (name, text) ou (None, None).
    `user` : le compte pour qui l'on résout — son skill passe devant le système."""
    candidates = []
    a, d = _slug(app), _slug(domain)
    if a and d:
        candidates.append(f"{a}-{d}")
    if a:
        candidates.append(a)
    if kind:
        candidates.append(f"default-{_slug(kind)}")
    rows = _row_texts(candidates, user)
    for name in candidates:
        text = rows.get(name) or load_skill(name)
        if text:
            return name, text
    return None, None


def file_skill_names() -> list:
    """Les noms des skills FICHIERS du dépôt — le système d'origine."""
    try:
        return [p.stem for p in sorted(SKILLS_DIR.glob('*.md')) if p.stem.lower() != 'readme']
    except Exception as e:
        logger.debug(f"[prompt_skills] dossier illisible : {e}")
        return []


def skills_catalog() -> dict:
    """{name: text} des skills SYSTÈME — les fichiers du dépôt, et ceux qu'un administrateur a
    promus (`common.PromptSkill` sans propriétaire, lus seulement sous Django). Pour l'assistant
    IA / wama-dev-ai / le registre `skills`. Les skills d'un compte se listent ailleurs
    (`services/skills_catalog`), par le filtre des catalogues."""
    out = {}
    for name in file_skill_names():
        t = load_skill(name)
        if t:
            out[name] = t
    try:
        from django.apps import apps
        if apps.ready:
            from wama.common.models import PromptSkill
            for name, text in PromptSkill.objects.filter(owner__isnull=True).values_list(
                    'name', 'text'):
                if text and text.strip():
                    out[name] = text.strip()     # la table avant le fichier, comme `resolve_skill`
    except Exception as e:
        logger.debug(f"[prompt_skills] skills système en table illisibles : {e}")
    return dict(sorted(out.items()))
