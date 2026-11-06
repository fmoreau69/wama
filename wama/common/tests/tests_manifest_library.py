"""Kind `library` — l'extraction mécanique et sa projection tiennent ce qu'elles promettent.

POURQUOI CE FICHIER (2026-09-07) : le premier semis MÉCANIQUE de 12 moteurs (« un moteur est
une librairie », décision Fabien) a fait échouer la projection au 6ᵉ manifeste — `DataError`,
`value too long for type character varying(128)`. Quatre paquets (`kokoro`, `python-doctr`,
`sam3`, `suno-bark`) mettent le TEXTE INTÉGRAL de leur licence (1 à 11 Ko) dans le champ
`License` des métadonnées, et l'extracteur le recopiait dans `identity.license` — un champ
que le registre projette dans un IDENTIFIANT de 128 caractères. Aucun test ne tenait ce kind.

Ce qui est tenu ici :
  • `licence_courte` rend un IDENTIFIANT ou None — jamais un texte (l'ordre déclaré →
    déduit : expression PEP 639, champ court, classifieur Trove, rien) ;
  • le validateur REFUSE un manifeste dont la licence est un texte — l'export l'aurait
    refusé au lieu de l'écrire ;
  • invariant de CORPUS : aucun manifeste `library` du dépôt ne porte un texte de licence.
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase

import sys
from unittest import skipUnless

from wama.common.manifests.builtin.library import (
    AUTHOR_MAX, LICENCE_MAX, author_name, licence_courte, validate_library_body,
)


class _Meta:
    """Stub des métadonnées `importlib.metadata` : `get` + `get_all`, rien d'autre."""

    def __init__(self, **champs):
        self._c = champs

    def get(self, cle, defaut=None):
        v = self._c.get(cle)
        return v if isinstance(v, str) else defaut

    def get_all(self, cle):
        v = self._c.get(cle)
        return list(v) if isinstance(v, (list, tuple)) else None


TEXTE_APACHE = "Apache License\nVersion 2.0, January 2004\n" + ("x" * 11000)


class LicenceCourteTest(SimpleTestCase):

    def test_l_expression_PEP_639_gagne_sur_tout(self):
        m = _Meta(**{'License-Expression': 'MIT', 'License': TEXTE_APACHE,
                     'Classifier': ['License :: OSI Approved :: Apache Software License']})
        self.assertEqual(licence_courte(m), 'MIT')

    def test_un_champ_License_court_est_un_identifiant(self):
        self.assertEqual(licence_courte(_Meta(License='AGPL-3.0')), 'AGPL-3.0')

    def test_un_TEXTE_de_licence_n_est_jamais_rendu__le_classifieur_prend_le_relais(self):
        """Le défaut vécu : kokoro / python-doctr / sam3 — texte de 7 à 11 Ko, classifieur propre."""
        m = _Meta(License=TEXTE_APACHE,
                  Classifier=['Programming Language :: Python :: 3',
                              'License :: OSI Approved :: Apache Software License'])
        self.assertEqual(licence_courte(m), 'Apache Software License')

    def test_un_texte_sans_classifieur_rend_None__une_licence_inconnue_se_dit(self):
        """`suno-bark` : 1 061 caractères de texte, aucun classifieur → None, pas un texte."""
        self.assertIsNone(licence_courte(_Meta(License='x' * 1061)))

    def test_un_champ_court_mais_multiligne_est_un_texte(self):
        self.assertIsNone(licence_courte(_Meta(License='MIT License\nCopyright (c) 2024')))

    def test_rien_rend_None(self):
        self.assertIsNone(licence_courte(_Meta()))

    def test_jamais_plus_long_que_le_registre(self):
        m = _Meta(**{'License-Expression': 'A' * 500})
        self.assertLessEqual(len(licence_courte(m)), LICENCE_MAX)


