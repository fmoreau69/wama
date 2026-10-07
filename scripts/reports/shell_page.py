# Remplissage de l'enveloppe commune des rapports de l'accueil (`report_shell.html`) — partagé par les
# scripts de construction (`build_transcription_report.py`, `build_cam_analyzer_report.py`). Chargé par
# chemin (`scripts/` n'est pas un paquet) : sys.path.insert(0, 'scripts/reports') puis import.
import html
from pathlib import Path

SHELL = Path(__file__).resolve().parent / 'report_shell.html'


def fill_shell(*, title, kicker, sub, comment, foot, body):
    """La page complète : `title`, `kicker`, `sub`, `foot` sont du TEXTE (échappé) ; `comment` est le bloc
    de commentaire de gabarit (lignes indentées de deux espaces, terminées par un saut de ligne) ; `body` est
    du HTML déjà rendu."""
    page = SHELL.read_text(encoding='utf-8')
    # textes de nœud : `quote=False` — une apostrophe reste une apostrophe (la page d'avant les écrivait ainsi)
    for field, value in (('@@COMMENT@@\n', comment), ('@@TITLE@@', html.escape(title)),
                         ('@@KICKER@@', html.escape(kicker, quote=False)), ('@@SUB@@', html.escape(sub, quote=False)),
                         ('@@FOOT@@', html.escape(foot, quote=False)), ('@@BODY@@', body)):
        assert field in page, field
        page = page.replace(field, value)
    return page
