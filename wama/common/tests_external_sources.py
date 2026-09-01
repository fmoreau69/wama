"""Registre commun des sources externes — invariants.

Le test qui porte le plus de valeur est le DERNIER : il interdit qu'un défaut d'adresse soit
recopié hors du registre. Sans lui, la brique range la dispersion une fois et la laisse
revenir — c'est exactement ce qui était arrivé à `ollama_host.py`, brique correcte et complète
dont la docstring signalait elle-même « ~11 autres points d'appel » qui l'ignoraient.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

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


def _sonde_factice(key, timeout=None):
    """Une sonde qui ne touche JAMAIS le réseau — les tests éprouvent la mécanique, pas l'ADSL."""
    return {'key': key, 'url': f'http://factice/{key}', 'configured': True,
            'reachable': key != 'duckduckgo', 'status': 200 if key != 'duckduckgo' else None,
            'latency_ms': 3, 'error': '' if key != 'duckduckgo' else 'ConnectTimeout: factice'}


class SondeTest(SimpleTestCase):
    """La sonde du registre `sources_externes` — mécanique seulement, réseau mocké."""

    def test_le_rapport_compte_juste_et_disjoint(self):
        with mock.patch.object(es, 'probe', side_effect=_sonde_factice):
            rapport = es.probe_all()
        c = rapport['counts']
        self.assertEqual(c['total'], len(es.SOURCES))
        self.assertEqual(c['reachable'] + c['unreachable'], c['total'])
        self.assertEqual(c['unreachable'], 1)          # la seule factice injoignable

    def test_le_rapport_ecrit_se_relit_a_l_identique(self):
        chemin = Path(settings.BASE_DIR) / 'media_tests_ignore'  # jamais utilisé : patché
        with mock.patch.object(es, 'probe', side_effect=_sonde_factice), \
             mock.patch.object(es, 'report_path') as rp:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                rp.return_value = Path(tmp) / 'rapport.json'
                ecrit = es.probe_all(write=True)
                self.assertEqual(es.last_report(), json.loads(
                    rp.return_value.read_text(encoding='utf-8')))
                self.assertEqual(es.last_report()['counts'], ecrit['counts'])
        self.assertFalse(chemin.exists())

    def test_sans_rapport_ecrit_la_page_ne_sonde_pas(self):
        with mock.patch.object(es, 'report_path') as rp:
            rp.return_value = Path('nulle/part/rapport.json')
            self.assertIsNone(es.last_report())

    def test_la_sonde_ollama_passe_par_le_resolveur_wsl2(self):
        # Sonder `127.0.0.1` depuis WSL2 accuserait de panne un service qui tourne sur l'hôte.
        with mock.patch('wama.common.utils.ollama_host.ollama_base',
                        return_value='http://passerelle:11434') as rb:
            self.assertEqual(es._probe_url('ollama'), 'http://passerelle:11434')
            rb.assert_called_once()

    def test_une_reponse_http_meme_en_erreur_prouve_la_joignabilite(self):
        # Un 403 (tier d'API) ou un 404 (pas de page racine) prouvent que le serveur répond.
        reponse = mock.Mock(status_code=403)
        with mock.patch('requests.get', return_value=reponse):
            r = es.probe('artificial_analysis')
        self.assertTrue(r['reachable'])
        self.assertEqual(r['status'], 403)
        reponse.close.assert_called_once()


class RegistreSondeTest(TestCase):
    """Le registre catalogué `sources_externes` : déclaration, rafraîchisseur, page."""

    def test_declare_en_nature_mesure_et_execute_en_celery(self):
        from wama.common.registries import CELERY, MEASURE, execution_of, get
        r = get('sources_externes')
        self.assertEqual(r.nature, MEASURE)
        self.assertEqual(execution_of(r), CELERY)
        self.assertEqual(r.permission, 'staff', "la sonde émet des requêtes sortantes")

    def test_le_rafraichisseur_sonde_et_rend_le_compte(self):
        from wama.common.registries import refresh
        with mock.patch.object(es, 'probe', side_effect=_sonde_factice), \
             mock.patch.object(es, 'report_path') as rp:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                rp.return_value = Path(tmp) / 'rapport.json'
                res = refresh('sources_externes')
        self.assertTrue(res.ok)
        self.assertEqual(res.total, len(es.SOURCES))
        self.assertIn('injoignable', ' '.join(res.messages))

    def test_la_page_se_rend_et_distingue_declaration_et_sonde(self):
        user = get_user_model().objects.create_user('sources_page_test', password='x')
        self.client.force_login(user)
        with mock.patch.object(es, 'last_report', return_value=None):
            r = self.client.get(reverse('common:sources_catalog'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['lignes']), len(es.SOURCES))
        # Sans rapport écrit, la page le DIT — elle ne sonde jamais elle-même.
        self.assertContains(r, 'jamais sond')

    def test_le_registre_designe_bien_cette_page(self):
        from wama.common.registries import overview
        entree = next(r for r in overview() if r['key'] == 'sources_externes')
        self.assertEqual(entree['url_name'], 'common:sources_catalog')
        self.assertTrue(reverse(entree['url_name']))


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
