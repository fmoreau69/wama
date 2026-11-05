"""Les RAPPORTS publiés par WAMA — une déclaration, lue par tous ceux qui les montrent.

Un rapport est une page servie à `/reports/<slug>/` (`wama.views.report`), générée par son script
de `scripts/reports/` dans l'enveloppe commune (`scripts/reports/report_shell.html`). Il s'AJOUTE
par sa ligne ici, jamais par une entrée de menu ou un lien écrit à la main : le menu
« Présentations & annexes » de l'accueil les liste, et l'onglet « À propos » d'une app montre ceux
qui la concernent (`apps`). La génération automatique des rapports d'évaluation (WAMA_QUALITE,
« Rapports d'évaluation GÉNÉRÉS ») y déclarera les siens.

Déplacé de `wama/views.py` le 2026-11-03 : le substrat (`app_about`) le lit, et une vue du site
n'est pas un lieu que le substrat importe.
"""
import re
from functools import lru_cache

#: slug → gabarit, titre, ligne de détail, et les apps dont le rapport parle (leur clé de
#: déclaration : une jumelle hérite des rapports de sa source, `app_about.declaration_key`).
REPORTS = {
    'transcription': {
        'template': 'includes/wama_rapport_transcription.html',
        'label': 'Évaluation des moteurs de transcription',
        'detail': 'Mesuré dans WAMA, octobre 2026',
        'apps': ('transcriber',),
    },
    'cam-analyzer': {
        'template': 'includes/wama_rapport_cam_analyzer.html',
        'label': 'Analyse vidéo de la navette aux intersections',
        'detail': 'Pipeline du cam_analyzer sur les données ENA, généré depuis les registres',
        'apps': ('cam_analyzer',),
    },
    'anonymizer': {
        'template': 'includes/wama_rapport_anonymizer.html',
        'label': "Évaluation des détecteurs de l'Anonymizer",
        'detail': 'Visages (WIDER FACE) et plaques, généré depuis les mesures du banc',
        'apps': ('anonymizer',),
    },
}

# Le sous-titre que l'enveloppe commune pose sous le titre (`report_shell.html`, `@@SUB@@`) ; son
# dernier segment (« · généré le 16 octobre 2026 ») est la date que le générateur y a écrite.
_SUBTITLE = re.compile(r'<p class="sub">(.*?)</p>', re.S)
# Ce que le rapport ÉVALUE (`@@EVALUATIONS@@`, `fill_shell(evaluations=)`) : `{clé de modèle:
# [échelle interne, …]}`, écrit par son générateur — les mesures que la page présente.
_EVALUATIONS = re.compile(r'<meta name="wama-evaluations" content="([^"]*)">')


@lru_cache(maxsize=None)
def _page_facts(path: str, mtime: float) -> tuple:
    """`(date, évaluations)` lues dans la page ; `mtime` fait relire une page régénérée."""
    import html
    import json
    with open(path, encoding='utf-8') as f:
        page = f.read()
    found = _SUBTITLE.search(page)
    date = found.group(1).rsplit(' · ', 1)[-1].strip() if found else ''
    declared = _EVALUATIONS.search(page)
    try:
        evaluations = json.loads(html.unescape(declared.group(1))) if declared else {}
    except ValueError:
        evaluations = {}
    return date, {k: list(v) for k, v in evaluations.items()} if isinstance(evaluations, dict) else {}


def _facts(slug: str) -> tuple:
    import os
    from django.template import TemplateDoesNotExist
    from django.template.loader import get_template
    try:
        path = get_template(REPORTS[slug]['template']).origin.name
        return _page_facts(path, os.path.getmtime(path))
    except (KeyError, TemplateDoesNotExist, OSError):
        return '', {}


def report_date(slug: str) -> str:
    """La date du rapport telle que son générateur l'a écrite (« généré le 16 octobre 2026 »),
    lue dans la page — jamais recopiée dans la déclaration, où elle périmerait à la régénération
    suivante. Vide si la page ne la porte pas."""
    return _facts(slug)[0]


def report_evaluations(slug: str) -> dict:
    """Ce que le rapport évalue, lu dans la page : `{clé de modèle: [échelle interne, …]}` — vide
    pour un rapport qui ne mesure pas de modèles (celui du cam_analyzer) ou une page d'avant."""
    return _facts(slug)[1]


def _entry(slug: str) -> dict:
    from django.urls import reverse
    return {'slug': slug, 'label': REPORTS[slug]['label'], 'date': report_date(slug),
            'url': reverse('report', args=[slug])}


def reports_for(app_key: str) -> list:
    """Les rapports qui parlent de l'app (sa clé de déclaration) : `[{slug, label, date, url}]`."""
    return [_entry(slug) for slug, entry in REPORTS.items() if app_key in entry.get('apps', ())]


def reports_evaluating(model_keys) -> dict:
    """Les rapports qui évaluent chacun de ces modèles : `{clé: [{slug, label, date, url,
    scales}]}`, `scales` les échelles internes que le rapport présente pour lui. La mesure
    interne d'un modèle (`internal_quality`) mène ainsi au rapport qui la porte — demande de
    Fabien, 2026-11-05. Un modèle qu'aucun rapport n'évalue est absent."""
    wanted = set(model_keys)
    out = {}
    for slug in REPORTS:
        evaluations = report_evaluations(slug)
        hits = wanted & set(evaluations)
        if not hits:
            continue
        entry = _entry(slug)
        for key in hits:
            out.setdefault(key, []).append({**entry, 'scales': list(evaluations[key])})
    return out
