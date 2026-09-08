"""PARTAGE d'un élément de file — le service, l'endpoint, et la seule preuve qui compte.

`PROFILES_PERMISSIONS §7` cadre le partage depuis le 2026-07-31, et §7.5 nommait le trou : « il
n'existe aucune interface de partage ». Ce module tient la première (2026-09-08), et Fabien l'a
posée dans les termes exacts : « on parle exclusivement de l'UI, pas du fonctionnement qui est
déjà en place ». D'où la forme de ces tests — ils n'éprouvent pas `ScopedVisibility` (déjà écrit
et adopté 10/10), ils éprouvent que le GESTE écrit ce qu'il faut, où il faut.

⚠⚠ LE TEST DÉCISIF est `test_le_destinataire_VOIT_reellement_l_element_partage`. Tous les autres
peuvent passer sur un partage qui n'ouvre rien : c'est celui-là qui interroge
`scoped_visible_q` — le filtre que les vraies vues utilisent — et donc qui distingue « la
colonne a été écrite » de « la personne voit ». La leçon du dépôt sur ce point est constante :
un vert d'adoption ne dit rien du fonctionnement.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.common.models import (OrgUnit, Project, ProjectMembership, ScopedVisibility,
                                scoped_visible_q)
from wama.common.services.sharing import RefusDePartage, partager, portees_offrables
from wama.common.utils.batch_common import batch_of

User = get_user_model()


def _job(user, batch=None, nom='temoin.png'):
    """Un élément converter — forme à FK DIRECTE (`ConversionJob.batch`)."""
    from wama.converter.models import ConversionJob
    return ConversionJob.objects.create(user=user, input_filename=nom, batch=batch)


def _lot_converter(user, total=1):
    from wama.converter.models import ConversionBatch
    return ConversionBatch.objects.create(user=user, total=total)


def _generation(user):
    """Un élément imager relié par MODÈLE DE LIAISON (`GenerationBatchItem`)."""
    from wama.imager.models import GenerationBatch, GenerationBatchItem, ImageGeneration
    gen = ImageGeneration.objects.create(user=user, prompt='un phare')
    lot = GenerationBatch.objects.create(user=user, total=1)
    GenerationBatchItem.objects.create(batch=lot, generation=gen, row_index=0)
    return gen, lot


class AccesseurDuLotTest(TestCase):
    """`batch_of` — le jumeau d'instance de `batch_model_for`, écrit pour le partage.

    Les DEUX formes de rattachement du dépôt doivent être couvertes : sans la seconde, le
    partage propagerait sur converter et pas sur les dix autres apps — et ce serait invisible,
    puisque rien ne planterait.
    """

    def setUp(self):
        self.u = User.objects.create_user('partage_lot', password='x')

    def test_forme_a_fk_directe(self):
        lot = _lot_converter(self.u)
        self.assertEqual(lot, batch_of(_job(self.u, batch=lot)))

    def test_forme_par_modele_de_liaison(self):
        gen, lot = _generation(self.u)
        self.assertEqual(lot, batch_of(gen))

    def test_un_element_hors_lot_rend_None_sans_lever(self):
        self.assertIsNone(batch_of(_job(self.u)))
        self.assertIsNone(batch_of(None))


class PartageTest(TestCase):

    def setUp(self):
        self.u = User.objects.create_user('partageur', password='x')
        self.autre = User.objects.create_user('autrui', password='x')
        self.labo = OrgUnit.objects.create(code='LESCOT_T', name='Lescot', unit_type='labo')
        prof = self.u.profile
        prof.org_entity_code = 'LESCOT_T'
        prof.save(update_fields=['org_entity_code'])

    # ── Le cœur : la propagation au LOT ────────────────────────────────────────────────
    def test_partager_propage_au_lot_forme_fk_directe(self):
        lot = _lot_converter(self.u)
        job = _job(self.u, batch=lot)
        cr = partager(self.u, job, ScopedVisibility.VIS_PUBLIC)
        job.refresh_from_db(); lot.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PUBLIC, job.visibility)
        self.assertEqual(ScopedVisibility.VIS_PUBLIC, lot.visibility)
        self.assertEqual(lot.id, cr['lot'])
        self.assertFalse(cr['lot_non_partageable'])

    def test_partager_propage_au_lot_forme_par_liaison(self):
        """⚠ LE CAS QUI COMPTE POUR 10 APPS SUR 12.

        `PROFILES_PERMISSIONS §7.4bis` : « une card partagée sans son batch n'apparaît pas » —
        la file est construite à partir des LOTS. Sans propagation, le partage n'échouerait pas
        et ne marcherait pas.
        """
        gen, lot = _generation(self.u)
        partager(self.u, gen, ScopedVisibility.VIS_UNIT, org_unit_id=self.labo.id)
        gen.refresh_from_db(); lot.refresh_from_db()
        for obj in (gen, lot):
            self.assertEqual(ScopedVisibility.VIS_UNIT, obj.visibility)
            self.assertEqual(self.labo.id, obj.scope_org_unit_id)

    # ── Les gardes ─────────────────────────────────────────────────────────────────────
    def test_seul_le_proprietaire_partage(self):
        job = _job(self.u)
        with self.assertRaises(RefusDePartage):
            partager(self.autre, job, ScopedVisibility.VIS_PUBLIC)
        job.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PRIVATE, job.visibility)

    def test_une_unite_qui_ne_couvre_pas_l_utilisateur_est_refusee(self):
        etranger = OrgUnit.objects.create(code='AUTRE_T', name='Autre labo', unit_type='labo')
        with self.assertRaises(RefusDePartage):
            partager(self.u, _job(self.u), ScopedVisibility.VIS_UNIT, org_unit_id=etranger.id)

    def test_un_projet_dont_on_n_est_pas_membre_est_refuse(self):
        projet = Project.objects.create(code='PF_T', name='Projet fermé')
        with self.assertRaises(RefusDePartage):
            partager(self.u, _job(self.u), ScopedVisibility.VIS_PROJECT, project_id=projet.id)

    def test_une_portee_a_cible_exige_sa_cible(self):
        with self.assertRaises(RefusDePartage):
            partager(self.u, _job(self.u), ScopedVisibility.VIS_UNIT)

    def test_portee_inconnue_refusee(self):
        with self.assertRaises(RefusDePartage):
            partager(self.u, _job(self.u), 'tout_le_monde')

    def test_repasser_en_public_EFFACE_le_scope_precedent(self):
        """Sinon l'objet resterait rattaché à une unité qu'il ne concerne plus — et un futur
        retour en `unit` le rouvrirait à cette unité-là sans que personne ne l'ait demandé."""
        job = _job(self.u)
        partager(self.u, job, ScopedVisibility.VIS_UNIT, org_unit_id=self.labo.id)
        partager(self.u, job, ScopedVisibility.VIS_PUBLIC)
        job.refresh_from_db()
        self.assertIsNone(job.scope_org_unit_id)
        self.assertIsNone(job.scope_project_id)

    # ── LE test décisif ────────────────────────────────────────────────────────────────
    def test_le_destinataire_VOIT_reellement_l_element_partage(self):
        """Écrire la colonne ne prouve pas qu'on ouvre quelque chose.

        On interroge `scoped_visible_q` — le filtre dont les vues se servent — depuis le compte
        d'un TIERS, avant et après le partage.
        """
        from wama.converter.models import ConversionJob
        lot = _lot_converter(self.u)
        job = _job(self.u, batch=lot)

        def vus_par(user):
            return set(ConversionJob.objects.filter(scoped_visible_q(user))
                       .values_list('id', flat=True))

        self.assertNotIn(job.id, vus_par(self.autre), "un élément privé ne doit PAS être visible")

        # Partage à l'UNITÉ : le tiers n'en fait pas partie → toujours invisible.
        partager(self.u, job, ScopedVisibility.VIS_UNIT, org_unit_id=self.labo.id)
        self.assertNotIn(job.id, vus_par(self.autre),
                         "un partage d'unité ne doit pas fuir hors de l'unité")

        # Le tiers REJOINT l'unité → il voit.
        prof = self.autre.profile
        prof.org_entity_code = 'LESCOT_T'
        prof.save(update_fields=['org_entity_code'])
        self.assertIn(job.id, vus_par(self.autre),
                      "un membre de l'unité doit voir l'élément partagé à son unité")

        # …et le PROJET traverse les organisations, ce qui est sa raison d'être.
        tiers = User.objects.create_user('partenaire', password='x')
        projet = Project.objects.create(code='PO_T', name='Projet ouvert')
        ProjectMembership.objects.create(project=projet, user=self.u, role='lead')
        ProjectMembership.objects.create(project=projet, user=tiers, role='partner')
        partager(self.u, job, ScopedVisibility.VIS_PROJECT, project_id=projet.id)
        self.assertIn(job.id, vus_par(tiers),
                      "un membre du projet doit voir l'élément partagé au projet")

    def test_portees_offrables_n_offre_pas_une_portee_sans_cible(self):
        """Proposer « Projet » à qui n'est membre d'aucun projet afficherait un choix qui ne
        peut pas aboutir — c'est la leçon du Geste 14, appliquée avant qu'elle ne se répète."""
        offres = {o['valeur'] for o in portees_offrables(self.u)}
        self.assertIn(ScopedVisibility.VIS_PRIVATE, offres)
        self.assertIn(ScopedVisibility.VIS_PUBLIC, offres)
        self.assertIn(ScopedVisibility.VIS_UNIT, offres)        # il a une affiliation
        self.assertNotIn(ScopedVisibility.VIS_PROJECT, offres)  # membre d'aucun projet

        ProjectMembership.objects.create(
            project=Project.objects.create(code='P_T', name='P'), user=self.u, role='member')
        self.assertIn(ScopedVisibility.VIS_PROJECT,
                      {o['valeur'] for o in portees_offrables(self.u)})


