"""
Page « Mes souvenirs » + accesseur `store.list_souvenirs` (13ᵉ registre, 2026-09-09).

Ce que ces tests protègent, et pourquoi chacun existe :

1. **La liste ACTIVE ne doit jamais diverger du rappel.** Elle réutilise `_visible_memory` ;
   si quelqu'un la remplace un jour par une requête « équivalente », la page montrera des
   souvenirs que l'assistant ne verra pas — on déboguerait alors une différence entre deux
   vérités au lieu d'une seule.
2. **La file de revue n'est PAS scopée** (délibéré : les souvenirs importés portent
   `user=NULL` + `private`, qu'aucune branche de `scoped_visible_q` ne matche). Sa seule garde
   est le `is_staff` de la vue. Une garde qui tient à une ligne de vue se teste, sinon elle
   disparaîtra au premier remaniement sans que rien ne plante.
3. **Un non approuvé ne doit JAMAIS entrer dans la liste active** — c'est la gouvernance
   `WAMA_MEMORY §6`, et son coût est mesuré (4 affirmations fausses sur 6 audits).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .memory.store import list_souvenirs
from .models import MemoryItem


def _souvenir(**kw):
    """Écrit en direct : `remember()` embarquerait un vecteur, donc le GPU, dans un test."""
    base = dict(kind=MemoryItem.KIND_SEMANTIC, provenance='test', content='contenu',
                subject='sujet', visibility=MemoryItem.VIS_PRIVATE)
    base.update(kw)
    return MemoryItem.objects.create(**base)


class ListSouvenirsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.moi = U.objects.create_user('moi', password='x')
        cls.autre = U.objects.create_user('autre', password='x')

    def test_la_liste_active_ne_rend_que_les_approuves(self):
        _souvenir(user=self.moi, content='approuvé', approved_at=timezone.now())
        _souvenir(user=self.moi, content='brouillon')
        contenus = [s['content'] for s in list_souvenirs(self.moi)]
        self.assertIn('approuvé', contenus)
        self.assertNotIn('brouillon', contenus,
                         "un souvenir non approuvé est invisible au rappel : la page ne doit "
                         "pas le montrer comme actif")

    def test_la_liste_active_ne_montre_pas_le_souvenir_dun_autre(self):
        _souvenir(user=self.autre, content='chez autre', approved_at=timezone.now())
        self.assertEqual([], [s['content'] for s in list_souvenirs(self.moi)])

    def test_la_file_de_revue_voit_les_souvenirs_SANS_PROPRIETAIRE(self):
        """Le cas qui a motivé la page : 25 souvenirs importés portaient `user=NULL`.

        Scopés, ils seraient invisibles à tout le monde — la file de revue serait vide alors
        que la gouvernance attend une validation humaine.
        """
        _souvenir(user=None, provenance='dev-ai', content='importé sans propriétaire')
        contenus = [s['content'] for s in list_souvenirs(self.moi, en_attente=True)]
        self.assertIn('importé sans propriétaire', contenus)

    def test_un_souvenir_remplace_sort_des_deux_listes(self):
        remplacant = _souvenir(user=self.moi, content='neuf', approved_at=timezone.now())
        _souvenir(user=self.moi, content='vieux', superseded_by=remplacant)
        self.assertNotIn('vieux', [s['content'] for s in list_souvenirs(self.moi)])
        self.assertNotIn('vieux', [s['content'] for s in list_souvenirs(self.moi, en_attente=True)])


class PageSouvenirsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.simple = U.objects.create_user('simple', password='x')
        cls.staff = U.objects.create_user('chef', password='x', is_staff=True)
        _souvenir(user=None, provenance='dev-ai', content='EN-ATTENTE-SECRET')

    def test_la_page_exige_une_connexion(self):
        r = self.client.get(reverse('common:souvenirs'))
        self.assertEqual(302, r.status_code)

    def test_un_simple_connecte_ne_voit_PAS_la_file_de_revue(self):
        """La file n'est pas scopée : sans cette garde, elle exposerait les souvenirs de tous."""
        self.client.force_login(self.simple)
        corps = self.client.get(reverse('common:souvenirs')).content.decode()
        self.assertNotIn('EN-ATTENTE-SECRET', corps)
        self.assertNotIn('File de revue', corps)

    def test_le_staff_voit_la_file_de_revue(self):
        self.client.force_login(self.staff)
        corps = self.client.get(reverse('common:souvenirs')).content.decode()
        self.assertIn('EN-ATTENTE-SECRET', corps)
        self.assertIn('File de revue', corps)


class RegistresMemoireTest(TestCase):
    def test_souvenirs_et_prompts_sont_declares_avec_leur_page(self):
        """Un registre sans `url_name` est le défaut que `skills` a porté jusqu'au 27/08 :
        un catalogue que personne ne peut ouvrir."""
        from .registries import overview
        par_cle = {r['key']: r for r in overview()}
        for cle, url in (('souvenirs', 'common:souvenirs'),
                         ('prompts', 'common:skills_catalog')):
            with self.subTest(registre=cle):
                self.assertIn(cle, par_cle, f"registre `{cle}` absent de la carte")
                self.assertEqual(url, par_cle[cle]['url_name'])

    def test_le_compteur_de_prompts_compte_les_CHAMPS_pas_les_apps(self):
        """⚠ Le total des champs ÉGALE le nombre d'apps aujourd'hui (6 et 6) — par coïncidence.

        Mesuré le 2026-09-09 : `imager` déclare DEUX champs (`prompt`, `negative_prompt`) et
        `synthesizer` ZÉRO — liste vide DÉLIBÉRÉE (décision §16.6 : un texte TTS ne se traduit
        jamais, on prononce ce que l'utilisateur a écrit). Les deux écarts se compensent.
        Comparer les deux nombres ne prouverait donc RIEN ; on vérifie la FORME du comptage.
        """
        from .registries import overview
        from .utils.app_metadata import PROMPT_TARGETS

        attendu = sum(len(t) for t in PROMPT_TARGETS.values())
        total = {r['key']: r for r in overview()}['prompts']['total']
        self.assertEqual(attendu, total)

        multi = [a for a, t in PROMPT_TARGETS.items() if len(t) > 1]
        vides = [a for a, t in PROMPT_TARGETS.items() if not t]
        self.assertTrue(multi, "aucune app multi-champs : un comptage par app passerait le test")
        self.assertTrue(vides, "aucune app à liste vide — l'« explicitement rien » a disparu, "
                               "ce qui change le sens du compteur")