class ValidateurLibraryTest(SimpleTestCase):

    def _body(self, licence):
        return {'identity': {'version': '1.0', 'license': licence},
                'install': {'pip': 'x==1.0'}}

    def test_une_licence_texte_est_REFUSEE(self):
        errs = validate_library_body(self._body(TEXTE_APACHE))
        self.assertTrue(any('TEXTE' in e for e in errs), errs)

    def test_une_licence_identifiant_passe(self):
        self.assertEqual(validate_library_body(self._body('MIT')), [])

    def test_une_licence_absente_passe(self):
        self.assertEqual(validate_library_body(self._body(None)), [])


class CorpusLibraryTest(SimpleTestCase):
    """Invariant sur les FICHIERS du dépôt : ce que l'export a écrit doit se projeter."""

    def test_aucun_manifeste_library_ne_porte_un_texte_de_licence(self):
        dossier = Path(settings.BASE_DIR) / 'manifests' / 'libraries'
        fautifs = []
        for f in sorted(dossier.glob('*.json')):
            m = json.loads(f.read_text(encoding='utf-8'))
            lic = ((m.get('body') or {}).get('identity') or {}).get('license')
            if lic and (len(str(lic)) > LICENCE_MAX or '\n' in str(lic)):
                fautifs.append(f'{f.name} ({len(str(lic))} car.)')
        self.assertEqual(fautifs, [], 'manifeste(s) library à licence-TEXTE — ré-exporter '
                                      'depuis venv_linux après le correctif de l’extracteur')

    def test_no_library_manifest_carries_an_author_longer_than_the_registry(self):
        folder = Path(settings.BASE_DIR) / 'manifests' / 'libraries'
        offenders = []
        for f in sorted(folder.glob('*.json')):
            m = json.loads(f.read_text(encoding='utf-8'))
            author = ((m.get('body') or {}).get('identity') or {}).get('author')
            if author and len(str(author)) > AUTHOR_MAX:
                offenders.append(f'{f.name} ({len(str(author))} car.)')
        self.assertEqual(offenders, [], 'ré-exporter depuis venv_linux (`author_name` le borne)')


# Douze « Nom <adresse> », la forme qu'a `pydantic` (513 caractères) : seul `Author-email` rempli.
_MANY_AUTHORS = ', '.join(f'Contributor Number{i} <contributor{i}@example.org>' for i in range(12))


class AuthorNameTest(SimpleTestCase):
    """L'auteur tient dans le registre (`Library.author`, 200) sans rien inventer (2026-11-06)."""

    def test_a_declared_author_that_fits_is_kept_as_declared(self):
        self.assertEqual('Jane Doe <jane@example.org>',
                         author_name(_Meta(**{'Author-email': 'Jane Doe <jane@example.org>'})))
        self.assertEqual('GGML', author_name(_Meta(Author='GGML', **{'Author-email': 'x <x@y.z>'})))

    def test_too_long_keeps_whole_names_without_addresses_and_marks_the_cut(self):
        author = author_name(_Meta(**{'Author-email': _MANY_AUTHORS}))
        self.assertLessEqual(len(author), AUTHOR_MAX)
        self.assertNotIn('@', author)
        self.assertTrue(author.startswith('Contributor Number0, Contributor Number1'), author)
        self.assertTrue(author.endswith(' …'), author)

    def test_nothing_declared_gives_none(self):
        self.assertIsNone(author_name(_Meta()))

    def test_the_validator_rejects_an_author_too_long_for_the_registry(self):
        body = {'identity': {'version': '1.0', 'author': 'x' * (AUTHOR_MAX + 1)},
                'install': {'pip': 'x==1.0'}}
        self.assertTrue(any('author' in e for e in validate_library_body(body)))


