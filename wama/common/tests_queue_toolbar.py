"""Barre d'outils COMMUNE de la file (`common/_queue_toolbar.html`) — invariants de SURFACE.

Le tri et le filtre eux-mêmes sont tenus par `tests_queue_sort.py` (la brique
`apply_queue_sort_filter`). Ici on tient la barre en tant qu'objet rendu : où elle se place,
et ce qu'elle offre.

POURQUOI CE FICHIER (2026-09-08, signalé par Fabien : « dans l'Imager Image et Vidéo, la barre
tri/filtrage/actions se retrouve à côté des cards en mode mosaïque au lieu d'être au-dessus »).

La barre doit être incluse AVANT le conteneur `.wama-queue-*`, jamais dedans. En mosaïque ce
conteneur passe en `display:grid` : une barre incluse à l'intérieur devient une CELLULE de la
grille. Mesuré au navigateur ce jour, sur `/imager/` : 592 px de large en mode ligne, **290 px
en mosaïque** — soit exactement une colonne, à côté de la première card.

Le défaut n'existait QUE dans l'imager (ses deux files) et sa jumelle : les 11 autres files du
parc, et le générateur (`templates_gen.py`), placent la barre avant le conteneur. Rien ne le
disait — d'où ce contrôle, qui mesure l'IMBRICATION RÉELLE (profondeur de `<div>`) et non
l'ordre des lignes : une barre écrite plus haut dans le fichier peut très bien être imbriquée
plus profond.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)

RE_OUVRE = re.compile(r'<div\b', re.I)
RE_FERME = re.compile(r'</div\s*>', re.I)
RE_COMMENTAIRE_LIGNE = re.compile(r'\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}', re.S)


def _jumelles():
    """Labels des jumelles de bac à sable — gabarits GÉNÉRÉS, exemptés.

    Même argument que `tests_queue_dnd._jumelles` : on teste la fabrique, pas son artefact.
    Le générateur est tenu par `test_le_generateur_place_la_barre_avant_le_conteneur`.
    """
    fichier = RACINE / 'wama' / 'sandbox_apps.json'
    if not fichier.exists():
        return set()
    try:
        return {e['label'] for e in json.loads(fichier.read_text(encoding='utf-8'))
                if e.get('label')}
    except (ValueError, KeyError):
        return set()


def barres_imbriquees_dans_une_file(texte: str):
    """Lignes des `include` de barre qui tombent DANS un conteneur `.wama-queue-*`.

    On suit la profondeur de `<div>` en ignorant les `<div>` qui n'apparaissent que dans un
    commentaire `{% comment %}…{% endcomment %}` d'une seule ligne (les gabarits du parc en
    contiennent, et les compter décalerait la profondeur).
    """
    profondeur = 0
    ouverts = []            # (ligne_du_conteneur, profondeur_avant_son_ouverture)
    coupables = []
    for n, ligne in enumerate(texte.splitlines(), 1):
        nu = RE_COMMENTAIRE_LIGNE.sub('', ligne)
        est_file = 'class="wama-queue-' in nu
        if 'include' in nu and '_queue_toolbar.html' in nu and ouverts:
            coupables.append((n, ouverts[-1][0]))
        ouvre = len(RE_OUVRE.findall(nu))
        if est_file and ouvre:
            ouverts.append((n, profondeur))
        profondeur += ouvre - len(RE_FERME.findall(nu))
        while ouverts and profondeur <= ouverts[-1][1]:
            ouverts.pop()
    return coupables


class PlacementDeLaBarreTest(SimpleTestCase):
    """La barre est AU-DESSUS de la file, dans les deux dispositions."""

    def test_aucune_barre_de_file_n_est_imbriquee_dans_son_conteneur(self):
        jumelles = _jumelles()
        defauts = []
        vus = 0
        gabarits = sorted((RACINE / 'wama').glob('*/templates/*/index.html'))
        gabarits += sorted((RACINE / 'wama_lab').glob('*/templates/*/index.html'))
        for gabarit in gabarits:
            if gabarit.parts[-4] in jumelles:
                continue
            texte = gabarit.read_text(encoding='utf-8')
            if '_queue_toolbar.html' not in texte:
                continue
            vus += 1
            for ligne, conteneur in barres_imbriquees_dans_une_file(texte):
                defauts.append(
                    f"{gabarit.relative_to(RACINE)}:{ligne} — barre incluse DANS le conteneur "
                    f"de file ouvert l.{conteneur} : en mosaïque elle devient une cellule de "
                    f"la grille, à côté des cards")
        self.assertEqual([], defauts, "\n".join(defauts))
        # Garde anti-vide : un glob qui ne trouve plus rien rendrait ce test vert sans mesurer.
        self.assertGreaterEqual(vus, 10, f"seulement {vus} gabarit(s) à barre relevé(s)")

    def test_le_detecteur_voit_le_defaut_qu_il_est_cense_voir(self):
        """CONTRE-ÉPREUVE — sans elle, le test ci-dessus pourrait être vert par impuissance.

        On rejoue la forme EXACTE que l'imager portait avant le correctif du 2026-09-08.
        """
        fautif = (
            '<div class="row">\n'
            '  <div class="col-12">\n'
            '    <div id="q" class="wama-queue-list" data-wama-dnd="x">\n'
            "      {% include 'common/_queue_toolbar.html' with q_sort=q_sort %}\n"
            '    </div>\n'
            '  </div>\n'
            '</div>\n')
        self.assertEqual([(4, 3)], barres_imbriquees_dans_une_file(fautif))

        correct = (
            "{% include 'common/_queue_toolbar.html' with q_sort=q_sort %}\n"
            '<div id="q" class="wama-queue-list" data-wama-dnd="x">\n'
            '</div>\n')
        self.assertEqual([], barres_imbriquees_dans_une_file(correct))

    def test_le_generateur_place_la_barre_avant_le_conteneur(self):
        """La chaîne de génération ne doit pas semer le défaut dans les apps futures.

        Elle était déjà juste (`templates_gen.py` émet la barre puis le conteneur) — c'est
        justement ce qui a permis d'attribuer le défaut au gabarit écrit à la main de l'imager
        plutôt qu'à la brique. On l'ancre pour que ça reste vrai.
        """
        source = (RACINE / 'wama' / 'common' / 'manifests' / 'codegen'
                  / 'templates_gen.py').read_text(encoding='utf-8')
        barre = source.find("_queue_toolbar.html")
        conteneur = source.find('class="wama-queue-')
        self.assertNotEqual(-1, barre, "le générateur n'émet plus de barre d'outils de file")
        self.assertNotEqual(-1, conteneur, "le générateur n'émet plus de conteneur de file")
        self.assertLess(barre, conteneur,
                        "le générateur émettrait la barre DANS le conteneur de file")
