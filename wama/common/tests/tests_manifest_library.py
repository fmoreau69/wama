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

from wama.common.manifests.builtin.library import (
    LICENCE_MAX, licence_courte, validate_library_body,
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
