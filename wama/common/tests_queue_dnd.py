"""Manipulation DIRECTE de la file (CARD_DESIGN §3bis) — invariants du drag&drop.

Trois familles :
  1. le JUMELAGE `nature_of` ↔ `group_key` (analyse AST, jamais grep) ;
  2. le refus de fusion entre natures incompatibles (comportement, en base) ;
  3. l'ordre manuel de la file (`queue_index` + tri `manual`).
"""

import ast
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

RACINE = Path(settings.BASE_DIR)

FABRIQUES = {'make_queue_manipulation_views', 'make_queue_manipulation_views_direct',
             '_make_qm'}


def _jumelles():
    """Labels des jumelles de BAC À SABLE (`converter_01`…), lus à leur registre.

    ⚠ EXEMPTÉES des invariants ci-dessous, et c'est un choix argumenté, pas un contournement.
    Leur `views.py` n'est pas écrit à la main : c'est la SORTIE FIGÉE d'une exécution passée du
    générateur. L'auditer reviendrait à mesurer la dernière régénération, pas le générateur —
    et à rendre rouge, à chaque évolution du codegen, un fichier que personne n'a le devoir de
    tenir à jour entre deux `app_sandbox`.

    Le générateur, lui, EST vérifié : `CodegenJumelleTest` ci-dessous lit le gabarit à la
    source. C'est là que l'invariant doit tenir — les jumelles l'hériteront à leur prochaine
    régénération. *Exempter l'artefact et tester la fabrique, jamais l'inverse.*
    """
    import json
    fichier = RACINE / 'wama' / 'sandbox_apps.json'
    if not fichier.exists():
        return set()
    try:
        return {e['label'] for e in json.loads(fichier.read_text(encoding='utf-8'))
                if e.get('label')}
    except (ValueError, KeyError):
        return set()


def _apps_de_file():
    """Les `views.py` des apps du monde MÉDIA qui déclarent une file (hors jumelles)."""
    jumelles = _jumelles()
    for chemin in sorted((RACINE / 'wama').glob('*/views.py')):
        if chemin.parent.name not in jumelles:
            yield chemin.parent.name, chemin


def _kwarg(appel: ast.Call, nom: str):
    for kw in appel.keywords:
        if kw.arg == nom:
            return kw.value
    return None


def _appels(arbre):
    return [n for n in ast.walk(arbre) if isinstance(n, ast.Call)]


class JumelageNatureGroupKeyTest(TestCase):
    """⚠⚠ LE test de ce chantier (remarque de Fabien, 2026-09-04).

    La question « ces deux cards peuvent-elles fusionner en lot ? » avait DÉJÀ une réponse
    dans le dépôt : `group_into_batches_by_nature(nature_of=…)`, qui décide à l'import de ce
    qui va ensemble. Le drag&drop repose la même question après coup. S'il y répond avec sa
    propre règle, les deux chemins divergent — l'import refuse de mélanger image et vidéo
    pendant que le glisser-déposer l'autorise, dans la même app.

    Ce test interdit la divergence PAR CONSTRUCTION : la fonction passée en `nature_of` doit
    être exactement celle passée en `group_key`. C'est aussi ce qui force à la NOMMER — une
    lambda inline ne se partage pas, et c'est sous cette forme qu'elle vivait dans 3 apps.

    Analyse AST et non grep : un grep compte des occurrences d'un motif, il ne dit pas quel
    argument d'quel appel les porte (leçon « un relevé par motif NE CONCLUT PAS »).
    """

    def test_toute_app_qui_groupe_par_nature_defend_la_meme_nature_au_drag(self):
        manquants, incoherents = [], []
        for app, chemin in _apps_de_file():
            arbre = ast.parse(chemin.read_text(encoding='utf-8'))
            appels = _appels(arbre)

            natures = []
            for a in appels:
                v = _kwarg(a, 'nature_of')
                if v is not None:
                    natures.append(ast.unparse(v))
            if not natures:
                continue    # app mono-nature : rien à défendre

            cles = []
            for a in appels:
                nom = (a.func.id if isinstance(a.func, ast.Name)
                       else getattr(a.func, 'attr', None))
                if nom in FABRIQUES:
                    v = _kwarg(a, 'group_key')
                    cles.append(ast.unparse(v) if v is not None else None)
            if not cles:
                continue    # app sans fabrique de manipulation : hors périmètre

            for n in natures:
                if n.startswith('lambda'):
                    incoherents.append(
                        f"{app} : `nature_of={n}` est une LAMBDA — impartageable, "
                        f"donc le drag&drop ne peut pas appliquer la même règle. "
                        f"La nommer (`def _{app}_nature(...)`) et la passer aux deux.")
                elif n not in cles:
                    manquants.append(
                        f"{app} : groupe à l'import par `{n}` mais la fabrique de "
                        f"manipulation ne reçoit pas `group_key={n}` "
                        f"(reçu : {cles}) → une fusion par drag&drop y produirait un lot "
                        f"mixte que l'import n'aurait jamais créé.")

        self.assertEqual([], incoherents + manquants,
                         "\n".join(incoherents + manquants))


