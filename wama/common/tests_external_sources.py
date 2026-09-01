"""Registre commun des sources externes — invariants.

Le test qui porte le plus de valeur est le DERNIER : il interdit qu'un défaut d'adresse soit
recopié hors du registre. Sans lui, la brique range la dispersion une fois et la laisse
revenir — c'est exactement ce qui était arrivé à `ollama_host.py`, brique correcte et complète
dont la docstring signalait elle-même « ~11 autres points d'appel » qui l'ignoraient.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from wama.common import external_sources as es


class RegistreTest(SimpleTestCase):

    def test_les_cles_sont_uniques(self):
        cles = [s.key for s in es.SOURCES]
        self.assertEqual(len(cles), len(set(cles)))

    def test_chaque_source_declare_une_portee_connue(self):
        for s in es.SOURCES:
            with self.subTest(source=s.key):
                self.assertIn(s.scope, (es.LOCAL, es.OUTBOUND))

    def test_chaque_source_declare_une_adresse_et_un_usage(self):
        for s in es.SOURCES:
            with self.subTest(source=s.key):
                self.assertTrue(s.base.startswith('http'), s.base)
                self.assertTrue(s.usage.strip(), "usage vide — la carte serait muette")
                self.assertTrue(s.label.strip())

    def test_une_source_inconnue_nomme_les_sources_connues(self):
        """Un message qui ne dit que « inconnue » oblige à rouvrir le registre pour rien."""
        with self.assertRaises(KeyError) as ctx:
            es.get('pas-une-source')
        self.assertIn('ollama', str(ctx.exception))


class AdresseTest(SimpleTestCase):

    @override_settings(OLLAMA_HOST='http://declare-par-django:1234')
    def test_le_reglage_django_gagne_sur_l_environnement(self):
        with mock.patch.dict(os.environ, {'OLLAMA_HOST': 'http://env:9999'}):
            self.assertEqual(es.base_url('ollama'), 'http://declare-par-django:1234')

    def test_l_environnement_sert_quand_aucun_reglage_django_ne_porte_l_adresse(self):
        """`wama_self` n'a pas de réglage Django — seulement `WAMA_UI_SMOKE_BASE`."""
        with mock.patch.dict(os.environ, {'WAMA_UI_SMOKE_BASE': 'http://ailleurs:8080'}):
            self.assertEqual(es.base_url('wama_self'), 'http://ailleurs:8080')

    def test_le_defaut_declare_sert_en_dernier_recours(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(es.base_url('wama_self'), 'http://127.0.0.1:8000')

    def test_l_adresse_ne_porte_jamais_de_barre_finale(self):
        """Les appelants concatènent leur chemin — une barre en trop donne `//api/tags`."""
        with mock.patch.dict(os.environ, {'WAMA_UI_SMOKE_BASE': 'http://hote:8000/'}):
            self.assertEqual(es.base_url('wama_self'), 'http://hote:8000')

    @override_settings(OLLAMA_HOST='')
    def test_un_reglage_vide_ne_masque_pas_le_defaut(self):
        """Un réglage posé à '' est une absence, pas un choix — sinon l'URL devient ''."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(es.base_url('ollama'), 'http://127.0.0.1:11434')


class PorteeTest(SimpleTestCase):
    """La portée décide du proxy — l'appelant n'a plus à savoir si sa source est locale."""

    def test_le_proxy_est_neutralise_pour_une_source_locale(self):
        with mock.patch.dict(os.environ, {'HTTP_PROXY': 'http://proxy.uge:3128'}):
            self.assertEqual(es.proxies_for('tts_service'), {'http': None, 'https': None})

    def test_une_source_sortante_emprunte_le_proxy(self):
        with mock.patch.dict(os.environ, {'HTTPS_PROXY': 'http://proxy.uge:3128'}):
            self.assertEqual(es.proxies_for('duckduckgo'),
                             {'http': 'http://proxy.uge:3128', 'https': 'http://proxy.uge:3128'})

    def test_les_trois_services_locaux_sont_declares_locaux(self):
        """Régression de l'incident du 2026-08-31 : une portée oubliée coûte un repli de 90 s."""
        for cle in ('ollama', 'tts_service', 'wama_self'):
            with self.subTest(source=cle):
                self.assertEqual(es.get(cle).scope, es.LOCAL)


class CleApiTest(SimpleTestCase):

    def test_une_source_anonyme_est_toujours_configuree(self):
        self.assertTrue(es.is_configured('duckduckgo'))
        self.assertEqual(es.api_key('duckduckgo'), '')

    def test_une_source_a_cle_n_est_configuree_que_si_la_cle_est_posee(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(es.is_configured('artificial_analysis'))
        with mock.patch.dict(os.environ, {'ARTIFICIAL_ANALYSIS_API_KEY': 'k'}):
            self.assertTrue(es.is_configured('artificial_analysis'))

    def test_les_attributions_sont_derivees_du_registre(self):
        """Obligation de licence (l'Arena est en CC-BY-4.0), donc jamais une chaîne figée."""
        attributions = es.attributions()
        self.assertTrue(any('CC-BY-4.0' in a for a in attributions))
        self.assertEqual(len(attributions), len([s for s in es.SOURCES if s.attribution]))


class AucuneRecidiveTest(SimpleTestCase):
    """Le gardien : un défaut d'adresse déclaré ici ne doit pas être recopié ailleurs.

    ⚠ Analyse par AST, pas par grep. Un `grep` compterait les COMMENTAIRES et les docstrings,
    où ces adresses sont légitimement citées (`url_guard` documente `http://localhost:8001/`
    comme exemple d'adresse interne à refuser). Une garde qui rend un chiffre faux se fait
    relever machinalement jusqu'à ne plus rien protéger.
    """

    #: Fichiers autorisés à porter un littéral : le registre lui-même, ses tests, et
    #: `settings.py` qui DÉCLARE la variable Django (son défaut est le pendant assumé de
    #: celui du registre — les faire dépendre l'un de l'autre ferait importer une app depuis
    #: les réglages, au risque de casser le démarrage pour un gain nul).
    EXEMPTS = {
        'wama/common/external_sources.py',
        'wama/common/tests_external_sources.py',
        'wama/settings.py',
    }

    #: Dossiers de code TIERS recopié dans le dépôt — ils ne suivent pas nos règles.
    VENDORISES = ('wama/avatarizer/musetalk', 'wama/avatarizer/codeformer')

    def _litteraux_de_code(self, chemin: Path, attendus: set[str]) -> set[str]:
        """Chaînes présentes dans le CODE — docstrings et chaînes libres exclues.

        Le texte brut sert de PRÉ-FILTRE : `ast.parse` sur tout le dépôt coûtait 85 s, un prix
        auquel un test finit par être désactivé. Un littéral absent du texte ne peut pas être
        une constante de l'arbre — à l'exception théorique d'une concaténation implicite
        (`'http://127.0.0.1' ':8000'`), que le parseur replierait. Ce serait un contournement
        délibéré, pas une récidive par inadvertance : ce test vise la seconde.
        """
        try:
            texte = chemin.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            return set()
        if not any(a in texte for a in attendus):
            return set()
        try:
            arbre = ast.parse(texte)
        except SyntaxError:
            return set()
        libres = {
            id(n.value) for n in ast.walk(arbre)
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
        }
        return {
            n.value for n in ast.walk(arbre)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in libres
        }

    def test_aucun_defaut_d_adresse_n_est_recopie_hors_du_registre(self):
        racine = Path(settings.BASE_DIR)
        attendus = {s.base for s in es.SOURCES}
        fautifs: dict[str, set[str]] = {}

        for dossier in ('wama', 'wama_data', 'wama_lab'):
            for chemin in (racine / dossier).rglob('*.py'):
                rel = chemin.relative_to(racine).as_posix()
                if rel in self.EXEMPTS or any(rel.startswith(v) for v in self.VENDORISES):
                    continue
                recopies = self._litteraux_de_code(chemin, attendus) & attendus
                if recopies:
                    fautifs[rel] = recopies

        self.assertEqual(fautifs, {}, (
            "Adresse(s) recopiée(s) hors du registre. Le défaut d'une source ne vit qu'à UN "
            "endroit : passer par `external_sources.base_url('<clé>')`.\n"
            + '\n'.join(f"  {f} → {', '.join(sorted(v))}" for f, v in sorted(fautifs.items()))
        ))
