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

from django.test import SimpleTestCase, override_settings

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

    def test_la_brique_rend_la_forme_historique_a_l_identique(self):
        """P2a ne DÉPLACE rien : il centralise. Mélanger les deux gestes rendrait le
        déplacement indébogable — on ne saurait pas si un chemin faux vient du portage ou du
        nouveau domicile."""
        from wama.common.utils.media_paths import app_media_dir, get_relative_media_path
        self.assertEqual('anonymizer/7/input', app_media_dir('anonymizer', 7, 'input'))
        self.assertEqual('imager/42/output', app_media_dir('imager', '42', 'output'))
        self.assertEqual('reader/3/input/x.pdf',
                         get_relative_media_path('reader', 3, 'input', 'x.pdf'))

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