class BriqueDePartageTest(TestCase):
    """Le CÂBLAGE de la brique front. Son comportement, lui, s'atteste au navigateur.

    Un `.js` ne casse jamais à la compilation : le smoke du 2026-09-08 a mesuré le cycle complet
    (ouvrir → appliquer → 0 backdrop, corps débloqué ; deux ouvertures d'affilée n'empilent
    rien ; charge envoyée `{visibility, org_unit_id}`). Ce que ces tests tiennent, c'est ce
    qu'un smoke ne rejouera pas si quelqu'un défait l'inclusion ou la FORME de la modale.
    """

    def _js(self):
        from django.conf import settings
        from pathlib import Path
        return (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
                / 'wama-share.js').read_text(encoding='utf-8')

    def test_la_brique_est_chargee_AVANT_le_menu(self):
        """Le menu n'offre « Partager… » que si `WamaShare` existe.

        Dans l'autre ordre, l'entrée serait absente au premier montage — sans erreur, donc sans
        qu'on le voie. C'est le genre de dépendance qui ne se rappelle pas toute seule.
        """
        from django.conf import settings
        from pathlib import Path
        base = (Path(settings.BASE_DIR) / 'wama' / 'templates'
                / 'base.html').read_text(encoding='utf-8')
        # ⚠ On cherche la BALISE, pas une mention : `base.html` cite `wama-card-menu.js` dans
        # le commentaire de sa feuille de style, bien AVANT le script. Un `find()` naïf y
        # tombait et rendait le test rouge sur un ordre pourtant correct — instrument fautif,
        # pas code fautif (mesuré en écrivant ce test).
        import re
        def position(fichier):
            m = re.search(r'<script[^>]+' + re.escape(fichier), base)
            return m.start() if m else -1

        i_share, i_menu = position('wama-share.js'), position('wama-card-menu.js')
        self.assertNotEqual(-1, i_share, "`wama-share.js` n'est plus chargé par une balise script")
        self.assertNotEqual(-1, i_menu, "`wama-card-menu.js` n'est plus chargé par une balise script")
        self.assertLess(i_share, i_menu, "la modale doit être chargée avant le menu")
        self.assertIn('wama-share.css', base)

    def test_la_modale_est_un_hote_UNIQUE_et_reutilise(self):
        """⚠ DEUX défauts mesurés ont imposé cette forme (cf. l'en-tête de `hote`).

        Une modale recréée à chaque ouverture restait `.show` et empilait **deux backdrops** —
        et un backdrop orphelin avale tous les clics de la page. Puis purger l'ancienne avant
        d'ouvrir a fait lever Bootstrap (`_showElement` sur un élément retiré en pleine
        animation). La forme singleton fait DISPARAÎTRE la classe de défaut.

        On interdit donc le retour à l'ancienne forme : pas de création d'élément de modale
        dans `ouvrir`, et `getOrCreateInstance` plutôt que `new bootstrap.Modal` (qui laisserait
        deux gestionnaires sur le même élément).
        """
        js = self._js()
        self.assertIn('function hote()', js)
        self.assertIn('getOrCreateInstance', js)
        self.assertNotIn('new bootstrap.Modal', js)
        self.assertNotIn('enveloppe.remove()', js)

    def test_la_modale_DIT_que_le_partage_est_en_lecture_seule(self):
        """L'écriture est le jalon S3 : une UI qui la laisse croire mentirait sur des droits."""
        js = self._js()
        self.assertIn('lecture seule', js)

    def test_les_coordonnees_viennent_de_data_preview_url(self):
        """Le contrat déjà porté par les 10 gabarits de card du parc (mesuré), et déjà utilisé
        par l'inspecteur pour dériver l'URL de détail. Il distingue les DEUX surfaces de
        l'enhancer, ce qu'un `data-wama-dnd` (l'app) ne saurait pas faire."""
        self.assertIn('/common/preview/', self._js())

    def test_chaque_gabarit_de_card_porte_bien_ce_contrat(self):
        """Sans lui l'entrée « Partager… » n'apparaîtrait pas — silencieusement."""
        from django.conf import settings
        from pathlib import Path
        racine = Path(settings.BASE_DIR) / 'wama'
        sans = []
        for gabarit in sorted(racine.glob('*/templates/*/_*card*.html')):
            nom = gabarit.name
            if nom.startswith(('_new_item_card', '_batch_card', '_card_', '_journal_card')):
                continue          # cards d'ENTRÉE / mère de lot / partials internes
            if 'data-preview-url' not in gabarit.read_text(encoding='utf-8'):
                sans.append(str(gabarit.relative_to(racine)))
        self.assertEqual([], sans, "\n".join(sans))


