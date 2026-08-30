"""Le TÉLÉCHARGEMENT — encodage du nom proposé, et RENDU du bouton ⬇.

Deux familles ici, réunies parce qu'elles gardent le même geste par ses deux bouts : ce que
l'utilisateur reçoit (le nom du fichier) et ce sur quoi il clique (le bouton et ses formats).

Contexte (2026-08-25, symptôme signalé par Fabien : « plusieurs fois des soucis d'affichage
des noms de fichiers à cause de l'encodage »). Onze vues écrivaient l'en-tête à la main :

    response['Content-Disposition'] = f'attachment; filename="{nom}"'

Un en-tête HTTP est transmis en latin-1. Django ne lève pas — il replie sur un encodage MIME
(`=?utf-8?b?…?=`) que les navigateurs n'interprètent PAS pour un nom de fichier : l'utilisateur
recevait un nom abîmé. La forme correcte est la RFC 5987 (`filename*=utf-8''…`), et Django la
produit lui-même via `content_disposition_header` — le dépôt savait d'ailleurs la LIRE
(`common/utils/video_utils.py:135`) sans savoir l'écrire.

⚠ Ces tests comptent d'autant plus que la brique de nommage PRÉSERVE désormais les accents
du nom d'origine (décision du 2026-08-25) : les noms non-ASCII sont passés de l'exception à
la norme, donc l'exposition à ce défaut a AUGMENTÉ.
"""
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase
from django.utils.http import content_disposition_header


def _rendu(arguments):
    """Rend `{% download_button … %}` et renvoie le HTML, espaces resserrés."""
    html = Template('{% load wama_actions %}{% download_button ' + arguments + ' %}').render(Context({}))
    return re.sub(r'\s+', ' ', html).strip()


class EncodageDuNomTelechargeTests(SimpleTestCase):

    def test_un_nom_accentue_part_en_RFC_5987(self):
        entete = content_disposition_header(True, "Réunion équipe_voice_xtts.wav")
        self.assertIn("filename*=utf-8''", entete)
        self.assertNotIn('Réunion', entete, "le nom brut ne doit pas voyager en latin-1")
        self.assertIn('R%C3%A9union', entete)

    def test_un_nom_ASCII_garde_la_forme_SIMPLE(self):
        """Compatibilité maximale : on ne complique pas ce qui n'en a pas besoin."""
        self.assertEqual(content_disposition_header(True, "rapport.pdf"),
                         'attachment; filename="rapport.pdf"')


class PasDeRecidiveTests(SimpleTestCase):
    """⚠ Garde-fou. Le défaut était RECOPIÉ dans 7 fichiers de vues : le corriger une fois ne
    protège de rien si le prochain copie l'idiome d'à côté. Ce test échoue à la RÉAPPARITION.
    """

    #: `f'attachment; filename="…"'` ou `inline` — l'en-tête composé à la main.
    IDIOME = re.compile(r"""f['"](attachment|inline); filename=""")

    def test_aucune_vue_n_ecrit_Content_Disposition_a_la_main(self):
        racine = Path(settings.BASE_DIR)
        coupables = []
        for chemin in list(racine.glob('wama/*/views.py')) + list(racine.glob('wama_lab/*/views.py')):
            for num, ligne in enumerate(chemin.read_text(encoding='utf-8').splitlines(), 1):
                if self.IDIOME.search(ligne):
                    coupables.append(f"{chemin.relative_to(racine)}:{num}")
        self.assertEqual(
            coupables, [],
            "en-tête Content-Disposition écrit à la main — utiliser "
            "`django.utils.http.content_disposition_header(as_attachment, nom)`, "
            "qui bascule seul en RFC 5987 sur un nom non-ASCII :\n  "
            + "\n  ".join(coupables))


class BoutonTelechargerTests(SimpleTestCase):
    """Les quatre formes du ⬇ commun — dont `split=False`, ajoutée le 2026-08-30 pour la BARRE
    de file. Ce qui est réellement vérifié ici n'est pas l'esthétique : c'est que les formats
    offerts viennent de la DÉCLARATION (`export_formats` du catalogue) et non d'une liste
    recopiée. Le transcriber en avait une, en JS, avec ses quatre formats en dur.
    """

    def test_sans_split_le_menu_est_seul_et_la_rangee_ne_s_elargit_pas(self):
        html = _rendu("'transcriber' '/dl/' True html_id='dl-tout' label='Télécharger tout' split=False")
        self.assertIn('id="dl-tout"', html)
        self.assertIn('Télécharger tout', html)
        self.assertIn('dropdown-toggle', html)
        self.assertNotIn('dropdown-toggle-split', html,
                         "la barre de file rend UN bouton ▾, pas un split button")

    def test_les_formats_offerts_viennent_du_CATALOGUE_pas_d_une_liste_recopiee(self):
        html = _rendu("'transcriber' '/dl/' True split=False")
        for fmt in ('txt', 'srt', 'pdf', 'docx'):
            self.assertIn(f'/dl/?format={fmt}', html)
        self.assertNotIn('format=vtt', html,
                         "`vtt` est un `output_types`, pas un `export_formats` — les deux diffèrent")

    def test_le_menu_existe_MEME_desactive_sinon_le_JS_ne_peut_plus_l_activer(self):
        """⚠ Trois apps basculent `disabled` au runtime : la branche doit se rendre quand même."""
        html = _rendu("'transcriber' '/dl/' False html_id='dl-tout' split=False")
        self.assertIn('disabled', html)
        self.assertIn('/dl/?format=txt', html)

    def test_une_card_garde_son_split_button_le_defaut_n_a_pas_bouge(self):
        html = _rendu("'transcriber' '/dl/' True")
        self.assertIn('dropdown-toggle-split', html)
        self.assertIn('href="/dl/?format=txt"', html, "le lien principal = premier format déclaré")
        self.assertNotIn('id=', html, "sans `html_id`, aucun id parasite n'apparaît")

    def test_une_app_sans_formats_declares_rend_un_LIEN_simple(self):
        html = _rendu("'anonymizer' '/dl/' True")
        self.assertIn('href="/dl/"', html)
        self.assertNotIn('dropdown', html)


class PasDeDropdownReconstruitEnJSTests(SimpleTestCase):
    """⚠ Garde-fou jumeau du précédent, côté JS (2026-08-30).

    La duplication résorbée n'était PAS un gabarit recopié : c'était un dropdown reconstruit en
    JavaScript autour du bouton rendu, avec les formats codés en dur. Aucun test de gabarit ne
    pouvait la voir — d'où ce contrôle sur les sources JS.
    """

    IDIOME = re.compile(r"""classList\.add\(['"]dropdown-toggle['"]\)""")

    def test_aucun_JS_d_app_ne_transforme_un_bouton_en_dropdown(self):
        racine = Path(settings.BASE_DIR)
        coupables = []
        for chemin in racine.glob('wama/*/static/*/js/*.js'):
            for num, ligne in enumerate(chemin.read_text(encoding='utf-8').splitlines(), 1):
                if self.IDIOME.search(ligne):
                    coupables.append(f"{chemin.relative_to(racine)}:{num}")
        self.assertEqual(
            coupables, [],
            "dropdown de téléchargement reconstruit en JS — passer `split=False` au tag "
            "`download_button` (les formats viennent alors du catalogue) :\n  "
            + "\n  ".join(coupables))
