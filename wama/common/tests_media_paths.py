"""Confinement des chemins sous MEDIA_ROOT — LA brique, et le gardien qui interdit d'en réécrire une.

Née le 2026-09-05 (`MEDIA_STORAGE_TIERING §8.6` D1-D3). Avant elle, 17 sites du dépôt
contrôlaient chacun à leur façon qu'un chemin reçu de l'utilisateur restait sous MEDIA_ROOT,
et deux familles étaient FAUSSES :
  - `Path(MEDIA_ROOT) / server_path` sans `resolve()` ni contrôle (synthesizer) — un `..`
    lisait n'importe quel fichier du serveur ;
  - `str(abs).startswith(str(root))` — un dossier FRÈRE dont le nom commence pareil
    (`media_backup/` à côté de `media/`) passait.
Ces tests fixent le contrat de la brique ET balaient le dépôt : l'idiome par préfixe ne
doit plus réapparaître (même famille que `tests_downloads`, gardien des Content-Disposition).
"""
import re
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.utils.media_paths import OutsideMediaRoot, resolve_under_media_root

RACINE_DEPOT = Path(__file__).resolve().parents[2]


class ResolveUnderMediaRootTest(SimpleTestCase):

    def setUp(self):
        # Un MEDIA_ROOT jetable ET un dossier FRÈRE au nom préfixé : c'est lui qui distingue
        # une frontière de chemin d'une comparaison de chaînes.
        self._tmp = tempfile.TemporaryDirectory(prefix='wama_mr_')
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / 'media'
        self.frere = base / 'media_backup'
        (self.root / 'app' / '1' / 'input').mkdir(parents=True)
        self.frere.mkdir()
        (self.root / 'app' / '1' / 'input' / 'a.txt').write_text('a')
        (self.frere / 'secret.txt').write_text('s')
        (base / 'hors.txt').write_text('h')
        self._ovr = override_settings(MEDIA_ROOT=str(self.root))
        self._ovr.enable()
        self.addCleanup(self._ovr.disable)

    def test_un_chemin_relatif_se_resout_sous_la_racine(self):
        abs_path, rel = resolve_under_media_root('app/1/input/a.txt')
        self.assertEqual(abs_path, (self.root / 'app/1/input/a.txt').resolve())
        self.assertEqual(rel, 'app/1/input/a.txt')

    def test_un_chemin_absolu_sous_la_racine_est_accepte(self):
        abs_path, rel = resolve_under_media_root(self.root / 'app/1/input/a.txt')
        self.assertEqual(rel, 'app/1/input/a.txt')

    def test_la_traversee_par_point_point_est_refusee(self):
        with self.assertRaises(OutsideMediaRoot):
            resolve_under_media_root('app/1/input/../../../../hors.txt')

    def test_le_dossier_frere_au_nom_prefixe_est_refuse(self):
        """Le cas que `startswith(str(root))` laissait passer : `media_backup/` commence
        par `media`."""
        with self.assertRaises(OutsideMediaRoot):
            resolve_under_media_root(self.frere / 'secret.txt')

    def test_un_absolu_etranger_est_refuse(self):
        with self.assertRaises(OutsideMediaRoot):
            resolve_under_media_root(Path(self._tmp.name) / 'hors.txt')

    def test_le_fichier_absent_leve_FileNotFoundError_sauf_si_on_ne_l_exige_pas(self):
        with self.assertRaises(FileNotFoundError):
            resolve_under_media_root('app/1/input/absent.txt')
        abs_path, rel = resolve_under_media_root('app/1/input/absent.txt', must_exist=False)
        self.assertEqual(rel, 'app/1/input/absent.txt')

    def test_le_chemin_rendu_est_posix_quelle_que_soit_la_plateforme(self):
        # Un `Path` natif (séparateur de l'OS) → le relatif rendu est TOUJOURS posix : c'est
        # lui qui va dans `FileField.name`. ⚠ Ne pas tester avec une chaîne à `\` : sous
        # Linux c'est un caractère de nom valide, et le test mentirait sur une plateforme.
        _abs, rel = resolve_under_media_root(Path('app', '1', 'input', 'a.txt'))
        self.assertEqual(rel, 'app/1/input/a.txt')