class CodegenJumelleTest(TestCase):
    """Une app GÉNÉRÉE naît-elle avec le geste — et avec la garde de compatibilité ?

    C'est ici que l'invariant tient pour les jumelles (cf. `_jumelles()`) : on lit le GABARIT,
    pas son produit figé. Sans ce test, toute app générée après le 2026-09-04 naîtrait avec une
    file inerte — et l'inertie est MUETTE (`_app_scripts.html` documente le cas de
    converter_01, qui n'a chargé aucun script d'app pendant des semaines sans une seule erreur
    console).
    """

    def test_le_gabarit_emet_les_cinq_endpoints_et_la_nature_partagee(self):
        from wama.common.manifests.codegen import urls_gen, views_gen

        source_urls = Path(urls_gen.__file__).read_text(encoding='utf-8')
        for route in ('reorder', 'reorder_queue', 'merge', 'move_to_batch',
                      'remove_from_batch', 'consolidate'):
            self.assertIn(f"'{route}':", source_urls,
                          f"route `{route}` absente du gabarit d'urls généré")

        source_vues = Path(views_gen.__file__).read_text(encoding='utf-8')
        for cle in ("_qm['reorder_queue']", "_qm['merge']"):
            self.assertIn(cle, source_vues, f"{cle} non exporté par le gabarit de vues")
        # La nature EST partagée : émise comme fonction nommée, consommée des deux côtés.
        self.assertIn('def _nature_de_lot(', source_vues)
        self.assertIn('nature_of=_nature_de_lot', source_vues)
        self.assertIn('group_key=_nature_de_lot', source_vues)
        self.assertNotIn('nature_of=lambda o:', source_vues,
                         "une lambda inline ne se partage pas — cf. `_jumelles()`")

    def test_le_gabarit_de_file_pose_les_attributs_de_manipulation(self):
        from wama.common.manifests.codegen import templates_gen

        source = Path(templates_gen.__file__).read_text(encoding='utf-8')
        self.assertIn('queue_dnd_attrs', source,
                      "le conteneur de file généré ne déclare pas ses URLs → file inerte, "
                      "et l'inertie ne lève aucune erreur")


