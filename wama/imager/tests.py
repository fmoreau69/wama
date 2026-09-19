"""Imager — le LOT a un DOMAINE (2026-09-08, décision Fabien : lots vidéo, dont depuis le studio).

`handle_file2img` écrivait `txt2img` et `domain='image'` en dur : un fichier de prompts déposé
sur la card VIDÉO ne pouvait exister. Le domaine est désormais DÉCLARÉ par l'appelant ; ces
tests tiennent les deux faces : vidéo → `txt2vid` dans un lot vidéo avec ses réglages, et
l'ABSENCE de déclaration → image, comme avant (aucun appelant existant ne change de sens).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.imager.models import GenerationBatch, ImageGeneration

User = get_user_model()


class LotImagerMixin:
    """Un utilisateur autorisé + la fabrique de lot par import — partagés par les deux familles.

    ⚠ Mixin et non classe de base HÉRITÉE d'un `TestCase` : hériter d'une classe de tests fait
    REJOUER ses tests dans chaque sous-classe (deux fois la même mesure, deux fois le coût).
    """

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('imager_lot', password='x')
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def _lot(self, **post):
        temoin = SimpleUploadedFile('wama_temoin_lot.txt', b'un phare dans la brume\nune foret\n',
                                    content_type='text/plain')
        rep = self.client.post(reverse('imager:import_batch'), {'batch_file': temoin, **post})
        self.assertEqual(200, rep.status_code, rep.content[:200])
        return GenerationBatch.objects.get(id=rep.json()['batch_id'])


class LotParDomaineTest(LotImagerMixin, TestCase):

    def test_un_lot_declare_video_cree_des_txt2vid_dans_un_lot_video(self):
        lot = self._lot(domain='video', video_duration='4', video_fps='24', video_resolution='720p')
        self.assertEqual('video', lot.domain)
        gens = list(ImageGeneration.objects.filter(user=self.user).order_by('id'))
        self.assertEqual(2, len(gens))
        self.assertTrue(all(g.generation_mode == 'txt2vid' and g.is_video_generation for g in gens))
        self.assertEqual((4.0, 24, '720p'),
                         (gens[0].video_duration, gens[0].video_fps, gens[0].video_resolution))

    def test_sans_domaine_declare_le_lot_reste_image_comme_avant(self):
        lot = self._lot()
        self.assertEqual('image', lot.domain)
        self.assertTrue(all(g.generation_mode == 'txt2img'
                            for g in ImageGeneration.objects.filter(user=self.user)))


class SortieDeLotTest(LotImagerMixin, TestCase):
    """Sortir UN élément d'un lot de 2 doit rendre DEUX cards unitaires.

    ⚠ DÉFAUT VÉCU (2026-09-08, signalé par Fabien : « pour un batch de 2 éléments, si j'essaie
    de sortir 1 élément, on devrait retrouver 2 cards unitaires. Et là rien ne change »).

    La vue était SAINE : le défaut vivait dans l'URL que le front construisait. Les deux briques
    JS substituaient le pk avec une expression ancrée en FIN d'URL (`/0/?$`) ; l'imager est la
    seule app du parc dont la route porte le pk au MILIEU
    (`/imager/queue/0/remove-from-batch/`), donc le gabarit repartait tel quel → 404 sur pk=0,
    puis `location.reload()`. Écran identique, aucun message.

    Ce test emprunte le CHEMIN DU NAVIGATEUR : il prend l'URL que le templatetag ÉMET et la
    substitue comme `WamaApp.getUrl` le fait. C'est la couture que ni le nocturne `queue_dnd`
    (aucun POST, par conception) ni `tests_queue_dnd` (endpoints via `reverse()`, donc pk déjà
    juste) ne pouvaient tenir — chacun déclarait sa moitié, et le défaut vivait entre les deux.
    """

    def _url_comme_le_front(self, pk):
        """L'URL de sortie de lot telle que la page la déclare, pk substitué comme en JS."""
        import re
        from wama.common.templatetags.wama_actions import queue_dnd_attrs
        rendu = str(queue_dnd_attrs('imager', 'image'))
        m = re.search(r'data-dnd-remove-url="([^"]+)"', rendu)
        self.assertIsNotNone(m, "la file n'expose pas `data-dnd-remove-url`")
        return m.group(1).replace('/0/', f'/{pk}/')

    def test_sortir_une_generation_d_un_lot_de_deux_rend_deux_lots_de_un(self):
        lot = self._lot()
        gens = list(ImageGeneration.objects.filter(user=self.user).order_by('id'))
        self.assertEqual(2, len(gens))
        self.assertEqual(2, lot.total)

        url = self._url_comme_le_front(gens[0].id)
        rep = self.client.post(url)
        self.assertEqual(200, rep.status_code,
                         f"{url} → {rep.status_code} (pk non substitué ? route déplacée ?)")
        self.assertTrue(rep.json().get('unwrapped'), rep.content[:200])

        lots = list(GenerationBatch.objects.filter(user=self.user).order_by('id'))
        self.assertEqual(2, len(lots), "la sortie n'a pas créé de second lot")
        self.assertEqual([1, 1], [b.total for b in lots])
        # `batch_extra` de l'imager : le lot né de la sortie doit rester dans SON onglet.
        self.assertEqual(['image', 'image'], [b.domain for b in lots])

    def test_sortir_le_dernier_element_est_refuse_sans_rien_casser(self):
        """Un lot de 1 est DÉJÀ isolé : la vue le dit au lieu de créer un lot vide."""
        self._lot()
        gens = list(ImageGeneration.objects.filter(user=self.user).order_by('id'))
        self.client.post(self._url_comme_le_front(gens[0].id))

        rep = self.client.post(self._url_comme_le_front(gens[1].id))
        self.assertEqual(200, rep.status_code)
        self.assertFalse(rep.json().get('unwrapped'))
        self.assertEqual('déjà isolé', rep.json().get('reason'))
        self.assertEqual(2, GenerationBatch.objects.filter(user=self.user).count())


