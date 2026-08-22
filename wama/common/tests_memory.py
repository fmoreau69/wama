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
from wama.common.memory.index import (ajouter_au_rag, decouper, lister_rag,
                                      retirer_du_rag)
from wama.common.models import MemoryItem, OrgUnit, RagChunk, ScopedVisibility


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


def _affilier(user, *codes):
    """Pose les affiliations d'unité sur le profil (auto-créé par signal `post_save`)."""
    prof = user.profile
    prof.org_affiliations = list(codes)
    prof.save()


class EntreeExpliciteRagTests(TestCase):
    """
    CORRECTION DE CONCEPTION du 2026-08-21 : l'entrée au RAG est un GESTE, jamais un balayage.

    La première version indexait les sorties de TOUTES les apps de TOUS les utilisateurs
    (939 fragments écrits sans qu'aucun n'ait rien demandé — purgés). Ces tests protègent le
    remplacement : `ajouter_au_rag` est le SEUL point d'entrée, au niveau choisi par
    l'utilisateur, et ce qui entre par un geste ressort par un geste (`retirer_du_rag`).
    """

    def setUp(self):
        self.labo = OrgUnit.objects.create(code='LAB-TEST', name='Labo test', unit_type='labo')
        self.equipe = OrgUnit.objects.create(code='EQ-TEST', name='Équipe test',
                                             unit_type='equipe', parent=self.labo)
        self.a = User.objects.create_user('rag_a', password='x')
        self.b = User.objects.create_user('rag_b', password='x')
        _affilier(self.a, 'EQ-TEST')      # membre de l'ÉQUIPE (le labo est son ancêtre)
        _affilier(self.b, 'LAB-TEST')     # membre du LABO directement

    def test_niveau_user_par_defaut_prive_et_sans_gpu(self):
        r = ajouter_au_rag(self.a, 'le protocole des essais sur les chevaux miniatures',
                           source_ref='reader#1', source_id='reader:1')
        self.assertEqual(r['etat'], 'indexé')
        chunks = RagChunk.objects.filter(source_id='reader:1')
        self.assertTrue(chunks.exists())
        self.assertTrue(all(c.visibility == ScopedVisibility.VIS_PRIVATE for c in chunks))
        self.assertTrue(all(c.embedding is None for c in chunks))      # jamais de GPU au geste
        # Rappelable par le propriétaire, invisible pour l'autre.
        self.assertTrue(recall('chevaux', user=self.a, semantic=False, include_memory=False))
        self.assertEqual(recall('chevaux', user=self.b, semantic=False, include_memory=False), [])

    def test_niveau_unit_partage_au_labo_et_herite_par_l_equipe(self):
        """LE test du niveau 2 : un doc partagé au LABO est vu d'un membre d'une ÉQUIPE du labo."""
        r = ajouter_au_rag(self.b, 'protocole du laboratoire sur le consentement',
                           source_ref='doc#1', source_id='doc:1', niveau='unit')
        self.assertEqual(r['niveau'], 'unit')
        chunk = RagChunk.objects.get(source_id='doc:1')
        self.assertEqual(chunk.visibility, ScopedVisibility.VIS_UNIT)
        self.assertEqual(chunk.scope_org_unit, self.labo)
        # `a` est membre de l'équipe, dont le labo est l'ancêtre → il voit le doc du labo.
        trouves = recall('consentement', user=self.a, semantic=False, include_memory=False)
        self.assertTrue(trouves, "l'héritage OrgUnit équipe→labo doit ouvrir le doc au membre")

    def test_niveau_unit_sans_affiliation_refuse(self):
        seul = User.objects.create_user('rag_seul', password='x')
        r = ajouter_au_rag(seul, 'texte', source_ref='x', niveau='unit')
        self.assertIn('erreur', r)
        self.assertEqual(RagChunk.objects.filter(user=seul).count(), 0)

    def test_niveau_unit_ambigu_exige_de_nommer_l_unite(self):
        """Multi-entités (précision Fabien) : plusieurs affiliations ⇒ on ne devine JAMAIS."""
        multi = User.objects.create_user('rag_multi', password='x')
        _affilier(multi, 'LAB-TEST', 'EQ-TEST')
        r = ajouter_au_rag(multi, 'texte partagé', source_ref='x', niveau='unit')
        self.assertIn('erreur', r)
        self.assertIn('plusieurs affiliations', r['erreur'])
        # En nommant l'unité, le geste passe.
        r2 = ajouter_au_rag(multi, 'texte partagé', source_ref='x', niveau='unit',
                            org_unit='LAB-TEST')
        self.assertEqual(r2.get('niveau'), 'unit')

    def test_publier_vers_un_ancetre_est_refuse(self):
        """`a` est affilié à l'ÉQUIPE : publier au LABO (ancêtre) = niveau 3/4, pas ouvert."""
        r = ajouter_au_rag(self.a, 'texte', source_ref='x', niveau='unit', org_unit='LAB-TEST')
        self.assertIn('erreur', r)

    def test_idempotence_et_changement_de_niveau_sans_perdre_les_vecteurs(self):
        texte = 'un document stable dont seul le niveau de partage change'
        ajouter_au_rag(self.b, texte, source_ref='d', source_id='doc:2')
        # Simule un réindex passé : le fragment a son vecteur.
        RagChunk.objects.filter(source_id='doc:2').update(embedding=[0.0] * 1024,
                                                          embedding_model='bge-m3')
        r = ajouter_au_rag(self.b, texte, source_ref='d', source_id='doc:2', niveau='unit')
        self.assertEqual(r['etat'], 'inchangé')
        chunk = RagChunk.objects.get(source_id='doc:2')
        self.assertEqual(chunk.visibility, ScopedVisibility.VIS_UNIT)
        self.assertIsNotNone(chunk.embedding,
                             'changer la portée ne doit PAS coûter un réindex')

    def test_contenu_modifie_est_redecoupe(self):
        ajouter_au_rag(self.a, 'premier contenu', source_ref='d', source_id='reader:9')
        r = ajouter_au_rag(self.a, 'un contenu entièrement différent',
                          source_ref='d', source_id='reader:9')
        self.assertEqual(r['etat'], 'réindexé')
        self.assertIn('entièrement différent',
                      RagChunk.objects.get(source_id='reader:9').content)

    def test_retirer_du_rag_ne_touche_que_le_proprietaire(self):
        ajouter_au_rag(self.a, 'document à retirer ensuite', source_ref='d', source_id='reader:5')
        self.assertEqual(retirer_du_rag(self.b, 'reader:5'), 0)     # pas le sien : rien
        self.assertTrue(retirer_du_rag(self.a, 'reader:5') > 0)
        self.assertEqual(RagChunk.objects.filter(source_id='reader:5').count(), 0)

    def test_lister_rag_pour_la_page_de_gestion(self):
        ajouter_au_rag(self.a, 'un premier document', source_ref='reader#7', source_id='reader:7')
        lignes = lister_rag(self.a)
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0]['niveau'], 'user')
        self.assertEqual(lignes[0]['vectorises'], 0)    # signale qu'un reindex est à faire


