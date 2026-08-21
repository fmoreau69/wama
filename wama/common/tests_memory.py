"""
WAMA Common — Tests de la brique MÉMOIRE & RAG (`common/memory/`). Doc : `WAMA_MEMORY.md`.

POURQUOI CE FICHIER EXISTE, ET POURQUOI ICI. La brique a été construite le 2026-08-20/21 avec
six suites de fumée qui vivaient dans un dossier temporaire. Elles ont validé le travail sur le
moment, puis **le dossier a été vidé** : ~130 contrôles perdus, et surtout plus rejouables par
personne. Un test qui ne survit pas à la session ne protège rien — il rassure son auteur.
Les invariants sont donc réécrits ici, versionnés, sur BASE DE TEST (aucune dépendance aux
données réelles, aucun risque pour elles).

CE QU'ON PROTÈGE EN PRIORITÉ : les invariants de GOUVERNANCE (un écrit LLM ne devient pas un
fait tout seul), la SÉPARATION des deux natures (un souvenir ne se purge pas), l'ISOLATION entre
utilisateurs, et les DEUX DÉFAUTS DE RAPPEL réellement rencontrés — ils sont devenus des tests
de non-régression, pas des anecdotes de commit.

⚠ AUCUN APPEL DE MODÈLE : tout est en `embed=False` / `semantic=False`. Un test ne doit jamais
charger un modèle sur la machine de quelqu'un (leçon du 2026-08-20, §5bis).

Lancer : `python manage.py test wama.common.tests_memory` (venv WSL2).
"""

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.memory import expire, forget, merge, recall, remember
from wama.common.memory.index import decouper
from wama.common.models import MemoryItem, RagChunk, ScopedVisibility


class GouvernanceTests(TestCase):
    """Ce qui empêche une sortie de modèle de devenir un fait."""

    def setUp(self):
        self.u = User.objects.create_user('memo_gouv', password='x')

    def test_ecrit_llm_invisible_tant_que_non_approuve(self):
        # Mesure du 2026-07-17 : sur 6 audits wama-dev-ai, les affirmations d'absence étaient
        # fausses 4 fois sur 6. Un magasin qui gobe ces sorties se corrompt en une nuit.
        brouillon = remember('Le backend X casse a l import', kind=MemoryItem.KIND_SEMANTIC,
                             provenance=MemoryItem.PROV_DEV_AI, user=self.u, embed=False)
        self.assertIsNotNone(brouillon)
        self.assertIsNone(brouillon.approved_at)
        trouves = recall('backend casse import', user=self.u, semantic=False, include_rag=False)
        self.assertNotIn(brouillon.pk, [h.obj.pk for h in trouves])

    def test_approbation_sans_approbateur_refusee(self):
        """`approved=True` sans `approved_by` est le trou par lequel un LLM s'auto-valide."""
        item = remember('tentative auto-approbation', kind=MemoryItem.KIND_SEMANTIC,
                        provenance=MemoryItem.PROV_DEV_AI, user=self.u,
                        approved=True, embed=False)
        self.assertIsNone(item.approved_at)

    def test_projection_peut_s_auto_approuver(self):
        """Seule provenance qui en a le droit : elle ne fait que pointer un fait déjà en base."""
        item = remember('Dans converter, sur Job #1 : un resultat a ete produit',
                        kind=MemoryItem.KIND_EPISODIC, provenance=MemoryItem.PROV_PROJECTION,
                        user=self.u, approved=True, embed=False)
        self.assertIsNotNone(item.approved_at)

    def test_ecriture_sans_gpu_ne_pose_aucun_vecteur(self):
        item = remember('un fait quelconque', kind=MemoryItem.KIND_SEMANTIC,
                        provenance=MemoryItem.PROV_HUMAN, user=self.u,
                        approved=True, approved_by=self.u, embed=False)
        self.assertIsNone(item.embedding)
        self.assertEqual(item.embedding_model, '')


class CycleDeVieTests(TestCase):
    """Les deux natures ont des cycles OPPOSÉS — c'est la raison des deux tables."""

    def setUp(self):
        self.u = User.objects.create_user('memo_cycle', password='x')
        self.item = remember('Fabien exporte les transcriptions en PDF',
                             kind=MemoryItem.KIND_SEMANTIC,
                             provenance=MemoryItem.PROV_HUMAN, user=self.u,
                             approved=True, approved_by=self.u, embed=False)

    def test_forget_invalide_mais_ne_supprime_pas(self):
        """Détruire la ligne détruirait la trace de ce qui était tenu pour vrai."""
        forget(self.item, reason='test')
        self.assertTrue(MemoryItem.objects.filter(pk=self.item.pk).exists())
        self.assertIsNotNone(MemoryItem.objects.get(pk=self.item.pk).valid_to)
        trouves = recall('transcriptions PDF', user=self.u, semantic=False, include_rag=False)
        self.assertNotIn(self.item.pk, [h.obj.pk for h in trouves])

    def test_expire_n_atteint_jamais_un_souvenir_approuve(self):
        """Règle née de la purge du 2026-08-19 qui avait détruit 13 évaluations LLM."""
        resume = expire(jours_non_approuve=0, dry_run=False)
        self.assertTrue(MemoryItem.objects.filter(pk=self.item.pk).exists())
        self.assertNotIn(self.item.pk, [])   # lisibilité : l'item approuvé survit
        self.assertIsInstance(resume, dict)

    def test_merge_propose_et_n_ecrit_rien(self):
        avant = MemoryItem.objects.count()
        propositions = merge(list(MemoryItem.objects.filter(user=self.u)))
        self.assertIsInstance(propositions, list)
        self.assertEqual(MemoryItem.objects.count(), avant)

    def test_dedup_par_content_hash(self):
        doublon = remember('Fabien exporte les transcriptions en PDF',
                           kind=MemoryItem.KIND_SEMANTIC,
                           provenance=MemoryItem.PROV_HUMAN, user=self.u,
                           approved=True, approved_by=self.u, embed=False)
        self.assertEqual(doublon.pk, self.item.pk)