class EveryImportedLibraryIsSeededTest(SimpleTestCase):
    """Décision de Fabien (2026-11-06) : « si des librairies sont utilisées dans les applications
    de WAMA, elles doivent être dans le registre des librairies ». Ce qui est tenu ici :
      • la mesure lit les TROIS mondes et ignore le code tiers vendorisé (ses imports sont ses
        dépendances) ;
      • rien ne reste à semer (`library_index.unseeded()`) ;
      • un import sans distribution installée est DÉCLARÉ ici, avec sa raison — la liste ne fait
        que descendre (un module résolu ou retiré la fait rougir : retirer sa ligne).
    Les deux derniers lisent le venv : le corpus `library` s'extrait de venv_linux, le runtime."""

    UNRESOLVED = {
        'django_redis': "chemin Redis de la console, paquet absent des deux venvs (`mecanismes.py`, "
                        "mécanisme `console`) — mort",
        'locate_anything_worker': "script de WAMA (`scripts/`), chargé par le backend — pas une "
                                  "librairie",
        'pypdf': "repli de `media_probe` après PyMuPDF ; seul PyPDF2 est installé — mort",
        # `rosbags` en est sorti le 2026-11-06 : installé par la route (décision de Fabien).
    }

    def test_the_scan_reads_the_three_worlds_and_skips_the_vendored_engines(self):
        from wama.common.services.library_index import RACINES, code_files
        self.assertEqual({'wama', 'wama_lab', 'wama_data'}, set(RACINES))
        vendor = Path(settings.BACKEND_VENDOR_DIR)
        files = list(code_files())
        self.assertFalse([f for f in files if f.is_relative_to(vendor)])
        self.assertTrue(any(f.is_relative_to(Path(settings.BASE_DIR) / 'wama_data') for f in files))

    @skipUnless(sys.platform.startswith('linux'), 'le corpus library s’extrait de venv_linux')
    def test_every_distribution_the_code_imports_is_in_the_registry(self):
        from wama.common.services.library_index import unseeded
        self.assertEqual([], unseeded(), 'semer par la route : manifest_export --kind library <clé>')

    @skipUnless(sys.platform.startswith('linux'), 'le corpus library s’extrait de venv_linux')
    def test_the_imports_without_a_distribution_are_the_declared_ones(self):
        from wama.common.services.library_index import non_resolus
        self.assertEqual(sorted(self.UNRESOLVED), non_resolus())


class JambeBackendsDesRequiresTest(TestCase):
    """La 2ᵉ jambe du `requires` d'app : modèle → backend résolu → paquets déclarés → librairies.

    POURQUOI (2026-09-07) : depuis que les backends vivent au substrat, la jambe « le dossier de
    l'app importe » ne voit plus torch/diffusers/soundfile — les 8 manifestes d'apps à backends
    perdaient leurs librairies au premier export. La dépendance suit le lien DÉCLARÉ, pas
    l'emplacement d'un fichier. Sème ses cas (la base de test est vide) ; ne dépend d'aucune
    distribution installée dans CE venv : `PIP_PACKAGES` nomme des distributions directement.
    """

    def _semer(self, cle, moteur):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(          # même semis que tests_backend_inventory
            model_key=cle, name=cle, model_type='image', source=cle.split(':')[0],
            is_available=True, is_downloaded=True,
            composition={'runtime': {'engine': moteur}})

    def test_un_modele_resolu_apporte_les_distributions_de_son_backend(self):
        """`deepface` : un seul backend le pilote, `PIP_PACKAGES = ['deepface', 'tf-keras>=2.21']`
        — `deepface` est semé au corpus, `tf-keras` ne l'est pas : seule la semée est citée."""
        from wama.common.services.library_index import librairies_des_backends, semees
        self.assertIn('deepface', semees(), 'le cas suppose deepface semé au corpus')
        self._semer('face_analyzer:deepface-age', 'deepface')
        libs = librairies_des_backends(['face_analyzer:deepface-age'])
        self.assertIn('deepface', libs)
        self.assertNotIn('tf-keras', libs, 'une distribution NON semée ne se cite pas')

    def test_un_modele_sans_backend_n_apporte_rien(self):
        from wama.common.services.library_index import librairies_des_backends
        self._semer('x:sans-moteur', '')
        self.assertEqual(librairies_des_backends(['x:sans-moteur', 'x:inexistant']), [])

    def test_le_socle_plateforme_reste_exclu(self):
        """`diffusers` déclare `REQUIRED_PACKAGES = ['torch', 'diffusers', 'numpy']` : numpy est
        du SOCLE — jamais cité, même semé (même règle que la 1ʳᵉ jambe)."""
        from wama.common.services.library_index import librairies_des_backends, SOCLE_PLATEFORME
        self._semer('imager:qwen-image-2', 'diffusers')
        libs = librairies_des_backends(['imager:qwen-image-2'])
        self.assertFalse(set(libs) & SOCLE_PLATEFORME, libs)


