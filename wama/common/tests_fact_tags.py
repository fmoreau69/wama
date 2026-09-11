"""Tests des faits EN LIGNE (`common/fact_tags.py`) — une balise de doc qui cite un registre.

Ce qui est vérifié est ce qui justifie la brique : une balise rend la valeur ACTUELLE du registre,
refuse ce qu'elle ne sait pas résoudre au lieu de le deviner, et ne réécrit jamais une valeur
qu'elle n'a pas su calculer. Plus la garde de corpus : chaque balise posée dans une doc déclarée
doit se résoudre — une balise cassée dans le dépôt est une doc qui ment en silence.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from .fact_tags import FactError, refresh_text, render_value, resolve


class ResolutionTest(TestCase):

    def test_le_registre_des_registres_se_compte(self):
        from .registries import REGISTRIES
        self.assertEqual(resolve('registres'), str(len(REGISTRIES)))

    def test_un_champ_du_registre_des_registres_se_lit(self):
        from .registries import REGISTRIES
        self.assertEqual(resolve('registres/apps/label'), REGISTRIES['apps'].label)

    def test_une_fiche_declaree_se_lit(self):
        from .app_registry import APP_CATALOG
        self.assertEqual(resolve('apps/transcriber/label'), APP_CATALOG['transcriber']['label'])
        self.assertEqual(resolve('apps'), str(len(APP_CATALOG)))

    def test_ce_qui_ne_se_resout_pas_est_refuse(self):
        for chemin, motif in (('inexistant', 'inconnu'),
                              ('apps/inexistante/label', 'clé'),
                              ('apps/transcriber/champ_inexistant', 'champ'),
                              ('apps/transcriber', 'attendu'),
                              ('rag/x/y', 'ne déclare pas ses fiches')):
            with self.assertRaises(FactError, msg=chemin) as ctx:
                resolve(chemin)
            self.assertIn(motif, str(ctx.exception), chemin)

    def test_une_structure_n_est_pas_une_valeur(self):
        with self.assertRaises(FactError):
            render_value({'a': 1})
        self.assertEqual(render_value(['a', 'b']), 'a, b')
        self.assertEqual(render_value(None), '—')
        self.assertEqual(render_value(True), 'oui')
        self.assertEqual(render_value("deux\n  lignes"), 'deux lignes')


class RafraichissementTest(TestCase):

    def test_une_valeur_perimee_est_regeneree_et_c_est_idempotent(self):
        from .registries import REGISTRIES
        texte = "Il y a <!-- WAMA:FAIT(registres) -->3<!-- /WAMA:FAIT --> registres."
        neuf, n, erreurs = refresh_text(texte)
        self.assertEqual((n, erreurs), (1, []))
        self.assertIn(f"-->{len(REGISTRIES)}<!--", neuf)
        self.assertEqual(refresh_text(neuf)[0], neuf)

    def test_une_balise_cassee_garde_sa_valeur_et_remonte(self):
        texte = "x <!-- WAMA:FAIT(inexistant/a/b) -->valeur écrite<!-- /WAMA:FAIT --> y"
        neuf, n, erreurs = refresh_text(texte)
        self.assertEqual(neuf, texte)
        self.assertEqual(n, 1)
        self.assertEqual([c for c, _ in erreurs], ['inexistant/a/b'])

    def test_une_balise_citee_en_code_n_est_pas_une_balise(self):
        # Le cas qui a fait naître la règle : la phrase qui PRÉSENTAIT la syntaxe, prise pour un
        # fait cassé (`registre « registre » inconnu`).
        texte = ("La syntaxe : `<!-- WAMA:FAIT(registre/clé/champ) -->v<!-- /WAMA:FAIT -->`.\n\n"
                 "```\n<!-- WAMA:FAIT(x/y/z) -->v<!-- /WAMA:FAIT -->\n```\n")
        self.assertEqual(refresh_text(texte), (texte, 0, []))

    def test_les_blocs_WAMA_FAITS_ne_sont_pas_des_balises_en_ligne(self):
        texte = "<!-- WAMA:FAITS(outils) — généré -->\ncontenu\n<!-- /WAMA:FAITS(outils) -->"
        self.assertEqual(refresh_text(texte), (texte, 0, []))


class CorpusTest(TestCase):

    def test_chaque_balise_du_corpus_se_resout(self):
        from .docs_catalog import checked_paths
        base = Path(settings.BASE_DIR)
        cassees = []
        for rel in checked_paths():
            f = base / rel
            if f.is_file():
                cassees += [(rel, c, m) for c, m in refresh_text(
                    f.read_text(encoding='utf-8', errors='replace'))[2]]
        self.assertEqual(cassees, [])