class IsolationTests(TestCase):
    """Le scope n'est pas une option : c'est ce qui rend la mémoire utilisable en labo."""

    def setUp(self):
        self.a = User.objects.create_user('memo_a', password='x')
        self.b = User.objects.create_user('memo_b', password='x')
        remember('secret de A sur les chevaux', kind=MemoryItem.KIND_SEMANTIC,
                 provenance=MemoryItem.PROV_HUMAN, user=self.a,
                 approved=True, approved_by=self.a, embed=False)

    def test_un_autre_utilisateur_ne_voit_rien(self):
        self.assertEqual(recall('chevaux', user=self.b, semantic=False, include_rag=False), [])

    def test_le_proprietaire_voit(self):
        trouves = recall('chevaux', user=self.a, semantic=False, include_rag=False)
        self.assertTrue(trouves)


class RappelLexicalTests(TestCase):
    """NON-RÉGRESSION des deux défauts réellement rencontrés le 2026-08-21."""

    def setUp(self):
        self.u = User.objects.create_user('memo_lex', password='x')
        for texte in ('le formulaire de consentement doit etre signe',
                      'la voiture roule sur la chaussee mouillee'):
            remember(texte, kind=MemoryItem.KIND_SEMANTIC, provenance=MemoryItem.PROV_HUMAN,
                     user=self.u, approved=True, approved_by=self.u, embed=False)

    def test_requete_sans_correspondance_ne_rend_RIEN(self):
        """
        DÉFAUT 1. Postgres rend un rang PLANCHER de 1e-20 sur TOUTES les lignes quand aucun terme
        n'est connu du dictionnaire — et `rank > 0` laissait donc tout passer. Le Hook B injectait
        du contexte hors-sujet dans un prompt sans la moindre correspondance.
        """
        self.assertEqual(recall('xyzzy quuxbaz', user=self.u, semantic=False,
                                include_rag=False), [])

    def test_question_en_langage_naturel_trouve(self):
        """
        DÉFAUT 2. `plainto_tsquery` fait un ET : une question exigeait TOUS ses mots dans le MÊME
        fragment, donc ne trouvait jamais rien. Les termes sont désormais combinés en OU.
        """
        trouves = recall('que disent mes entretiens sur le consentement',
                         user=self.u, semantic=False, include_rag=False)
        self.assertTrue(trouves, "une question en langage naturel doit trouver ses fragments")


class DecoupageTests(TestCase):
    """Le découpage RAG — pur, sans base ni modèle."""

    def test_texte_vide_et_court(self):
        self.assertEqual(decouper(''), [])
        self.assertEqual(decouper('Une phrase.'), ['Une phrase.'])

    def test_texte_long_est_decoupe_avec_recouvrement(self):
        phrase = 'Le systeme de transcription utilise un modele pour les fichiers audio. '
        frags = decouper(phrase * 40)
        self.assertGreater(len(frags), 1)
        self.assertTrue(all(f.strip() for f in frags))
        # Sans recouvrement, une phrase coupee en deux devient introuvable : ni l'un ni l'autre
        # des fragments ne la contient en entier.
        self.assertTrue(any(mot in frags[1] for mot in frags[0][-40:].split()[:3]))

    def test_aucun_fragment_ne_depasse_la_taille_avec_marge(self):
        frags = decouper('Phrase de test. ' * 200)
        self.assertTrue(all(len(f) <= 900 for f in frags), [len(f) for f in frags])


class FragmentRagTests(TestCase):
    """Un `RagChunk` est RE-DÉRIVABLE — c'est ce qui autorise ce qu'un souvenir interdit."""

    def setUp(self):
        self.u = User.objects.create_user('memo_rag', password='x')
        RagChunk.objects.create(
            content='la notice d information et le formulaire de consentement',
            content_hash='h1', source_kind='doc', source_id='transcriber:1', ordinal=0,
            user=self.u, visibility=ScopedVisibility.VIS_PRIVATE)

    def test_le_fragment_est_rappelable(self):
        trouves = recall('formulaire de consentement', user=self.u, semantic=False,
                         include_memory=False)
        self.assertTrue(trouves)
        self.assertEqual(trouves[0].source, 'rag')

    def test_un_autre_utilisateur_ne_voit_pas_le_fragment(self):
        autre = User.objects.create_user('memo_rag_b', password='x')
        self.assertEqual(recall('formulaire de consentement', user=autre, semantic=False,
                                include_memory=False), [])
