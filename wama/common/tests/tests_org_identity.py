"""L'IDENTITÉ d'une unité organisationnelle est-elle portable ? (S2, PROFILES_PERMISSIONS §8.6)

`OrgUnit.code` porte un `supannCodeEntite`, qui n'est unique QUE dans son annuaire. Il était
pourtant `unique=True` globalement : deux établissements ayant chacun leur « DSI », le second
était littéralement impossible à créer. C'était le seul point non évolutif du modèle d'accès.

Ouvrir l'unicité ne suffit PAS, et c'est ce que ces tests verrouillent : le jour où une unité
étrangère porte le même code, un `OrgUnit.objects.filter(code=…).first()` interne en choisirait
une AU HASARD (l'`ordering` du modèle porte sur `name`) sans rien signaler. On aurait déplacé un
défaut d'unicité vers une panne muette — exactement le motif `/model-manager/` refermé le même
jour. D'où deux familles de propriétés ici : la coexistence (ce qu'on ouvre) ET la résolution
locale (ce qu'on referme en même temps).
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from wama.common.models import LOCAL_AUTHORITY, OrgUnit, user_scope_org_ids


def _affilier(user, *codes):
    prof = user.profile
    prof.org_entity_code = codes[0]
    prof.org_affiliations = list(codes)
    prof.save(update_fields=['org_entity_code', 'org_affiliations'])
    return prof


class CoexistenceDesAutoritesTests(TestCase):
    """Ce que le correctif OUVRE : deux annuaires peuvent porter le même code."""

    def test_deux_etablissements_peuvent_avoir_la_meme_DSI(self):
        # Impossible avant le 27/08 : `code` était unique globalement.
        ici = OrgUnit.objects.create(code='DSI', name='DSI (ici)', unit_type='service')
        ailleurs = OrgUnit.objects.create(code='DSI', authority='autre-univ.fr',
                                          name='DSI (ailleurs)', unit_type='service')
        self.assertNotEqual(ici.pk, ailleurs.pk)
        self.assertEqual(OrgUnit.objects.filter(code='DSI').count(), 2)

    def test_le_meme_code_DANS_la_meme_autorite_reste_interdit(self):
        # La contre-épreuve : on a remplacé une unicité par une autre, pas supprimé l'unicité.
        # Sans ce test, avoir simplement retiré `unique=True` passerait le test précédent.
        OrgUnit.objects.create(code='DUP', name='Un', unit_type='service')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OrgUnit.objects.create(code='DUP', name='Deux', unit_type='service')

    def test_l_autorite_par_defaut_est_celle_de_cette_instance(self):
        # Les lignes déjà en base n'ont pas d'autorité : la migration devait être neutre.
        u = OrgUnit.objects.create(code='DEF', name='Défaut', unit_type='labo')
        self.assertEqual(u.authority, LOCAL_AUTHORITY)
        self.assertIn(u, OrgUnit.local())


class ResolutionLocaleTests(TestCase):
    """Ce que le correctif REFERME : un code nu se résout chez soi, jamais chez le voisin."""

    def setUp(self):
        self.mien = OrgUnit.objects.create(code='LESCOT', name='AAA local', unit_type='labo')
        # `name` volontairement AVANT le mien dans l'ordre alphabétique : l'`ordering = ['name']`
        # du modèle ferait remonter l'étranger en premier avec un `.first()` non filtré. Le test
        # échouerait donc VRAIMENT si la résolution n'était pas scopée — il ne passe pas par chance.
        self.etranger = OrgUnit.objects.create(code='LESCOT', authority='autre-univ.fr',
                                               name='AAA etranger', unit_type='labo')

    def test_le_scope_d_un_utilisateur_ne_ramasse_que_ses_unites(self):
        u = User.objects.create_user('org_local', password='x')
        _affilier(u, 'LESCOT')
        ids = user_scope_org_ids(User.objects.get(pk=u.pk))
        self.assertIn(self.mien.id, ids)
        self.assertNotIn(self.etranger.id, ids,
                         "une unité d'un AUTRE établissement est entrée dans le périmètre "
                         "de partage — c'est une fuite de visibilité, pas un détail")

    def test_la_resolution_RAG_choisit_l_unite_locale(self):
        from wama.common.memory.index import _resolve_unit
        u = User.objects.create_user('org_rag', password='x')
        _affilier(u, 'LESCOT')
        unite, err = _resolve_unit(User.objects.get(pk=u.pk), 'LESCOT')
        self.assertEqual(err, '')
        self.assertEqual(unite.id, self.mien.id)

    def test_aucune_resolution_interne_ne_contourne_local(self):
        # 🔴 Propriété de SOURCE, pas de comportement — parce que le défaut qu'on traque est
        # l'oubli d'un site, pas la logique d'un site. Un `OrgUnit.objects.filter(code=…)` ajouté
        # demain resterait muet à l'exécution tant qu'aucune unité étrangère n'existe : le jour où
        # elle existe, il est trop tard. Seul `models.py` a le droit d'interroger sans scope
        # (c'est lui qui définit `local()` et `resolve_qualified()`).
        racine = Path(settings.BASE_DIR)
        motif = re.compile(r'OrgUnit\.objects\.filter\(\s*code')
        autorises = {racine / 'wama' / 'common' / 'models.py'}
        fautifs = []
        for f in list(racine.glob('wama/**/*.py')) + list(racine.glob('wama_lab/**/*.py')):
            if f in autorises or '/migrations/' in f.as_posix() or f.name.startswith('tests'):
                continue
            try:
                texte = f.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            if motif.search(texte):
                fautifs.append(f.relative_to(racine).as_posix())
        self.assertEqual(sorted(fautifs), [],
                         "résolution d'unité NON scopée à l'autorité : utiliser `OrgUnit.local()` "
                         f"(interne) ou `OrgUnit.resolve_qualified()` (code venu d'un manifeste) — {fautifs}")


class CodeQualifieTests(TestCase):
    """La forme EXPORTÉE — celle sous laquelle le code sort de WAMA et voyage."""

    def test_sans_autorite_la_forme_exportee_reste_le_code_nu(self):
        # La compatibilité ascendante EST la propriété : les manifestes déjà écrits portent un
        # code nu, et le correctif ne doit pas en faire des manifestes illisibles.
        u = OrgUnit.objects.create(code='CFR - LESCOT', name='LESCOT', unit_type='labo')
        self.assertEqual(u.qualified_code, 'CFR - LESCOT')

    def test_avec_autorite_la_forme_exportee_est_globalement_unique(self):
        a = OrgUnit.objects.create(code='DSI', name='A', unit_type='service')
        b = OrgUnit.objects.create(code='DSI', authority='autre-univ.fr', name='B',
                                   unit_type='service')
        self.assertNotEqual(a.qualified_code, b.qualified_code)
        self.assertEqual(b.qualified_code, 'autre-univ.fr:DSI')

    def test_un_aller_retour_export_import_retombe_sur_la_MEME_unite(self):
        # Le seul test qui prouve la portabilité : ce qu'on écrit dans un manifeste doit
        # redésigner l'unité de départ, y compris quand une homonyme étrangère existe.
        for unite in (OrgUnit.objects.create(code='EQ', name='ZZZ locale', unit_type='equipe'),
                      OrgUnit.objects.create(code='EQ', authority='autre-univ.fr',
                                             name='AAA etrangere', unit_type='equipe')):
            with self.subTest(autorite=unite.authority or '(locale)'):
                self.assertEqual(OrgUnit.resolve_qualified(unite.qualified_code), unite)

    def test_un_code_nu_venu_d_un_ancien_manifeste_designe_l_unite_locale(self):
        locale = OrgUnit.objects.create(code='OLD', name='ZZZ locale', unit_type='labo')
        OrgUnit.objects.create(code='OLD', authority='autre-univ.fr', name='AAA etrangere',
                               unit_type='labo')
        self.assertEqual(OrgUnit.resolve_qualified('OLD'), locale)

    def test_un_code_inconnu_ou_vide_ne_designe_rien(self):
        self.assertIsNone(OrgUnit.resolve_qualified('INEXISTANT'))
        self.assertIsNone(OrgUnit.resolve_qualified(''))
        self.assertIsNone(OrgUnit.resolve_qualified(None))

    def test_le_manifeste_function_exporte_la_forme_qualifiee(self):
        # Le point de sortie réel (§8.6) : `Manifest.scope_org_unit` est un CharField qui voyage,
        # pas une FK. C'est là — et seulement là — que le code doit porter son autorité.
        from wama.common.models import UserFunction
        from wama.common.manifests.builtin.function import extract_function
        unite = OrgUnit.objects.create(code='DSI', authority='autre-univ.fr', name='DSI',
                                       unit_type='service')
        owner = User.objects.create_user('fn_owner', password='x')
        UserFunction.objects.create(key='fn.test.export', name='Test export', owner=owner,
                                    visibility='unit', scope_org_unit=unite)
        env = extract_function('fn.test.export')
        self.assertIsNotNone(env, "la fonction n'a pas été extraite : le test ne mesurerait rien")
        self.assertEqual(env.get('scope_org_unit'), 'autre-univ.fr:DSI')