class EnvoyerVersImagerCreeUnLotTest(LotImagerMixin, TestCase):
    """La TROISIÈME porte d'entrée du lot — « Envoyer vers Imager » depuis le gestionnaire.

    Elle ne créait pas de lot : elle posait un `ImageGeneration` PLACEHOLDER en `file2img`,
    portant le fichier dans le champ `prompt_file`, avec la promesse écrite en commentaire que
    « le batch sera créé quand l'utilisateur ouvrira l'Imager ». Personne ne le créait — mesuré
    au portage du 2026-09-10 : **0 génération avec `prompt_file` rempli** en base. L'utilisateur
    envoyait un .txt et récupérait une card fantôme « Batch from X (pending) ».

    Depuis, les trois portes (card historique, barre de détection commune, gestionnaire de
    fichiers) partagent le même cœur `creer_lot_de_prompts`. Le lot est un GESTE commun, pas
    une implémentation par point d'entrée.
    """

    def _envoyer(self, contenu=b'un phare dans la brume\nune foret la nuit\n', nom='wama_temoin_envoi.txt'):
        import tempfile
        from pathlib import Path

        from wama.filemanager.views import import_to_imager

        dossier = Path(tempfile.mkdtemp())
        source = dossier / nom
        source.write_bytes(contenu)
        return import_to_imager(source, self.user)

    def test_envoyer_un_fichier_de_prompts_cree_un_VRAI_lot(self):
        res = self._envoyer()
        self.assertTrue(res.get('imported'))
        self.assertIn('batch_id', res,
                      'la voie « Envoyer vers » ne rend pas de lot : le placeholder est revenu')
        self.assertEqual(2, res['count'])

        lot = GenerationBatch.objects.get(id=res['batch_id'])
        self.assertEqual(2, lot.total)
        gens = list(ImageGeneration.objects.filter(user=self.user).order_by('id'))
        self.assertEqual(2, len(gens))
        self.assertEqual(['un phare dans la brume', 'une foret la nuit'],
                         [g.prompt for g in gens])

    def test_aucune_card_FANTOME_ne_subsiste(self):
        """Le défaut se voyait à l'écran, pas dans une exception : une card « (pending) »
        qui n'était le travail de personne. On tient donc l'ABSENCE du placeholder."""
        self._envoyer()
        fantomes = ImageGeneration.objects.filter(user=self.user, generation_mode='file2img')
        self.assertEqual(0, fantomes.count(),
                         'un item `file2img` placeholder a été recréé')
        self.assertEqual(0,
                         ImageGeneration.objects.filter(user=self.user)
                         .exclude(prompt_file='').exclude(prompt_file=None).count(),
                         'le champ `prompt_file` est réalimenté : le lot vit sur le BATCH')

    def test_un_fichier_sans_prompt_exploitable_est_REFUSE_sans_rien_creer(self):
        with self.assertRaises(ValueError):
            self._envoyer(contenu=b'\n\n\n')
        self.assertEqual(0, ImageGeneration.objects.filter(user=self.user).count())
        self.assertEqual(0, GenerationBatch.objects.filter(user=self.user).count())


