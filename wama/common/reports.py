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


@lru_cache(maxsize=None)
def _dated(path: str, mtime: float) -> str:
    """Le dernier segment du sous-titre de la page ; `mtime` fait relire une page régénérée."""
    with open(path, encoding='utf-8') as f:
        found = _SUBTITLE.search(f.read())
    return found.group(1).rsplit(' · ', 1)[-1].strip() if found else ''


def report_date(slug: str) -> str:
    """La date du rapport telle que son générateur l'a écrite (« généré le 16 octobre 2026 »),
    lue dans la page — jamais recopiée dans la déclaration, où elle périmerait à la régénération
    suivante. Vide si la page ne la porte pas."""
    import os
    from django.template import TemplateDoesNotExist
    from django.template.loader import get_template
    try:
        path = get_template(REPORTS[slug]['template']).origin.name
        return _dated(path, os.path.getmtime(path))
    except (KeyError, TemplateDoesNotExist, OSError):
        return ''


def reports_for(app_key: str) -> list:
    """Les rapports qui parlent de l'app (sa clé de déclaration) : `[{slug, label, date}]`."""
    return [{'slug': slug, 'label': entry['label'], 'date': report_date(slug)}
            for slug, entry in REPORTS.items() if app_key in entry.get('apps', ())]