class NiveauxRappelTests(TestCase):
    """Le SÉLECTEUR de niveaux au rappel : mon RAG, celui du labo, les deux — ou rien."""

    def setUp(self):
        self.labo = OrgUnit.objects.create(code='LAB-N', name='Labo', unit_type='labo')
        self.a = User.objects.create_user('niv_a', password='x')
        self.b = User.objects.create_user('niv_b', password='x')
        _affilier(self.a, 'LAB-N')
        _affilier(self.b, 'LAB-N')
        # `a` possède un doc PRIVÉ ; `b` partage un doc au LABO. Même mot « protocole » dans
        # les deux : c'est le NIVEAU qui discrimine, pas la requête.
        ajouter_au_rag(self.a, 'mes notes personnelles sur le protocole des essais',
                       source_ref='n', source_id='n:1')
        ajouter_au_rag(self.b, 'protocole du laboratoire sur les entretiens',
                       source_ref='l', source_id='l:1', niveau='unit')

    def _ids(self, niveaux):
        hits = recall('protocole', user=self.a, semantic=False, include_memory=False,
                      rag_niveaux=niveaux)
        return {h.obj.source_id for h in hits}

    def test_mon_rag_seulement(self):
        self.assertEqual(self._ids({'user'}), {'n:1'})

    def test_rag_du_labo_seulement_exclut_mes_prives(self):
        # Choix documenté : « le RAG du labo » ≠ « le mien + celui du labo ».
        self.assertEqual(self._ids({'unit'}), {'l:1'})

    def test_les_deux(self):
        self.assertEqual(self._ids({'user', 'unit'}), {'n:1', 'l:1'})

    def test_ne_rien_selectionner_est_legitime(self):
        self.assertEqual(self._ids(set()), set())

    def test_defaut_none_egale_tout_le_visible(self):
        self.assertEqual(self._ids(None), {'n:1', 'l:1'})


