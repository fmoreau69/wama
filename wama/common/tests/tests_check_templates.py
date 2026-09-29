"""Verrouille `check_templates` — le contrôle du commentaire de gabarit multi-ligne.

Pourquoi ces tests existent : la faute visée a récidivé SEPT fois depuis le 2026-06-27, et les
trois occurrences documentées ont coûté des sessions entières de diagnostic (barre de progression
poussée hors d'une piste clippée, `<template>` écrit dans un commentaire qui a avalé 30 `<script>`,
ligne fantôme de 168 px dans une grille). La commande n'a d'intérêt que si elle DÉTECTE : chaque
test injecte donc la régression au lieu de constater que le dépôt est vert aujourd'hui.

Contre-épreuve incluse : un gabarit sain doit sortir muet. Un contrôle qui signale tout ne vaut
pas mieux que celui qui ne signale rien.
"""
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from wama.common.management.commands.check_templates import scanner

# Composés à l'exécution : écrits en clair dans ce fichier, ils seraient eux-mêmes des motifs
# suspects pour tout outil qui grep le dépôt.
OUVRE, FERME = '{' + '#', '#' + '}'


def _depot(**gabarits):
    """Un dépôt jetable avec un `wama/templates/` — la seule racine dont le scan a besoin."""
    tmp = tempfile.TemporaryDirectory()
    d = Path(tmp.name) / 'wama' / 'templates'
    d.mkdir(parents=True)
    for nom, corps in gabarits.items():
        (d / f'{nom}.html').write_text(corps, encoding='utf-8')
    return tmp


class ScannerTests(SimpleTestCase):
    """Le cœur : `scanner()`, appelé directement sur un dépôt jetable."""

    def _defauts(self, **gabarits):
        tmp = _depot(**gabarits)
        self.addCleanup(tmp.cleanup)
        return scanner(tmp.name)

    def test_un_commentaire_sur_deux_lignes_est_signale(self):
        # LE défaut : le lexer de Django n'a pas re.DOTALL, donc ceci est rendu comme du TEXTE.
        d = self._defauts(page=f"<div>{OUVRE} une explication\n   qui continue {FERME}</div>")
        self.assertEqual([x['genre'] for x in d], ['multi-ligne'])
        self.assertEqual(d[0]['ligne'], 1)

    def test_un_load_vers_une_bibliotheque_absente_est_signale(self):
        # Défaut VÉCU le 2026-09-01 : `reader_tags.py` retiré (filtre réellement mort), son
        # `{% load %}` laissé → page reader en TemplateSyntaxError. Ni ce contrôle (qui ne
        # lisait que les commentaires) ni la suite (aucun test ne rendait ce partial) ne
        # pouvaient le voir. ⚠ Et la bibliothèque fautive est AU MILIEU d'une liste : c'est
        # ce qui avait fait passer mon grep, écrit sur la graphie `load reader_tags`.
        d = self._defauts(page='{% load i18n bibliotheque_disparue wama_actions %}<div>x</div>')
        self.assertEqual([x['genre'] for x in d], ['load-introuvable'])
        self.assertIn('bibliotheque_disparue', d[0]['extrait'])

    def test_un_load_de_bibliotheques_existantes_ne_declenche_rien(self):
        # Contre-épreuve : les 129 gabarits du dépôt en chargent à longueur de fichier.
        self.assertEqual(
            self._defauts(page='{% load i18n static wama_actions wama_static %}<div>x</div>'), [])

    def test_un_commentaire_sur_une_seule_ligne_ne_declenche_rien(self):
        # La contre-épreuve la plus importante : le dépôt en compte des centaines de légitimes.
        self.assertEqual(self._defauts(page=f"<div>{OUVRE} court {FERME}</div>"), [])

    def test_un_nom_de_balise_avaleuse_dans_un_commentaire_est_signale_meme_sur_une_ligne(self):
        # Cas du 2026-07-26 : mono-ligne le jour même, dangereux au premier reformatage.
        d = self._defauts(page=f"{OUVRE} on garde <template> pour plus tard {FERME}")
        self.assertEqual([x['genre'] for x in d], ['balise-avaleuse'])
        self.assertIn('template', d[0]['extrait'])

    def test_un_commentaire_jamais_referme_est_signale(self):
        d = self._defauts(page=f"<p>ok</p>\n{OUVRE} on a oublié de refermer\n<p>suite</p>")
        self.assertEqual([x['genre'] for x in d], ['jamais-refermé'])
        self.assertEqual(d[0]['ligne'], 2)

    def test_le_bloc_comment_de_django_est_la_forme_saine_et_passe(self):
        # Le remède recommandé par le message d'erreur ne doit évidemment pas être signalé.
        corps = "{% comment %}\n  une explication\n  sur plusieurs lignes\n{% endcomment %}"
        self.assertEqual(self._defauts(page=corps), [])

    def test_chaque_gabarit_fautif_est_rapporte_separement(self):
        d = self._defauts(a=f"{OUVRE} un\ndeux {FERME}", b=f"{OUVRE} trois\nquatre {FERME}",
                          c="<p>sain</p>")
        self.assertEqual(sorted(x['fichier'] for x in d),
                         ['wama/templates/a.html', 'wama/templates/b.html'])

    def test_un_gabarit_illisible_est_signale_au_lieu_de_faire_planter_le_scan(self):
        tmp = _depot(sain="<p>ok</p>")
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / 'wama' / 'templates' / 'binaire.html').write_bytes(b'\xff\xfe\x00abc')
        d = scanner(tmp.name)
        self.assertEqual([x['genre'] for x in d], ['illisible'])

    def test_une_racine_de_monde_absente_est_ignoree_en_silence(self):
        # `wama_lab`/`wama_data` peuvent manquer sur une machine : ce n'est pas un défaut.
        self.assertEqual(self._defauts(page="<p>ok</p>"), [])


