# Remplissage de l'enveloppe commune des rapports de l'accueil (`report_shell.html`) — partagé par les
# scripts de construction (`build_transcription_report.py`, `build_cam_analyzer_report.py`). Chargé par
# chemin (`scripts/` n'est pas un paquet) : sys.path.insert(0, 'scripts/reports') puis import.
import html
import json
from pathlib import Path

SHELL = Path(__file__).resolve().parent / 'report_shell.html'


def fill_shell(*, title, kicker, sub, comment, foot, body, evaluations=None):
    """La page complète : `title`, `kicker`, `sub`, `foot` sont du TEXTE (échappé) ; `comment` est le bloc
    de commentaire de gabarit (lignes indentées de deux espaces, terminées par un saut de ligne) ; `body` est
    du HTML déjà rendu.

    `evaluations` : ce que le rapport ÉVALUE, `{clé de modèle: [échelle interne, …]}` (le nom d'échelle de
    `internal_quality.scale_name`). La page le porte comme elle porte sa date, et WAMA l'y lit
    (`wama.common.reports`) : la mesure interne d'un modèle mène au rapport qui la présente."""
    page = SHELL.read_text(encoding='utf-8')
    declared = json.dumps({k: sorted(v) for k, v in sorted((evaluations or {}).items())}, ensure_ascii=False)
    # textes de nœud : `quote=False` — une apostrophe reste une apostrophe (la page d'avant les écrivait ainsi)
    for field, value in (('@@COMMENT@@\n', comment), ('@@TITLE@@', html.escape(title)),
                         ('@@EVALUATIONS@@', html.escape(declared)),
                         ('@@KICKER@@', html.escape(kicker, quote=False)), ('@@SUB@@', html.escape(sub, quote=False)),
                         ('@@FOOT@@', html.escape(foot, quote=False)), ('@@BODY@@', body)):
        assert field in page, field
        page = page.replace(field, value)
    return page