class EndpointDePartageTest(TestCase):
    """La route commune — UNE pour les 12 files, clé = la SURFACE de `PreviewRegistry`."""

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        from django.contrib.auth.models import Group
        self.u = User.objects.create_user('endpoint_partage', password='x')
        for role in ('communication', 'recherche', 'ingenierie', 'administratif'):
            g, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')
            self.u.groups.add(g)
        self.client.force_login(self.u)
        self.job = _job(self.u, batch=_lot_converter(self.u))

    def _url(self, surface='converter', pk=None):
        return reverse('common:api_partage', args=[surface, pk or self.job.id])

    def test_get_rend_l_etat_et_les_portees(self):
        rep = self.client.get(self._url())
        self.assertEqual(200, rep.status_code, rep.content[:200])
        d = rep.json()
        self.assertEqual(ScopedVisibility.VIS_PRIVATE, d['etat']['visibility'])
        self.assertTrue(d['portees'], "aucune portée offerte : la modale serait vide")

    def test_post_applique_et_rend_un_compte_rendu(self):
        rep = self.client.post(self._url(), {'visibility': ScopedVisibility.VIS_PUBLIC})
        self.assertEqual(200, rep.status_code, rep.content[:200])
        d = rep.json()
        self.assertTrue(d['ok'])
        self.assertEqual(ScopedVisibility.VIS_PUBLIC, d['visibility'])
        self.assertIsNotNone(d['lot'], "le compte-rendu doit DIRE que le lot a suivi")
        self.job.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PUBLIC, self.job.visibility)

    def test_un_pk_etranger_rend_404_et_non_403(self):
        """Un 403 confirmerait l'existence de l'objet d'un autre."""
        autre = User.objects.create_user('proprietaire', password='x')
        etranger = _job(autre)
        self.assertEqual(404, self.client.get(self._url(pk=etranger.id)).status_code)
        self.assertEqual(404, self.client.post(self._url(pk=etranger.id),
                                               {'visibility': 'public'}).status_code)
        etranger.refresh_from_db()
        self.assertEqual(ScopedVisibility.VIS_PRIVATE, etranger.visibility)

    def test_surface_inconnue_rend_404(self):
        self.assertEqual(404, self.client.get(self._url(surface='pas_une_app')).status_code)

    def test_un_refus_est_MOTIVE_et_non_un_500(self):
        rep = self.client.post(self._url(), {'visibility': 'unit'})   # sans cible
        self.assertEqual(400, rep.status_code)
        self.assertFalse(rep.json()['ok'])
        self.assertIn('unité', rep.json()['reason'])

    def test_les_deux_surfaces_de_l_enhancer_sont_distinctes(self):
        """La clé est la SURFACE : `enhancer` et `audio_enhancer` ont deux modèles différents.
        Une route indexée sur l'APP aurait confondu les deux files de la même page."""
        from wama.common.utils.preview_registry import PreviewRegistry
        m1 = PreviewRegistry.get_model('enhancer')
        m2 = PreviewRegistry.get_model('audio_enhancer')
        self.assertIsNotNone(m1)
        self.assertIsNotNone(m2)
        self.assertIsNot(m1, m2)