class AucunConfinementReecritTest(SimpleTestCase):
    """Gardien : l'idiome `startswith(str(<racine>))` ne doit plus exister dans wama/.

    Un contrôle recopié est un contrôle qui divergera — c'est exactement ce qui s'est
    passé 17 fois. La seule mention tolérée est celle qui EXPLIQUE l'interdiction
    (docstring de `tool_api._resolve_user_path`).
    """

    IDIOME = re.compile(r"startswith\(str\((media_root|racine|Path\(settings\.MEDIA_ROOT\))")
    TOLERE = {('wama/tool_api.py', 'recopiait son')}

    def test_aucun_site_ne_confine_par_prefixe_de_chaine(self):
        from wama.common.sandbox import LABEL_RE
        fautifs = []
        for py in (RACINE_DEPOT / 'wama').rglob('*.py'):
            # Les JUMELLES (`wama/<app>_NN/`, gitignorées) sont des copies-témoins régénérées
            # à la demande : les balayer mesurerait l'ARBRE, pas la logique. Vécu au premier
            # run — `converter_01/views.py` portait l'idiome de sa génération d'avant.
            if 'migrations' in py.parts or any(LABEL_RE.match(p) for p in py.parts):
                continue
            for no, ligne in enumerate(py.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                if self.IDIOME.search(ligne):
                    rel = py.relative_to(RACINE_DEPOT).as_posix()
                    if any(rel == f and marque in ligne for f, marque in self.TOLERE):
                        continue
                    fautifs.append(f'{rel}:{no}')
        self.assertEqual(fautifs, [],
                         'confinement réécrit par préfixe de chaîne — passer par '
                         '`media_paths.resolve_under_media_root` : ' + ', '.join(fautifs))


class FormeDuCheminEnUnSeulEndroitTest(SimpleTestCase):
    """Aucun site ne fabrique plus `<app>/<user>/<sous-dossier>` à la main.

    C'est le PRÉALABLE au domicile unique par utilisateur (demande Fabien 2026-09-11 : tous les
    fichiers importés sous `users/<u>/`, condition d'un chiffrement par utilisateur). Mesuré
    avant portage : **61 littéraux** répartis sur 4 fichiers, dont une table déclarative de 43
    entrées dans l'arbre du gestionnaire de fichiers.

    Pourquoi un test et pas une intention : un littéral oublié ne casse RIEN au moment du
    déplacement. Il devient un dossier vide dans l'arbre, une preview morte, ou un import qui
    écrit encore à l'ancien endroit — et aucune erreur ne le dit. C'est exactement la famille
    « garde muette » que ce dépôt traque.
    """

    #: Les fichiers qui portaient les 61 littéraux. On les tient explicitement plutôt que de
    #: balayer tout `wama/` : un balayage large attraperait des chaînes de tests et de
    #: migrations, et un test qui crie à tort finit par être ignoré.
    FICHIERS = (
        'wama/filemanager/views.py',
        'wama/tool_api.py',
        'wama/anonymizer/views.py',
        'wama/converter/views.py',
    )

    #: `users/<u>/…` est EXCLU : le temp de l'utilisateur est déjà chez lui, c'est la forme
    #: CIBLE, pas celle qu'on pourchasse.
    MOTIF = re.compile(r"""f['"](?!users/)[a-z_]+/\{user(?:_id|\.id)\}/(?:input|output)""")

    #: ⚠ SECOND MOTIF, ajouté le 2026-09-12 — parce que le premier a laissé passer le site qui
    #: a réellement cassé. Il exigeait un nom d'app LITTÉRAL (`converter/{user_id}/…`) suivi
    #: d'un sous-dossier ; `_allowed_app_prefixes` du gestionnaire de fichiers, lui, boucle sur
    #: le catalogue et compose `f'{app}/{user_id}/'` — nom VARIABLE, et une PAIRE, pas un
    #: triplet. La garde ne l'a jamais vu, et un préfixe d'autorisation resté à l'ancien
    #: domicile n'aurait rien cassé bruyamment : il aurait refusé les fichiers, en affichant
    #: « aperçu non disponible ».
    #: *Une garde écrite sur la forme COMPLÈTE d'un chemin est aveugle à ses PRÉFIXES.*
    MOTIF_VARIABLE = re.compile(r"""f['"]\{(?:app|app_name|app_label|label)\}/\{user(?:_id|\.id)\}/""")

    #: Les lignes où l'ancienne forme est VOULUE, avec la raison. Une tolérance sans raison
    #: écrite redevient un trou au premier relecteur.
    TOLERE_ANCIENNE_FORME = (
        ('wama/filemanager/views.py', 'arbre historique — orphelins non migrés'),
    )

    def _src(self, chemin):
        from pathlib import Path
        import wama
        return (Path(wama.__file__).parent.parent / chemin).read_text(encoding='utf-8')

    def test_aucun_litteral_de_chemin_d_app_ne_subsiste(self):
        fautifs = {}
        for f in self.FICHIERS:
            trouves = self.MOTIF.findall(self._src(f))
            if trouves:
                fautifs[f] = len(trouves)
        self.assertEqual({}, fautifs,
                         'des chemins d’app sont encore écrits à la main — ils resteront à '
                         f'l’ancien endroit le jour du déplacement, en silence : {fautifs}')

    def test_aucun_PREFIXE_d_app_a_nom_variable_ne_subsiste(self):
        """Le trou que la garde ci-dessus a laissé passer — cf. `MOTIF_VARIABLE`.

        Une ligne tolérée doit porter sa raison EN COMMENTAIRE sur place ; ici on vérifie qu'il
        n'en reste pas d'autre que celle-là.
        """
        fautifs = []
        for f in self.FICHIERS:
            tolerees = sum(1 for fic, _ in self.TOLERE_ANCIENNE_FORME if fic == f)
            trouves = self.MOTIF_VARIABLE.findall(self._src(f))
            if len(trouves) > tolerees:
                fautifs.append(f'{f} : {len(trouves)} trouvé(s), {tolerees} toléré(s)')
        self.assertEqual([], fautifs,
                         'un PRÉFIXE de dossier d’app est composé à la main avec un nom d’app '
                         'variable — il pointera vers l’ancien domicile en silence : '
                         + ', '.join(fautifs))

    def test_la_brique_rend_le_DOMICILE_UNIQUE_de_l_utilisateur(self):
        """La bascule est faite (2026-09-12) : `users/<uid>/<app>/<sub>`.

        ⚠ Ce test affirmait l'inverse jusqu'au 2026-09-11 — il gardait la forme HISTORIQUE, et
        c'était juste : P2a centralisait les 61 littéraux à forme CONSTANTE, précisément pour
        que le déplacement du parc (P2b) soit débogable. Les deux gestes sont maintenant faits,
        dans cet ordre, et c'est l'ordre qui a permis de distinguer « un littéral oublié » de
        « un rename raté ».

        Ce que ce test garde désormais : l'utilisateur d'abord. Un chemin qui recommencerait
        par le nom de l'app redisperserait ses octets dans 11 arbres, et le chiffrement par
        utilisateur demandé par Fabien n'aurait plus d'objet.
        """
        from wama.common.utils.media_paths import app_media_dir, get_relative_media_path
        self.assertEqual('users/7/anonymizer/input', app_media_dir('anonymizer', 7, 'input'))
        self.assertEqual('users/42/imager/output', app_media_dir('imager', '42', 'output'))
        self.assertEqual('users/3/reader/input/x.pdf',
                         get_relative_media_path('reader', 3, 'input', 'x.pdf'))

    def test_tout_chemin_media_d_app_commence_par_le_domicile_de_l_utilisateur(self):
        """L'INVARIANT, plutôt que trois exemples : c'est lui que le chiffrement suppose.

        Une app ajoutée demain le satisfait sans qu'on ait à ajouter sa ligne ici — c'est la
        différence entre une garde et une liste.
        """
        from wama.common.utils.media_paths import app_media_dir
        for app in ('anonymizer', 'imager', 'reader', 'transcriber', 'converter_01'):
            for sub in ('input', 'output'):
                self.assertTrue(app_media_dir(app, 5, sub).startswith('users/5/'),
                                f"{app}/{sub} sort du domicile de l'utilisateur")

    def test_get_relative_media_path_DERIVE_de_la_brique(self):
        """Deux fonctions qui composent le même chemin divergeraient au premier changement."""
        from wama.common.utils.media_paths import app_media_dir, get_relative_media_path
        for app, uid, sub in (('describer', 1, 'input'), ('enhancer', 9, 'output')):
            self.assertTrue(
                get_relative_media_path(app, uid, sub, 'f.bin').startswith(
                    app_media_dir(app, uid, sub) + '/'))

    def test_le_temp_utilisateur_n_est_PAS_touche(self):
        """Il est déjà à sa place cible : le porter le ferait passer par une brique d'APP,
        ce qu'il n'est pas."""
        src = self._src('wama/tool_api.py')
        self.assertIn("'temp':               'users/{user_id}/temp'", src)


class ChaqueChampFichierEcritAuDomicileTest(TestCase):
    """DÉRIVÉ des modèles, pas d'une liste : où chaque `FileField` écrirait-il aujourd'hui ?

    ⚠ La garde d'à côté atteste que `app_media_dir` rend la bonne forme. Elle ne dit RIEN d'un
    champ qui ne passerait pas par elle — or c'est exactement ce qui s'est produit le
    2026-09-12 : `get_app_media_url` composait sa chaîne à la main et a survécu au portage des
    61 littéraux parce qu'elle EST une brique, et qu'on ne cherchait que des littéraux d'app.
    Après la bascule elle aurait été seule à pointer vers l'ancien domicile — des aperçus
    morts, sans une erreur.

    Ce test interroge donc les CHAMPS : pour chacun, on demande à son `upload_to` le chemin
    qu'il produirait. Un champ câblé autrement se signale ici, y compris celui qu'on ajoutera
    demain sans penser à ce fichier.
    """

    #: Champs qui n'écrivent PAS dans un dossier d'app — ils ont leur propre domicile, et le
    #: leur est déjà sous `users/` ou hors périmètre assumé (médiathèque, montages).
    HORS_PERIMETRE = ('media_library', 'filemanager')

    def test_aucun_champ_n_ecrit_hors_du_domicile_de_l_utilisateur(self):
        from django.apps import apps as django_apps
        from django.db import models as dj

        fautifs, muets = [], []
        for modele in django_apps.get_models():
            if modele._meta.app_label in self.HORS_PERIMETRE:
                continue
            for champ in modele._meta.get_fields():
                if not isinstance(champ, dj.FileField):
                    continue
                upload_to = getattr(champ, 'upload_to', None)
                if not callable(upload_to):
                    continue          # chaîne fixe ou vide : hors de ce contrat
                nom = f'{modele._meta.app_label}.{modele.__name__}.{champ.name}'
                chemin = self._chemin_simule(modele, upload_to)
                if chemin is None:
                    muets.append(nom)
                elif not chemin.startswith('users/7/'):
                    fautifs.append(f'{nom} → {chemin}')

        self.assertEqual([], fautifs,
                         'des champs fichier écrivent HORS du domicile de l’utilisateur — '
                         'leurs octets échapperont au chiffrement par utilisateur : '
                         + ', '.join(fautifs))
        # ⚠ Un champ qu'on ne sait pas simuler n'est PAS un champ conforme : c'est un champ
        # NON MESURÉ. Le sauter en silence est exactement ce qui a laissé `cam_upload_path`
        # écrire dans l'ancien arbre pendant que tout le reste basculait. On borne donc la
        # liste des muets : elle peut RÉTRÉCIR, jamais grandir sans qu'on le décide.
        self.assertLessEqual(
            len(muets), self.MUETS_ASSUMES,
            f'{len(muets)} champ(s) fichier NON MESURÉS (contrat : ≤ {self.MUETS_ASSUMES}) — '
            'leur `upload_to` dépend d’un état que ce test ne sait pas construire, donc '
            'personne ne vérifie où ils écrivent : ' + ', '.join(sorted(muets)))

    #: Champs dont l'`upload_to` demande un état qu'on ne fabrique pas ici (relation absente).
    #: Mesuré le 2026-09-12 : les 2 de `face_analyzer`. Ce nombre est un PLAFOND, pas un
    #: objectif — le faire monter, c'est cesser de mesurer un champ de plus.
    MUETS_ASSUMES = 2

    @staticmethod
    def _chemin_simule(modele, upload_to):
        """Chemin que ce champ produirait pour l'utilisateur 7, ou `None` si non simulable.

        ⚠ Deux façons de porter son utilisateur, et la seconde est celle qui manquait :
        directement (`user`) ou par une RELATION (`cam_analyzer.CameraView.session.user`).
        Ne connaître que la première revenait à ne pas mesurer le seul champ que le pré-vol
        de migration avait justement signalé.
        """
        from django.contrib.auth import get_user_model

        champs = {f.name: f for f in modele._meta.get_fields()}
        if 'user' in champs:
            instance = modele(user_id=7)
        elif 'session' in champs and getattr(champs['session'], 'related_model', None):
            # ⚠ Un `Mock` est REFUSÉ par Django sur une clé étrangère (« must be a
            # AnalysisSession instance ») : on monte de vrais objets NON SAUVEGARDÉS, ce qui
            # suffit à `instance.session.user.id` sans toucher la base.
            intermediaire = champs['session'].related_model()
            intermediaire.user = get_user_model()(id=7)
            instance = modele()
            instance.session = intermediaire
        else:
            return None
        try:
            return upload_to(instance, 'fichier.bin').replace('\\', '/')
        except Exception:
            return None