class CommandeTests(SimpleTestCase):
    """L'enveloppe : rapport lisible, code de sortie, et le pied qui rappelle le remède."""

    def _lancer(self, gabarits, *args):
        tmp = _depot(**gabarits)
        self.addCleanup(tmp.cleanup)
        sortie = StringIO()
        with override_settings(BASE_DIR=tmp.name):
            call_command('check_templates', *args, stdout=sortie)
        return sortie.getvalue()

    def test_un_depot_sain_annonce_explicitement_qu_il_a_regarde(self):
        # « 0 défaut » sans dénominateur ne distingue pas un dépôt sain d'un scan à vide.
        r = self._lancer({'page': "<p>ok</p>"})
        self.assertIn('Aucun commentaire de gabarit dangereux', r)
        self.assertIn('sur 1 gabarit', r)

    def test_le_rapport_nomme_le_fichier_la_ligne_et_le_remede(self):
        r = self._lancer({'page': f"<div>{OUVRE} une\nexplication {FERME}</div>"})
        self.assertIn('wama/templates/page.html:1', r)
        self.assertIn('multi-ligne', r)
        self.assertIn('endcomment', r)

    def test_strict_sort_en_erreur_quand_il_reste_un_defaut(self):
        with self.assertRaises(SystemExit) as ctx:
            self._lancer({'page': f"{OUVRE} une\nexplication {FERME}"}, '--strict')
        self.assertEqual(ctx.exception.code, 1)

    def test_strict_ne_sort_pas_en_erreur_sur_un_depot_sain(self):
        self.assertIn('Aucun commentaire', self._lancer({'page': "<p>ok</p>"}, '--strict'))

    def test_json_rend_le_denominateur_et_les_defauts(self):
        import json
        r = json.loads(self._lancer({'page': f"{OUVRE} une\nexplication {FERME}"}, '--json'))
        self.assertEqual(r['gabarits'], 1)
        self.assertEqual(r['defauts'][0]['genre'], 'multi-ligne')


class DepotReelTests(SimpleTestCase):
    """Le gabarit du dépôt VIVANT, pas un dépôt jetable : c'est lui qu'on protège."""

    def test_le_depot_courant_ne_porte_aucun_commentaire_dangereux(self):
        d = scanner()
        self.assertEqual(d, [], "\n".join(
            f"{x['fichier']}:{x['ligne']}  [{x['genre']}]  {x['extrait']}" for x in d))