class RefusDeFusionTest(TestCase):
    """Le refus est-il RÉELLEMENT appliqué — pas seulement déclaré ?

    ⚠ Un test qui ne vérifierait que le câblage (le kwarg est passé) attesterait une ADOPTION,
    jamais un FONCTIONNEMENT (`WAMA_VERIFICATION §1`). On exerce donc la vue.
    """

    def setUp(self):
        self.user = User.objects.create_user('dnd_refus', 'dnd@test.local', 'x')
        self.rf = RequestFactory()

    def _requete(self, donnees):
        r = self.rf.post('/', donnees)
        r.user = self.user
        return r

    def test_deplacer_dans_un_lot_de_nature_differente_est_refuse(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        from wama.converter.views import move_to_batch

        lot_image = ConversionBatch.objects.create(user=self.user, total=1, media_type='image')
        ConversionJob.objects.create(user=self.user, media_type='image', batch=lot_image,
                                     batch_row_index=0)
        video = ConversionJob.objects.create(user=self.user, media_type='video')

        rep = move_to_batch(self._requete({'batch_id': lot_image.id}), pk=video.id)

        self.assertEqual(409, rep.status_code)
        video.refresh_from_db()
        self.assertIsNone(video.batch, "la vidéo ne doit PAS avoir rejoint le lot d'images")

    def test_deplacer_dans_un_lot_de_meme_nature_est_accepte(self):
        from wama.converter.models import ConversionBatch, ConversionJob
        from wama.converter.views import move_to_batch

        lot = ConversionBatch.objects.create(user=self.user, total=1, media_type='image')
        ConversionJob.objects.create(user=self.user, media_type='image', batch=lot,
                                     batch_row_index=0)
        autre = ConversionJob.objects.create(user=self.user, media_type='image')

        rep = move_to_batch(self._requete({'batch_id': lot.id}), pk=autre.id)

        self.assertEqual(200, rep.status_code)
        autre.refresh_from_db()
        self.assertEqual(lot.id, autre.batch_id)

    def test_fusionner_des_natures_differentes_est_refuse(self):
        """`merge` REFUSE — c'est le geste du drag&drop, on a visé une card précise."""
        from wama.converter.models import ConversionJob
        from wama.converter.views import merge

        img = ConversionJob.objects.create(user=self.user, media_type='image')
        vid = ConversionJob.objects.create(user=self.user, media_type='video')

        r = self.rf.post('/', {'ids': [str(img.id), str(vid.id)]})
        r.user = self.user
        rep = merge(r)

        self.assertEqual(409, rep.status_code)
        img.refresh_from_db(); vid.refresh_from_db()
        self.assertTrue(img.batch_id is None or img.batch_id != vid.batch_id)

    def test_consolidate_lui_RANGE_par_nature_au_lieu_de_refuser(self):
        """Le pendant du test ci-dessus, et la raison d'être des deux noms.

        `consolidate` est le chemin d'IMPORT : on vient de déposer un dossier mélangé, on veut
        qu'il se range — deux lots, pas un refus. Router le drag&drop dessus (ce que faisait
        mon premier jet) rendait « succès » après n'avoir rien fait de visible."""
        from wama.converter.models import ConversionJob
        from wama.converter.views import consolidate

        img = ConversionJob.objects.create(user=self.user, media_type='image')
        vid = ConversionJob.objects.create(user=self.user, media_type='video')

        # ⚠ `job_ids`, pas `ids` : le consolidate LOCAL du converter garde son champ
        # historique (c'est pourquoi `wama-import.js` expose `consolidateField`). Une raison
        # de plus de ne pas router le drag&drop dessus — les cinq consolidate locaux ne
        # partagent même pas leur contrat d'entrée, là où `merge` vient tout entier de la
        # fabrique commune.
        r = self.rf.post('/', {'job_ids': [str(img.id), str(vid.id)]})
        r.user = self.user
        rep = consolidate(r)

        self.assertEqual(200, rep.status_code)
        img.refresh_from_db(); vid.refresh_from_db()
        self.assertIsNotNone(img.batch_id)
        self.assertIsNotNone(vid.batch_id)
        self.assertNotEqual(img.batch_id, vid.batch_id,
                            "l'import RANGE par nature : deux lots, jamais un lot mixte")


class OrdreManuelDeFileTest(TestCase):
    """`reorder_queue` + le tri `manual` — l'ordre de niveau supérieur, qui n'existait pas."""

    def setUp(self):
        self.user = User.objects.create_user('dnd_ordre', 'dnd2@test.local', 'x')
        self.rf = RequestFactory()

    def _lots(self, n):
        from wama.transcriber.models import BatchTranscript
        return [BatchTranscript.objects.create(user=self.user, total=1) for _ in range(n)]

    def test_reorder_queue_ecrit_1_a_N_et_jamais_0(self):
        from wama.transcriber.views import reorder_queue

        a, b, c = self._lots(3)
        r = self.rf.post('/', {'order': f'{c.id},{a.id},{b.id}'})
        r.user = self.user
        reorder_queue(r)

        a.refresh_from_db(); b.refresh_from_db(); c.refresh_from_db()
        self.assertEqual([1, 2, 3], [c.queue_index, a.queue_index, b.queue_index])
        # Le 0 est RÉSERVÉ à « jamais ordonné » : l'écrire ici replacerait silencieusement
        # une entrée classée dans le paquet des non-classées.
        self.assertNotIn(0, [a.queue_index, b.queue_index, c.queue_index])

    def test_un_id_etranger_n_empeche_pas_le_classement_des_autres(self):
        from wama.transcriber.views import reorder_queue

        a, b = self._lots(2)
        autre = User.objects.create_user('dnd_autre', 'x@test.local', 'x')
        from wama.transcriber.models import BatchTranscript
        pas_a_moi = BatchTranscript.objects.create(user=autre, total=1)

        r = self.rf.post('/', {'order': f'{a.id},{pas_a_moi.id},{b.id}'})
        r.user = self.user
        rep = reorder_queue(r)

        self.assertEqual(200, rep.status_code)
        a.refresh_from_db(); b.refresh_from_db(); pas_a_moi.refresh_from_db()
        self.assertEqual(1, a.queue_index)
        self.assertEqual(3, b.queue_index)
        self.assertEqual(0, pas_a_moi.queue_index, "un lot d'un autre utilisateur reste intact")

    def test_le_tri_manuel_met_les_non_classes_en_tete_par_recence(self):
        """La sémantique du 0 — celle qui fait qu'un import récent ne se noie pas."""
        from datetime import timedelta

        from django.utils import timezone

        from wama.common.utils.queue_view import apply_queue_sort_filter

        maintenant = timezone.now()

        class _Faux:
            def __init__(self, i, qi, minutes):
                self.id, self.queue_index = i, qi
                self.created_at = maintenant - timedelta(minutes=minutes)
                self.total = 1

        entrees = [
            {'obj': _Faux(1, 2, 60), 'items': [], 'success_count': 0,
             'running_count': 0, 'failure_count': 0},
            {'obj': _Faux(2, 1, 50), 'items': [], 'success_count': 0,
             'running_count': 0, 'failure_count': 0},
            {'obj': _Faux(3, 0, 5), 'items': [], 'success_count': 0,     # nouvel arrivant
             'running_count': 0, 'failure_count': 0},
            {'obj': _Faux(4, 0, 40), 'items': [], 'success_count': 0,    # jamais classé, plus vieux
             'running_count': 0, 'failure_count': 0},
        ]
        r = self.rf.get('/', {'sort': 'manual'})
        r.session = {}
        tries, q_sort, _ = apply_queue_sort_filter(r, entrees, name_of=lambda b: '')

        self.assertEqual('manual', q_sort)
        self.assertEqual([3, 4, 2, 1], [e['obj'].id for e in tries],
                         "non classés d'abord (du plus récent au plus ancien), puis 1..N")

    def test_le_tri_manuel_ne_tombe_pas_sur_un_lot_sans_le_mixin(self):
        """Le tri est persisté en SESSION et suit l'utilisateur d'app en app : il doit
        survivre à une file dont le batch n'a pas `queue_index`."""
        from datetime import timedelta

        from django.utils import timezone

        from wama.common.utils.queue_view import apply_queue_sort_filter

        class _SansMixin:
            id, total = 1, 1
            created_at = timezone.now() - timedelta(minutes=1)

        entrees = [{'obj': _SansMixin(), 'items': [], 'success_count': 0,
                    'running_count': 0, 'failure_count': 0}]
        r = self.rf.get('/', {'sort': 'manual'})
        r.session = {}
        tries, _, _ = apply_queue_sort_filter(r, entrees, name_of=lambda b: '')
        self.assertEqual(1, len(tries))


class ExpositionDesUrlsTest(TestCase):
    """La brique JS ne peut agir que sur ce que le gabarit lui DÉCLARE."""

    def test_les_12_files_declarent_leurs_urls_de_manipulation(self):
        """`{% queue_dnd_attrs %}` doit être posé sur CHAQUE conteneur de file.

        Sans lui la file est inerte, et c'est une inertie MUETTE : rien ne plante quand rien
        n'est monté (le défaut exact que `_app_scripts.html` documente pour converter_01).
        """
        manquants = []
        jumelles = _jumelles()
        for gabarit in sorted((RACINE / 'wama').glob('*/templates/*/index.html')):
            if gabarit.parts[-4] in jumelles:
                continue        # gabarit GÉNÉRÉ — cf. `_jumelles()`
            texte = gabarit.read_text(encoding='utf-8')
            files = texte.count('class="wama-queue-')
            if not files:
                continue
            poses = texte.count('queue_dnd_attrs')
            if poses < files:
                manquants.append(
                    f"{gabarit.relative_to(RACINE)} : {files} file(s), "
                    f"{poses} `queue_dnd_attrs`")
        self.assertEqual([], manquants, "\n".join(manquants))

    def test_le_tag_n_emet_que_les_routes_qui_existent(self):
        from wama.common.templatetags.wama_actions import queue_dnd_attrs

        rendu = str(queue_dnd_attrs('transcriber'))
        for attendu in ('data-wama-dnd="transcriber"', 'data-dnd-reorder-url',
                        'data-dnd-reorder-queue-url', 'data-dnd-move-url',
                        'data-dnd-remove-url', 'data-dnd-merge-url'):
            self.assertIn(attendu, rendu)

        # Une app sans aucune de ces routes n'émet RIEN — donc la brique ne monte pas, et
        # aucun geste ne part dans le vide.
        self.assertEqual('', str(queue_dnd_attrs('filemanager')))

    def test_le_domaine_choisit_la_bonne_famille_de_routes(self):
        """L'enhancer a DEUX files sur la même page : la file audio doit recevoir les routes
        `audio_*`, sinon un glisser-déposer dans l'audio écrirait dans la file image/vidéo."""
        from wama.common.templatetags.wama_actions import queue_dnd_attrs

        audio = str(queue_dnd_attrs('enhancer', 'audio'))
        self.assertIn('/audio/reorder/', audio)
        self.assertIn('/audio/move-to-batch/', audio)

        media = str(queue_dnd_attrs('enhancer', 'image_video'))
        self.assertNotIn('/audio/', media)