class LotDePromptsRespecteLaJUMELLETest(TestCase):
    """`creer_lot_de_prompts` doit créer dans l'app CIBLE, jamais dans l'app réelle.

    Régression introduite puis rattrapée le 2026-09-10, en extrayant le cœur de
    `handle_file2img` : la version extraite importait `ImageGeneration`/`GenerationBatch` en
    dur depuis `wama.imager.models`. Appelée pour `imager_01`, elle créait donc le lot dans
    l'imager RÉEL. Le code d'origine résolvait par `django_apps.get_model(app_label, …)`
    précisément pour ça — l'extraction avait perdu ce contrat en route.

    ⚠ Le symptôme est le pire qui soit : la requête répond **200**, et rien n'apparaît. Aucun
    test unitaire de l'app réelle ne pouvait le voir (elle, elle recevait bien son lot) ; c'est
    le scénario nocturne de la JUMELLE qui l'a attrapé — « requête acceptée (200) mais AUCUN
    élément n'apparaît dans imager_01 ». D'où cette garde, qui rend le contrat mesurable sans
    passer par le navigateur.
    """

    def _fichier(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        f = d / 'wama_temoin_jumelle.txt'
        f.write_bytes(b'un phare\nune foret\n')
        return f

    def test_le_lot_est_cree_dans_l_app_CIBLE(self):
        from django.apps import apps as django_apps
        from django.contrib.auth import get_user_model
        from wama.imager.views import creer_lot_de_prompts

        try:
            Jumelle = django_apps.get_model('imager_01', 'ImageGeneration')
        except LookupError:
            self.skipTest('jumelle imager_01 non installée sur cet arbre')

        from wama.imager.models import ImageGeneration as Reelle
        user = get_user_model().objects.create_user('lot_jumelle', password='x')
        avant_reel = Reelle.objects.count()

        batch, gens = creer_lot_de_prompts(self._fichier(), 'wama_temoin_jumelle.txt', user,
                                           app_label='imager_01')
        self.assertIsNotNone(batch)
        self.assertEqual(2, len(gens))
        self.assertTrue(all(isinstance(g, Jumelle) for g in gens),
                        'les éléments ont été créés dans l’app RÉELLE au lieu de la jumelle')
        self.assertEqual(avant_reel, Reelle.objects.count(),
                         'l’app réelle a été polluée par un import destiné à la jumelle')

    def test_le_defaut_reste_l_app_reelle(self):
        from django.contrib.auth import get_user_model
        from wama.imager.models import ImageGeneration
        from wama.imager.views import creer_lot_de_prompts

        user = get_user_model().objects.create_user('lot_reel', password='x')
        batch, gens = creer_lot_de_prompts(self._fichier(), 'wama_temoin_jumelle.txt', user)
        self.assertIsNotNone(batch)
        self.assertTrue(all(isinstance(g, ImageGeneration) for g in gens))


class ImageAttacheeAUnInputQuiEXISTETest(TestCase):
    """Le JS de la card ne doit pas SUPPOSER quel input d'image la card rend.

    Depuis que les ports viennent des modèles, l'imager ne déclare plus `reference_image`
    (aucun de ses 12 modèles ne le réclame) mais `work_image`. La card v4 rend donc UN volet
    fichier, servi par `file_input_id` ; `reference_input_id` n'y existe plus. Le JS attachait
    le fichier déposé à `d.refInputId` en dur : sur la v4, **il visait un élément ABSENT et le
    dépôt n'allait nulle part, sans une seule erreur**.

    Mesuré au navigateur le 2026-09-11 — imager (v3) rendait `imgRefInput` + `imgFileInput`,
    imager_01 (v4) `imgFileInput` seul.

    ⚠ Un `.js` ne casse pas à la compilation, il casse dans le navigateur : ce test tient donc
    le CONTRAT en texte. ⚠⚠ La phrase « aucun vérificateur de syntaxe JS n'est installé ici »
    qui figurait ici est FAUSSE depuis le 2026-09-17 (mesure) : `node` est bien absent, mais le
    venv porte `py_mini_racer` (V8) et `esprima`. La validité d'un `.js` s'atteste donc hors
    navigateur — parse du fichier SERVI par **V8**, et exécution si la brique ne touche pas au
    DOM. ⚠ `esprima` seul ne suffit pas : il s'arrête à ES2017 (mesuré le 18/09 sur du chaînage
    optionnel). Recette : skill `renommage-api` §4bis.
    """

    def _js(self, chemin):
        from pathlib import Path
        import wama
        return (Path(wama.__file__).parent.parent / chemin).read_text(encoding='utf-8')

    def test_l_input_d_image_est_RESOLU_avec_un_repli_jamais_suppose(self):
        js = self._js('wama/imager/static/imager/js/input_card.js')
        i = js.index('const refInput =')
        bloc = js[i:i + 220]
        self.assertIn('d.fileInputId', bloc,
                      "`refInput` ne se replie plus sur le port de travail : sur une card qui "
                      "ne rend pas d'input de référence, le dépôt ira nulle part EN SILENCE")
        self.assertIn('refInputId', js[i:i + 320],
                      'l’id résolu doit être exposé — les consommateurs (attache, appariement) '
                      'ne doivent plus lire `d.refInputId` directement')

    def test_l_attache_et_l_appariement_lisent_l_id_RESOLU(self):
        js = self._js('wama/imager/static/imager/js/input_card.js')
        self.assertIn('attach:      [refInputId],', js,
                      'l’attache vise encore l’id DÉCLARÉ au lieu de l’id résolu')
        self.assertNotIn('attach:      [d.refInputId],', js)
        self.assertIn('inputId: refInputId,', js,
                      'le slot d’appariement vise encore l’id déclaré')

    def test_la_copie_SERVIE_est_le_meme_fichier(self):
        """`staticfiles/` est ce que le navigateur reçoit : une modification qui ne s'y
        resynchronise pas ne change rien à l'écran, et rien ne le signale."""
        import hashlib
        a = self._js('wama/imager/static/imager/js/input_card.js')
        b = self._js('staticfiles/imager/js/input_card.js')
        self.assertEqual(hashlib.sha256(a.encode()).hexdigest(),
                         hashlib.sha256(b.encode()).hexdigest(),
                         'staticfiles/ n’a pas été resynchronisé — le navigateur sert l’ancien')


class DeclaredCompositionTest(TestCase):
    """L'anatomie déclarée des modèles imager (2026-09-19, chantier VRAM décision A).

    Ces déclarations ne servent pas qu'à décrire : elles décident de ce que
    `model_installer.components_for_spec` PÈSE et de ce que `patterns_from_composition` TIRE.
    Une déclaration fausse n'échoue donc pas bruyamment — elle rend deux chiffres plausibles et
    faux. D'où ces gardes, toutes HORS RÉSEAU : le relevé sur les vraies cartes HF vit dans les
    commentaires de `model_config`, il ne peut pas tourner dans une suite de tests.
    """

    def _declared(self):
        from wama.imager.utils.model_config import IMAGER_MODELS
        return {mid: cfg['composition'] for mid, cfg in IMAGER_MODELS.items()
                if cfg.get('composition')}

    def test_every_declaration_passes_the_manifest_schema(self):
        """Le schéma est celui des manifestes — pas un second formalisme pour l'imager."""
        from wama.common.manifests.builtin.model import _validate_composition
        declarations = self._declared()
        self.assertGreaterEqual(len(declarations), 12, "les compositions imager ont disparu")
        for mid, composition in declarations.items():
            self.assertEqual(_validate_composition(composition), [],
                             f"{mid} : composition hors schéma")

    def test_a_pattern_names_its_own_role_and_excludes_the_variants(self):
        """Un motif doit être ANCRÉ sur le dossier de son rôle : `vae/*` suffirait à faire
        entrer les 44 Go du pipeline dupliqué sous `vae/` de LTX-distilled, et un `*` nu
        ramasserait les copies `.fp16`, `.bf16`, `.non_ema` et OpenVINO."""
        for mid, composition in self._declared().items():
            for comp in composition['components']:
                pattern, role = comp['pattern'], comp['role']
                self.assertTrue(pattern.startswith(role + '/'),
                                f"{mid}/{role} : le motif ne commence pas par son rôle")
                self.assertTrue(pattern.endswith('.safetensors'),
                                f"{mid}/{role} : seul le format safetensors est déclaré")
                # ⚠ `.fp16`/`.bf16` NE SONT PLUS interdits ici (2026-09-20) : cette assertion
                # disait « une précision marquée est une COPIE », et la MESURE l'a réfutée —
                # SDXL n'a QUE ses fichiers `.fp16` sur ce disque, et c'est eux que le backend
                # demande (`diffusers_backend.py:304`, `variant="fp16"` dès que le dtype est
                # float16). Un marqueur de précision désigne une copie quand la forme pleine
                # coexiste, et LE modèle quand elle est seule — un motif ne permet pas de le
                # savoir, seul le disque le dit. Ce qui reste interdit ne dépend, lui, d'aucun
                # état : les poids d'ENTRAÎNEMENT et ceux d'un AUTRE moteur ne sont jamais le
                # modèle que WAMA charge.
                for marker in ('non_ema', 'openvino', 'flax', 'onnx', 'msgpack'):
                    self.assertNotIn(marker, pattern,
                                     f"{mid}/{role} : {marker} n'est pas un composant chargé")

    def test_the_discovery_carries_the_declaration_to_the_catalog(self):
        """Le trou fermé le 19/09 : la déclaration existait, la découverte ne la transmettait
        pas — `ModelInfo` naissait sans `composition`, donc les composants n'atteignaient jamais
        le catalogue. Une déclaration que personne ne transporte ne décide de rien."""
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._discover_imager_models()
        carried = {key: info.composition for key, info in registry._models.items()
                  if (info.composition or {}).get('components')}
        self.assertGreaterEqual(len(carried), 12,
                                "la découverte imager ne transporte pas les compositions")
        fastwan = carried.get('imager:fastwan-2.2-ti2v-5b') or {}
        self.assertEqual({c['role'] for c in fastwan.get('components', [])},
                         {'transformer', 'text_encoder', 'vae'})

    def test_an_adapter_declares_nothing_rather_than_a_misleading_weight(self):
        """La LoRA logo ne pèse que 0,04 Go de fichier, mais son empreinte est celle de sa
        dorsale FLUX.1-dev. Declarer sa composition ferait répondre « 0,04 Go » — exact sur les
        fichiers, faux sur l'empreinte. Mieux vaut indéterminable qu'un chiffre trompeur."""
        from wama.imager.utils.model_config import IMAGER_MODELS
        lora = IMAGER_MODELS['flux-lora-logo-design']
        self.assertEqual(lora.get('model_type'), 'lora')
        self.assertNotIn('composition', lora,
                         "une composition ici ferait passer 0,04 Go pour l'empreinte du modèle")
        self.assertTrue(lora.get('base_model'), "la dorsale doit rester déclarée")