class ModelLibrariesSinglePathTest(TestCase):
    """Modèle → librairies : UNE dérivation (`library_index.model_libraries`), que lisent le
    manifeste de modèle et la jambe backends d'une app (2026-11-06).

    Le manifeste de modèle avait SA lecture : le premier backend du moteur, et les noms de
    `pip_install_spec` pris pour des distributions. Mesuré ce jour-là : 124 manifestes de modèle
    sur 627 ne requéraient pas ce que la jambe d'app leur trouvait — `reader:doctr` sans
    `python-doctr`, pyannote sans `pyannote-audio`, les modèles `loaded_by` sans rien.
    """

    def test_a_pip_specifier_names_its_distribution(self):
        """`pyannote.audio>=3.3.1` : la lecture coupée au seul `==` gardait la contrainte."""
        from wama.common.services.library_index import seeded_libraries
        self.assertEqual(['pyannote-audio'],
                         seeded_libraries(distributions=['pyannote.audio>=3.3.1']))

    def test_an_import_name_is_read_through_the_installed_distribution(self):
        """`doctr` est un nom d'IMPORT ; la librairie semée est `python-doctr`. Contre-épreuve :
        lu comme un nom de distribution, il ne désigne rien."""
        from wama.common.services.library_index import seeded_libraries
        self.assertEqual(['python-doctr'], seeded_libraries(modules=['doctr']))
        self.assertEqual([], seeded_libraries(distributions=['doctr']))

    def test_the_engine_reads_the_distribution_the_venv_installs_for_it(self):
        """`onnxruntime` est AUSSI semé (la version processeur) : le requérir pousserait à
        l'installer à côté de la version GPU, qu'elle masque (patch n° 10). Le moteur se lit
        donc d'abord comme un nom d'import."""
        from wama.common.services.library_index import engine_libraries, semees
        self.assertIn('onnxruntime', semees(), 'le cas suppose les deux semées')
        self.assertEqual(['onnxruntime-gpu'], engine_libraries('onnxruntime'))
        self.assertEqual(['faster-whisper'], engine_libraries('faster-whisper'))
        self.assertEqual([], engine_libraries('moteur-fantome'))

    def test_a_backend_requires_what_its_install_contract_names(self):
        """`DoctrBackend` ne déclare que `REQUIRED_PACKAGES = ['doctr']` : la librairie se lit
        par son nom d'import (le manifeste de `reader:doctr` sortait sans elle)."""
        from wama.common.backends.manager import backend_for_engine
        from wama.common.services.library_index import executor_libraries
        self.assertEqual(['python-doctr'], executor_libraries(backend_for_engine('doctr')))

    def _row(self, key, runtime):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(model_key=key, name=key, model_type='vision',
                                      source=key.split(':')[0], is_available=True,
                                      is_downloaded=True, composition={'runtime': runtime})

    def test_the_app_leg_contains_the_model_leg(self):
        from wama.common.services.library_index import librairies_des_backends, model_libraries
        row = self._row('reader:doctr', {'engine': 'doctr'})
        model = model_libraries(row)
        self.assertEqual(['python-doctr'], model)
        self.assertTrue(set(model) <= set(librairies_des_backends(['reader:doctr'])))

    def test_a_loader_brings_its_engine_not_every_import_of_its_module(self):
        """Le banc importe aussi ultralytics et transformers pour d'AUTRES mesures que LPIPS :
        la jambe d'app ne mesure pas le module d'un `loaded_by`, elle prend son moteur."""
        from wama.common.services.library_index import librairies_des_backends
        self._row('pytorch_download:lpips-alexnet',
                  {'engine': 'lpips', 'loaded_by': 'wama.model_manager.services.bench'})
        self.assertEqual(['lpips'], librairies_des_backends(['pytorch_download:lpips-alexnet']))