class SurfacesDuGesteTests(TestCase):
    """
    JALON 14 — les SURFACES du geste (bouton d'inspecteur + page « Mon RAG »).

    Ce qui est protégé ici n'est pas l'ergonomie mais les INVARIANTS de la décision du 21/08 :
    l'écriture passe par un geste sur UN élément, l'élément doit porter du texte, il doit
    m'appartenir, et le geste est idempotent. Une régression sur l'un d'eux rouvrirait la porte
    que le retrait du balayage avait fermée.

    Le registre de détail est peuplé ICI avec un adapter de test : les vues sont GÉNÉRIQUES
    (elles ne connaissent aucune app), donc les tester à travers une app réelle ferait dépendre
    la garantie d'un gabarit d'app — et masquerait la généricité qu'on veut justement prouver.
    """

    def setUp(self):
        from wama.common.utils.detail_registry import DetailRegistry

        self.u = User.objects.create_user('surf_a', password='x')
        self.autre = User.objects.create_user('surf_b', password='x')
        # Porteur commode : MemoryItem a un FK `user`, donc la garde de propriété est réelle.
        self.item = MemoryItem.objects.create(
            subject='porteur', content='inutilisé', user=self.u,
            provenance=MemoryItem.PROV_PROJECTION)
        self.muet = MemoryItem.objects.create(
            subject='muet', content='inutilisé', user=self.u,
            provenance=MemoryItem.PROV_PROJECTION)
        textes = {self.item.pk: 'le compte rendu de la réunion sur les chevaux miniatures',
                  self.muet.pk: ''}

        def adapter(instance):
            d = {'id': instance.pk, 'status': 'SUCCESS'}
            if textes.get(instance.pk):
                d['result_text'] = textes[instance.pk]
            return d

        avant = dict(DetailRegistry._registry)
        DetailRegistry.register('apptest', MemoryItem, adapter)
        self.addCleanup(lambda: DetailRegistry._registry.clear()
                        or DetailRegistry._registry.update(avant))
        self.client.force_login(self.u)

    def _ajouter(self, pk, **extra):
        return self.client.post('/common/api/rag/ajouter/',
                                dict({'app': 'apptest', 'pk': pk}, **extra))

    def test_le_geste_indexe_le_texte_du_schema_canonique(self):
        r = self._ajouter(self.item.pk)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()['fragments'], 1)
        # `source_id` = <app>:<pk> — c'est lui qui rend le geste idempotent ET qui permet à la
        # page de gestion de remonter à l'élément d'origine.
        chunks = RagChunk.objects.filter(user=self.u, source_id=f'apptest:{self.item.pk}')
        self.assertTrue(chunks.exists())
        self.assertTrue(all(c.embedding is None for c in chunks))   # jamais de GPU au geste

    def test_un_element_sans_texte_n_est_pas_indexable(self):
        r = self._ajouter(self.muet.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(RagChunk.objects.count(), 0)

    def test_l_element_d_un_autre_ne_peut_pas_entrer_dans_mon_rag(self):
        self.item.user = self.autre
        self.item.save(update_fields=['user'])
        self.assertEqual(self._ajouter(self.item.pk).status_code, 403)
        self.assertEqual(RagChunk.objects.count(), 0)

    def test_re_cliquer_ne_duplique_pas(self):
        self._ajouter(self.item.pk)
        n = RagChunk.objects.count()
        r = self._ajouter(self.item.pk)
        self.assertEqual(r.json()['etat'], 'inchangé')
        self.assertEqual(RagChunk.objects.count(), n)

    def test_le_retrait_est_le_pendant_du_geste(self):
        self._ajouter(self.item.pk)
        r = self.client.post('/common/api/rag/retirer/',
                             {'source_id': f'apptest:{self.item.pk}'})
        self.assertGreaterEqual(r.json()['retires'], 1)
        self.assertEqual(RagChunk.objects.count(), 0)

    def test_anonyme_ne_peut_rien_ecrire(self):
        self.client.logout()
        r = self._ajouter(self.item.pk)
        self.assertIn(r.status_code, (302, 403))       # login_required
        self.assertEqual(RagChunk.objects.count(), 0)

    def test_niveau_par_defaut_du_profil_est_applique(self):
        _affilier(self.u, 'LAB-SURF')
        OrgUnit.objects.create(code='LAB-SURF', name='Labo', unit_type='labo')
        prof = self.u.profile
        prof.rag_niveau_defaut = 'unit'
        prof.save()
        self._ajouter(self.item.pk)
        chunk = RagChunk.objects.filter(user=self.u).first()
        self.assertEqual(chunk.visibility, ScopedVisibility.VIS_UNIT)

    def test_preference_de_rappel_distingue_JAMAIS_CHOISI_de_RIEN(self):
        """L'invariant qui a failli être manqué : `null` et `[]` ne veulent pas dire pareil.

        `null` = jamais choisi ⇒ tous les niveaux visibles (comportement historique) ;
        `[]` = décoché volontairement ⇒ ne rien rappeler. Un `default=list` aurait confondu
        les deux et coupé le RAG de tous les profils existants au déploiement.
        """
        self.assertIsNone(self.u.profile.rag_niveaux_rappel)      # profil neuf = jamais choisi
        r = self.client.post('/common/api/rag/preference/',
                             {'rappel_soumis': '1'})              # aucune case cochée
        self.assertEqual(r.status_code, 200)
        self.u.profile.refresh_from_db()
        self.assertEqual(self.u.profile.rag_niveaux_rappel, [])   # RIEN, et non « jamais choisi »

    def test_la_page_de_gestion_liste_ce_que_j_ai_confie(self):
        self._ajouter(self.item.pk)
        r = self.client.get('/common/rag/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['total'], 1)
        self.assertGreaterEqual(r.context['fragments'], 1)
        # Le document est annoncé NON VECTORISÉ tant que le lot n'est pas passé : le taire
        # laisserait croire que le rappel sémantique le trouve déjà.
        self.assertEqual(r.context['en_attente'], 1)

    def test_la_page_ne_montre_que_MES_documents(self):
        self._ajouter(self.item.pk)
        self.client.force_login(self.autre)
        r = self.client.get('/common/rag/')
        self.assertEqual(r.context['total'], 0)


class RattachementMultipleTests(TestCase):
    """
    LE cas réel qui bloquait le niveau labo (mesuré sur le profil de Fabien, 2026-08-22).

    L'annuaire UGE porte les codes HÉRITÉS (« {IFSTTAR}LESCOT ») À CÔTÉ des codes actuels
    (« CFR - LESCOT ») pour le MÊME laboratoire : l'utilisateur a donc plusieurs rattachements
    sans être membre de plusieurs labos. `_resoudre_unite` refuse alors de deviner — à raison,
    un partage parti dans la mauvaise entité ne se voit pas — mais sans réglage d'unité cible le
    niveau labo devenait INATTEIGNABLE. Ces tests protègent la sortie de ce blocage.
    """

    def setUp(self):
        from wama.common.utils.detail_registry import DetailRegistry

        self.actuel = OrgUnit.objects.create(code='CFR - LESCOT', name='LESCOT',
                                             unit_type='labo')
        self.herite = OrgUnit.objects.create(code='{IFSTTAR}LESCOT', name='{IFSTTAR}LESCOT',
                                             unit_type='autre')
        self.u = User.objects.create_user('multi', password='x')
        prof = self.u.profile
        # Trois codes, dont un FANTÔME absent de l'annuaire — exactement le profil mesuré.
        prof.org_affiliations = ['{IFSTTAR}LESCOT', 'CFR - LESCOT', '{EIFFEL}CFR - LESCOT']
        prof.rag_niveau_defaut = 'unit'
        prof.save()

        self.item = MemoryItem.objects.create(subject='p', content='x', user=self.u,
                                              provenance=MemoryItem.PROV_PROJECTION)
        avant = dict(DetailRegistry._registry)
        DetailRegistry.register('apptest', MemoryItem,
                                lambda i: {'id': i.pk, 'result_text': 'compte rendu de réunion'})
        self.addCleanup(lambda: DetailRegistry._registry.clear()
                        or DetailRegistry._registry.update(avant))
        self.client.force_login(self.u)

    def _ajouter(self):
        return self.client.post('/common/api/rag/ajouter/',
                                {'app': 'apptest', 'pk': self.item.pk})

    def test_sans_unite_choisie_le_partage_est_refuse_et_MOTIVE(self):
        r = self._ajouter()
        self.assertEqual(r.status_code, 400)
        self.assertIn('nommer', r.json()['erreur'])       # refus explicite, pas un plantage
        self.assertEqual(RagChunk.objects.count(), 0)

    def test_l_unite_par_defaut_du_profil_debloque_le_partage(self):
        prof = self.u.profile
        prof.rag_unite_defaut = 'CFR - LESCOT'
        prof.save()
        r = self._ajouter()
        self.assertEqual(r.status_code, 200)
        chunk = RagChunk.objects.filter(user=self.u).first()
        self.assertEqual(chunk.visibility, ScopedVisibility.VIS_UNIT)
        self.assertEqual(chunk.scope_org_unit_id, self.actuel.id)

    def test_la_page_ne_propose_que_les_unites_RESOLUES(self):
        r = self.client.get('/common/rag/')
        codes = {u['code'] for u in r.context['unites']}
        # Le code fantôme est écarté : proposer un choix qui échouerait ensuite serait pire
        # que ne pas le proposer.
        self.assertEqual(codes, {'CFR - LESCOT', '{IFSTTAR}LESCOT'})

    def test_on_ne_peut_pas_choisir_une_unite_dont_on_n_est_pas_membre(self):
        OrgUnit.objects.create(code='AUTRE-LABO', name='Autre labo', unit_type='labo')
        r = self.client.post('/common/api/rag/preference/',
                             {'unite_soumise': '1', 'unite_defaut': 'AUTRE-LABO'})
        self.assertEqual(r.status_code, 400)
        self.u.profile.refresh_from_db()
        self.assertEqual(self.u.profile.rag_unite_defaut, '')


class SyncOrgUnitsTests(TestCase):
    """`deviner_type` est du best-effort ASSUMÉ : le type d'unité est cosmétique, l'héritage
    RAG ne dépend que de `parent`. Ces tests fixent le comportement, pas une exactitude."""

    def test_types_devines_depuis_le_code_ou_le_type_supann(self):
        from wama.accounts.management.commands.sync_org_units import deviner_type
        self.assertEqual(deviner_type('{EIFFEL}CR-LR', 'CFR - LESCOT'), 'labo')
        self.assertEqual(deviner_type('', 'UNIV-EIFFEL'), 'universite')
        self.assertEqual(deviner_type('', '{IFSTTAR}'), 'autre')     # repli silencieux
