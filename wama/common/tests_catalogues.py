"""
CONFORMITÉ des trois autres registres déclaratifs — `MECANISMES`, `MANIFEST_KINDS`, `APP_CATALOG`.

POURQUOI CE FICHIER (pending #6 du §REPRISE 2026-08-22 « WAMA DATA → MONDES → REGISTRES »)

    `tests_registries.py::ConformiteTest` a porté l'infrastructure de test SUR le registre des
    registres : chaque contrôle boucle sur TOUS les registres, donc le 8ᵉ hérite de la couverture
    en naissant. Le défaut qui l'a motivé — « en ajoutant un registre la suite ne tombait pas,
    **elle devenait muette** » — n'était pas propre à ce registre-là. Il vaut pour tout registre
    déclaratif du dépôt. Mesuré avant d'écrire, le 2026-08-22 :

        MECANISMES      88 entrées → **0 test**            (ni contrat, ni sémantique)
        MANIFEST_KINDS   7 entrées → **0 test** nommant le registre
        APP_CATALOG     11 entrées → 2 tests (`tests.py`), dont un plancher `len >= 10`

    Un plancher n'est pas un contrat : il reste vert quand la 12ᵉ app arrive avec une catégorie
    inventée. C'est le même vert trompeur, une strate plus bas.

CE QUE CES CONTRÔLES COUVRENT, ET CE QU'ILS NE COUVRENT PAS

    Le CONTRAT d'une entrée : ses champs obligatoires, ses références qui doivent résoudre
    (fichier, document, URL), ses valeurs qui doivent appartenir à une énumération, la cohérence
    entre deux champs qui se conditionnent. La SÉMANTIQUE reste ailleurs — « le scan détecte-t-il
    un modèle renommé ? » est irréductiblement spécifique, et `mecanismes_scan` a ses propres
    contrôles côté `doc_facts`.

⚠ ON NE REDIT PAS CE QUI EST DÉJÀ TESTÉ. `tests.py::PagesSmokeTests` résout et REND l'index de
    chaque app du catalogue : la résolvabilité d'`url_name` y est donc déjà prouvée, plus fort
    qu'ici. On ne la reprend pas — en revanche les `extra_links` des CATÉGORIES n'étaient testés
    nulle part, alors que le registre porte la trace d'un lien silencieusement omis par le garde
    `NoReverseMatch` (commentaire d'`APP_CATEGORIES`). C'est là qu'il manquait un test.

⚠ LE PIÈGE DU VERT SUR DU VIDE. Une boucle sur un registre vide passe : zéro sous-test, zéro
    échec. Deux harnais du dépôt ont déjà annoncé « 0 FAIL » sur du vide. Chaque classe vérifie
    donc d'abord que son registre est peuplé — sans quoi tous les contrôles qui suivent mentent.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import NoReverseMatch, reverse


def _base() -> Path:
    return Path(settings.BASE_DIR)


def _fichier_du_doc(doc: str) -> str:
    """`doc` s'écrit « CHEMIN.md §ancre » — l'ancre n'est pas une partie du chemin.

    Sans cette découpe le contrôle déclare 24 documents introuvables sur 57 (mesuré en écrivant
    ce fichier) : un faux positif massif, qui aurait fait retirer le contrôle plutôt que corriger
    les entrées.
    """
    return doc.split(' §')[0].strip()


class MecanismesConformiteTest(TestCase):
    """Contrat des mécanismes déclarés (le NOMBRE vit dans le registre, jamais ici — « 88 »
    écrit à cette place était devenu faux à 109) — la carte `WAMA_MECANISMES.md` est
    GÉNÉRÉE d'ici.

    Une entrée fausse ne casse rien à l'exécution : elle produit une ligne de carte qui pointe
    dans le vide, ou un compte de consommateurs mesuré sur le mauvais symbole. Donc rien ne la
    signale, sauf ceci.
    """

    def _chaque(self):
        from wama.common.mecanismes import MECANISMES
        return sorted(MECANISMES, key=lambda m: m.cle)

    def test_le_registre_est_peuple(self):
        # Garde anti-« vert sur du vide » : sans elle, un import cassé rendrait toute la classe
        # verte en n'exécutant aucun sous-test.
        self.assertGreaterEqual(len(self._chaque()), 80)

    def test_cle_unique(self):
        cles = [m.cle for m in self._chaque()]
        doublons = sorted({c for c in cles if cles.count(c) > 1})
        self.assertEqual(doublons, [], f"clés déclarées deux fois : {doublons}")

    def test_identite_declaree(self):
        # `nom` et `role` sont le texte de la carte : vides, la ligne existe sans rien dire.
        for m in self._chaque():
            with self.subTest(mecanisme=m.cle):
                self.assertTrue(m.cle.strip(), "clé vide")
                self.assertTrue(m.nom.strip(), "nom non déclaré")
                self.assertTrue(m.role.strip(), "rôle non déclaré")

    def test_domaine_pose_sur_chaque_entree(self):
        """Le domaine est posé par `_domaine()` sur un GROUPE — une entrée hors groupe le perd.

        Elle disparaît alors de toutes les sous-tables de la carte : la ligne n'est pas fausse,
        elle est invisible. C'est le défaut trouvé sur `app_sandbox` en écrivant ce test.
        """
        for m in self._chaque():
            with self.subTest(mecanisme=m.cle):
                self.assertTrue(m.domaine, "domaine vide — entrée déclarée hors d'un _domaine()")

    def test_domicile_existe(self):
        for m in self._chaque():
            with self.subTest(mecanisme=m.cle):
                self.assertTrue((_base() / m.domicile).exists(),
                                f"domicile introuvable : {m.domicile}")

    def test_annexes_existent(self):
        for m in self._chaque():
            for annexe in m.annexes:
                with self.subTest(mecanisme=m.cle, annexe=annexe):
                    self.assertTrue((_base() / annexe).exists(), f"annexe introuvable : {annexe}")

    def test_doc_designe_un_document_DU_DEPOT(self):
        """Un `doc` sert à qui lit le dépôt. Il doit donc s'y ouvrir.

        `doc=''` est licite et VOULU : c'est le trou que la carte rend visible (31 mécanismes au
        2026-08-22). Ce qui ne l'est pas, c'est un pointeur que personne ne peut suivre — défaut
        trouvé ici sur `org_sync`, qui désignait un souvenir d'agent et non un fichier.
        """
        for m in self._chaque():
            if not m.doc:
                continue
            with self.subTest(mecanisme=m.cle):
                fichier = _fichier_du_doc(m.doc)
                self.assertTrue(fichier.endswith('.md'),
                                f"doc={m.doc!r} ne désigne pas un document du dépôt")
                self.assertTrue((_base() / fichier).exists(), f"document introuvable : {fichier}")

    def test_symbole_appartient_au_mecanisme(self):
        """⚠ Le contrat exact vient de l'ACCESSEUR, pas de l'intuition.

        `mecanismes_scan.consommateurs()` cherche le symbole PARTOUT SAUF dans le domicile et les
        annexes — un symbole absent du domicile n'est donc pas fautif (`api_v1` est un namespace
        d'URL déclaré dans `urls.py`, l'annexe). Ce qui serait fautif, c'est un symbole que le
        mécanisme ne possède nulle part : le compte porterait alors sur le bien d'autrui.
        """
        for m in self._chaque():
            if not m.symbole:
                continue
            with self.subTest(mecanisme=m.cle):
                siens = [m.domicile, *m.annexes]
                present = any(
                    (_base() / rel).exists()
                    and m.symbole in (_base() / rel).read_text(encoding='utf-8', errors='ignore')
                    for rel in siens
                )
                self.assertTrue(present,
                                f"symbole '{m.symbole}' absent des fichiers du mécanisme {siens}")

    def test_un_fichier_de_harnais_ne_rend_pas_une_app_ADOPTANTE(self):
        """MESURER un mécanisme n'est pas l'ADOPTER (corrigé le 2026-09-08).

        `apps_consommatrices` alimente le contrôle de jonction, dont la phrase est « mécanismes
        de niveau app SANS critère de grille — **adoptés par des apps** ». Un `tests*.py` y
        entrait comme n'importe quel fichier : un test ajouté à `wama/imager/tests.py`, qui
        appelle `queue_dnd_attrs` pour construire l'URL que le gabarit émet (c'est le BON test),
        faisait apparaître « `queue_dnd` adopté par 1 app : imager ».

        Le biais portait sur **83 mécanismes** / **328** fichiers de harnais comptés. Et il est
        CORROBORÉ par une trouvaille indépendante du même jour : la recalibration de la grille a
        constaté que la preuve de `backend_contract` pointait `tests_table_transformer.py`
        (reader) et `nightly_scenarios.py` (enhancer) — mêmes deux apps que cette exclusion
        retire ici. *Deux instruments, un seul biais.*

        ⚠ La colonne « consommateurs » de la carte n'est PAS touchée : un test importe
        réellement le domicile, ce compte ne mentait pas.
        """
        from wama.common.services.mecanismes_scan import _est_harnais, apps_consommatrices

        for rel, attendu in (('wama/imager/tests.py', True),
                             ('wama/common/tests_queue_dnd.py', True),
                             ('wama/common/services/nightly_scenarios.py', True),
                             ('wama/common/services/test_utils.py', True),
                             ('wama/imager/views.py', False),
                             ('wama/common/templates/common/_queue_toolbar.html', False),
                             # Piège : le nom CONTIENT « test » sans être un harnais.
                             ('wama/common/utils/latest_tests.py', False)):
            with self.subTest(fichier=rel):
                self.assertEqual(attendu, _est_harnais(rel))

        # Contre-épreuve fonctionnelle : un mécanisme dont le SEUL consommateur d'app est un
        # harnais ne doit produire AUCUNE app adoptante.
        faux = type('M', (), {'domicile': 'wama/common/x.py', 'annexes': (), 'symbole': ''})()
        self.assertEqual([], apps_consommatrices(faux, {}, ['wama/imager/tests.py']))


class ManifestKindsConformiteTest(TestCase):
    """Contrat des 7 kinds de manifeste. Aucun défaut au 2026-08-22 : garde pour le 8ᵉ.

    C'est le sens même de l'exercice — ces contrôles ne valent pas par ce qu'ils trouvent
    aujourd'hui, mais par ce qu'un kind ajouté demain ne pourra plus contourner en silence.
    """

    def _chaque(self):
        from wama.common.manifests import MANIFEST_KINDS
        return sorted(MANIFEST_KINDS.items())

    def test_le_registre_est_peuple(self):
        # Les kinds sont enregistrés par IMPORT À EFFET DE BORD (`manifests/__init__.py`) : un
        # import réordonné les ferait tous disparaître sans lever.
        self.assertGreaterEqual(len(self._chaque()), 7)

    def test_cle_du_dict_et_kind_declare_coincident(self):
        # `get_kind()` sert par la clé du dict, `extract()` réécrit `kind` dans l'enveloppe :
        # les deux divergeant, un manifeste sortirait étiqueté autrement qu'il n'a été demandé.
        for cle, mk in self._chaque():
            with self.subTest(kind=cle):
                self.assertEqual(mk.kind, cle)

    def test_description_declaree(self):
        for cle, mk in self._chaque():
            with self.subTest(kind=cle):
                self.assertTrue((mk.description or '').strip(), "description non déclarée")

    def test_validate_rend_une_LISTE_sans_lever(self):
        """`validate` est appelé sur du `body` arbitraire (ingest d'un fichier fourni).

        Il doit rapporter les erreurs, jamais les propager : une exception ici remonterait en 500
        au lieu d'un compte-rendu de validation.
        """
        for cle, mk in self._chaque():
            with self.subTest(kind=cle):
                self.assertTrue(callable(mk.validate))
                try:
                    erreurs = mk.validate({})
                except Exception as exc:                      # noqa: BLE001 — c'est le défaut visé
                    self.fail(f"validate({{}}) lève {type(exc).__name__}: {exc}")
                self.assertIsInstance(erreurs, list)

    def test_extract_rend_None_sur_une_cle_inconnue(self):
        # Contrat du round-trip : « pas d'entrée » se dit par None, pas par une exception —
        # `manifest_export` boucle sur des clés dont certaines ont pu disparaître entre-temps.
        for cle, mk in self._chaque():
            if not mk.extract:
                continue
            with self.subTest(kind=cle):
                try:
                    self.assertIsNone(mk.extract('__cle_inexistante_pour_le_test__'))
                except Exception as exc:                      # noqa: BLE001
                    self.fail(f"extract(clé inconnue) lève {type(exc).__name__}: {exc}")

    def test_write_back_et_un_write_back_vont_PAR_PAIRE(self):
        """La réversibilité est au contrat (spec §7.1) : ce qu'un kind écrit, il doit le retirer.

        Un `write_back` sans retour laisse des entrées dérivées qu'aucun geste ne défait — la
        moitié d'un mécanisme, et c'est la moitié qui salit.
        """
        for cle, mk in self._chaque():
            with self.subTest(kind=cle):
                self.assertEqual(bool(mk.write_back), bool(mk.un_write_back),
                                 "write_back et un_write_back doivent être déclarés ensemble")

    def test_le_write_back_expose_apply_en_MOT_CLE(self):
        """`apply=False` = dry-run. Positionnel, un appelant l'inverserait par accident.

        L'annotation d'origine (`Callable[[dict], None]`) ne décrivait ni l'argument ni le retour,
        et faisait diagnostiquer à tort les implémentations existantes — d'où un contrôle qui
        porte sur la signature RÉELLE plutôt que sur l'annotation.
        """
        for cle, mk in self._chaque():
            for nom, fonction in (('write_back', mk.write_back),
                                  ('un_write_back', mk.un_write_back)):
                if not fonction:
                    continue
                with self.subTest(kind=cle, fonction=nom):
                    params = inspect.signature(fonction).parameters
                    self.assertIn('apply', params, "pas de dry-run possible")
                    self.assertEqual(params['apply'].kind, inspect.Parameter.KEYWORD_ONLY,
                                     "`apply` doit être keyword-only")
                    self.assertIs(params['apply'].default, False,
                                  "le défaut doit être le DRY-RUN")

    #: Kinds qui DÉCLARENT un `write_back`. Inventaire TENU, pas indicatif : l'en-tête de
    #: `kinds.py` porte la table « qui projette, et dans quelle mesure », et elle a MENTI
    #: du 2026-08-11 au 2026-09-09 — elle annonçait « 3 kinds » et rangeait `function`
    #: parmi ceux qui n'en ont PAS, alors qu'il en enregistrait un depuis un mois.
    #: Ajouter ou retirer une projection FAIT TOMBER ce test : c'est le rappel d'aller
    #: rouvrir la table. *Une table d'en-tête que rien ne tient dérive par le haut.*
    KINDS_QUI_PROJETTENT = {'app', 'function', 'library', 'model'}

    def test_l_INVENTAIRE_des_kinds_qui_projettent_est_TENU(self):
        projettent = {cle for cle, mk in self._chaque() if mk.write_back}
        self.assertEqual(
            projettent, self.KINDS_QUI_PROJETTENT,
            "l'inventaire des kinds projetants a changé — mettre à jour la table de "
            "l'en-tête de `wama/common/manifests/kinds.py` DANS LE MÊME COMMIT")


class ApplyManifestsRendCompteDesREFUSTest(TestCase):
    """`apply_manifests` doit distinguer « sauté » d'« inchangé ».

    ⚠ DÉFAUT MESURÉ le 2026-09-09 : `--kind function` annonçait « créés 0 · modifiés 0 ·
    **inchangés 62** » alors qu'AUCUN des 62 manifestes n'avait été tenté — tous refusés par
    `write_back_function` (binding `pure`/`app` = catalogue CODE), avec une raison que
    l'appelant JETAIT. Un refus compté comme « déjà synchrone » se lit comme un succès.
    *Un vert qui ne se joue pas est pire qu'un rouge.*
    """

    def _plan(self, kind: str) -> str:
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('apply_manifests', '--kind', kind, stdout=out, stderr=out)
        return out.getvalue()

    def test_un_corpus_entierement_REFUSE_ne_se_dit_pas_inchange(self):
        sortie = self._plan('function')
        # ⚠ Anti-vacuité : sans cette borne, un corpus VIDE ferait passer le test en silence
        # — le défaut « 0 FAIL sur du vide » que deux harnais du dépôt ont déjà commis.
        self.assertRegex(sortie, r'sautés [1-9]',
                         "aucun manifeste `function` sauté : corpus vide ou write_back changé ?")
        self.assertIn('inchangés 0', sortie,
                      "un manifeste REFUSÉ ne doit jamais être compté « inchangé »")

    def test_la_RAISON_du_refus_est_rendue_lisible(self):
        # La raison est ce qui distingue « je n'ai rien eu à faire » de « je n'ai rien tenté ».
        self.assertIn('catalogue CODE', self._plan('function'))

    def test_un_kind_qui_projette_VRAIMENT_ne_saute_rien(self):
        # Contre-épreuve : le compteur ne doit pas s'allumer partout. `library` est le kind
        # d'initialisation — il projette, donc il ne saute rien.
        self.assertIn('sautés 0', self._plan('library'))

    def test_les_DEUX_formes_de_skipped_du_depot_se_lisent(self):
        """`skipped` a deux formes ANTÉRIEURES au lecteur : chaîne (`write_back_function`) et
        liste de `{field, reason}` (`write_back_app`). En inventer une troisième pour
        uniformiser serait le chemin parallèle qu'on refuse."""
        from wama.common.management.commands.apply_manifests import _raison_du_saut
        self.assertEqual(_raison_du_saut('binding pure'), 'binding pure')
        self.assertEqual(
            _raison_du_saut([{'field': 'access', 'reason': 'écrit main'}]),
            'access : écrit main')
        # Une même raison sur N facettes ne se répète pas N fois.
        self.assertEqual(
            _raison_du_saut([{'field': 'a', 'reason': 'r'}, {'field': 'a', 'reason': 'r'}]),
            'a : r')
        self.assertEqual(_raison_du_saut([]), 'sans raison déclarée')


class AppCatalogConformiteTest(TestCase):
    """Contrat des 11 entrées d'`APP_CATALOG` — le registre qui peuple menu, accueil et /apps/.

    L'incident fondateur de `tests.py` (kwarg dupliqué, trois surfaces cassées sans détection)
    a produit un test de PLANCHER (`len >= 10`). Le plancher voit disparaître une app ; il ne voit
    pas une app déclarée de travers. C'est ce niveau-là qu'on ajoute.
    """

    CATEGORIES_DERIVABLES = ('understand', 'create', 'transform')

    def _chaque(self):
        from wama.common.app_registry import APP_CATALOG
        return sorted(APP_CATALOG.items())

    def test_le_registre_est_peuple(self):
        self.assertGreaterEqual(len(self._chaque()), 10)

    def test_champs_d_identite_declares(self):
        # Ces quatre-là sont lus par le menu et la tuile d'accueil : vide, la surface se rend
        # quand même, avec un trou à la place du libellé.
        for nom, spec in self._chaque():
            for champ in ('label', 'icon', 'url_name', 'description'):
                with self.subTest(app=nom, champ=champ):
                    self.assertTrue((spec.get(champ) or '').strip(), f"{champ} non déclaré")

    def test_categorie_connue_et_coherente_avec_les_types(self):
        """La catégorie déclarée PRIME, la dérivation sert de garde-fou (`derive_category`).

        Les deux divergeant, c'est soit la catégorie soit les types qui sont faux — dans les deux
        cas l'app se range ailleurs que là où ses entrées/sorties la placent.
        """
        from wama.common.app_registry import APP_CATEGORIES, derive_category
        for nom, spec in self._chaque():
            with self.subTest(app=nom):
                categorie = spec.get('category')
                self.assertTrue(categorie, "catégorie non déclarée")
                self.assertIn(categorie, APP_CATEGORIES, "catégorie inconnue d'APP_CATEGORIES")
                # La garde ne vaut que pour les 3 catégories DÉRIVABLES des types ; `data`, `lab`
                # et `platform` ne se dérivent pas et sortiraient en faux positif.
                if categorie in self.CATEGORIES_DERIVABLES:
                    self.assertEqual(categorie, derive_category(spec),
                                     "la catégorie déclarée contredit les types déclarés")

    def test_types_d_entree_et_de_sortie_declares(self):
        # L'appariement entrée ↔ app (médiathèque, « envoyer vers ») se fait sur ces tuples :
        # vides, l'app devient injoignable par ce chemin sans que rien ne le dise.
        for nom, spec in self._chaque():
            with self.subTest(app=nom):
                self.assertTrue(spec.get('input_types'), "input_types non déclarés")
                self.assertTrue(spec.get('output_types'), "output_types non déclarés")

    def test_lot_declare_des_DEUX_cotes(self):
        # `has_batch` ouvre l'UI de lot, `batch_type` dit au parseur quoi lire. L'un sans l'autre
        # donne un bouton qui ne sait pas lire, ou un parseur que rien n'appelle.
        for nom, spec in self._chaque():
            with self.subTest(app=nom):
                self.assertEqual(bool(spec.get('has_batch')), bool(spec.get('batch_type')),
                                 "has_batch et batch_type doivent être déclarés ensemble")

    def test_conventions_completes_et_typees(self):
        """Les conventions viennent TOUTES de `_conv()` — c'est ce qui rend la grille comparable.

        Une clé écrite à la main à côté ne serait mesurée par personne : le critère n'existerait
        que dans cette entrée, et le rapport de conformité l'ignorerait en silence.
        """
        from wama.common.app_registry import _conv
        defauts = _conv()
        attendues = set(defauts)

        # Les conventions NON booléennes se DÉRIVENT du défaut de `_conv()` ; elles ne sont
        # plus reconnues par leur nom écrit ici. `export_binding` l'était en dur — si bien que
        # `export_formats`, ajouté le 2026-08-23 (`af0bb92b`), n'a jamais été exempté et a mis
        # les 11 apps au rouge pendant deux jours pour une faute qui n'était PAS la leur.
        # Une liste tenue à la main dans un test reproduit ce défaut à la clé suivante.
        CONTRATS = {
            'export_binding': (lambda v: v in ('early', 'late'), "'early' ou 'late'"),
            'export_formats': (lambda v: isinstance(v, tuple) and all(isinstance(x, str) for x in v),
                               "tuple de chaînes"),
        }
        # ⚠ `d not in (True, False, None)` et non `isinstance(d, bool)` : le tuple VIDE `()`
        # doit sortir comme non booléen, et c'est bien le cas (`() == False` est faux).
        non_bool = {c for c, d in defauts.items() if d not in (True, False, None)}
        # ⚠ `assertFalse` et non `assertEqual(…, set())` : le diff d'ensembles d'assertEqual
        # s'affiche AVANT le message, et c'est le message qui dit quoi faire. Le nom de la
        # clé fautive doit être la première chose lue.
        sans_contrat = sorted(non_bool - set(CONTRATS))
        self.assertFalse(
            sans_contrat,
            f"convention(s) non booléenne(s) sans contrat dans ce test : {sans_contrat} — "
            f"déclarer ce qu'elles acceptent dans CONTRATS, sinon elles échoueront comme un "
            f"mauvais typage d'app alors que les apps n'y sont pour rien")
        contrat_perime = sorted(set(CONTRATS) - non_bool)
        self.assertFalse(
            contrat_perime,
            f"contrat déclaré pour une convention redevenue booléenne : {contrat_perime} — le retirer")

        for nom, spec in self._chaque():
            with self.subTest(app=nom):
                conventions = spec.get('conventions')
                self.assertTrue(conventions, "conventions non déclarées")
                self.assertEqual(set(conventions), attendues,
                                 "les conventions doivent être produites par _conv()")
                for critere, valeur in conventions.items():
                    if critere in CONTRATS:
                        accepte, libelle = CONTRATS[critere]
                        self.assertTrue(accepte(valeur),
                                        f"{critere}={valeur!r} — attendu {libelle}")
                    else:
                        self.assertIn(valeur, (True, False, None),
                                      f"{critere}={valeur!r} — attendu True/False/None (N/A)")

    def test_export_binding_et_formats_se_repondent(self):
        """`late` ⟺ des formats déclarés. Règle vraie 11 fois sur 11, que RIEN n'imposait.

        `_conv()` documente les deux clés séparément, alors qu'elles décrivent un seul
        mécanisme : la liaison TARDIVE veut dire « le format se choisit au téléchargement »,
        donc un split-button, donc des formats à lui donner. Les deux incohérences possibles
        sont muettes, chacune à sa manière :
          - `late` avec `()`      → un split-button sans rien à proposer ;
          - `early` avec des formats → des formats que le bouton n'offre pas (lien simple),
            déclarés pour personne.
        Mesuré le 2026-08-25 : les 3 apps `late` (describer, reader, transcriber) portent des
        formats, les 8 `early` portent `()`.
        """
        for nom, spec in self._chaque():
            conventions = spec.get('conventions') or {}
            if 'export_binding' not in conventions:
                continue
            with self.subTest(app=nom):
                tardif = conventions.get('export_binding') == 'late'
                formats = conventions.get('export_formats') or ()
                self.assertEqual(
                    tardif, bool(formats),
                    f"export_binding={conventions.get('export_binding')!r} mais "
                    f"export_formats={formats!r} — la liaison tardive exige des formats, "
                    f"la liaison précoce n'en propose aucun")

    def test_extra_links_des_categories_resolvent(self):
        """Le trou que `PagesSmokeTests` ne bouche pas : il boucle sur les APPS, pas sur les liens.

        Le registre porte lui-même la trace du défaut — « le premier jet `face_analyzer:index`
        était silencieusement omis par le garde NoReverseMatch ». Un lien mort n'y lève pas : il
        s'efface du menu, et la surface qu'il désignait devient inatteignable sans un mot.
        """
        from wama.common.app_registry import APP_CATEGORIES
        for cid, meta in sorted(APP_CATEGORIES.items()):
            for lien in (meta.get('extra_links') or ()):
                with self.subTest(categorie=cid, lien=lien.get('label')):
                    self.assertTrue(lien.get('label'), "lien sans libellé")
                    try:
                        reverse(lien['url_name'])
                    except (NoReverseMatch, KeyError):
                        self.fail(f"url_name={lien.get('url_name')!r} ne se résout pas")


class CardEntreeConformiteTest(TestCase):
    """Le `file_accept` des cards d'entrée ⟷ `input_extensions` du catalogue — les deux sens.

    Défaut fondateur (mesuré 2026-08-30, ROUTE §S2bis.6 (a)) : le littéral du converter
    s'arrêtait à `.tex,.latex` — 14 extensions de retard sur sa déclaration, dont les 10
    archives que `format_router` convertit réellement. Le sélecteur de fichier GRISAIT des
    fichiers que l'app sait traiter, et rien ne pouvait le voir : aucun test, aucun critère
    de grille ne confrontait ces littéraux au catalogue. Le converter est depuis DÉRIVÉ
    (`current_app_spec.input_extensions` — context processor) ; ce contrôle tient les
    littéraux restants, dans les deux sens :
      - la card OFFRE ce que l'app ne déclare pas → promesse fausse (le serveur refusera) ;
      - la card GRISE ce que l'app déclare → capacité invisible (le défaut du converter).

    ⚠ Un slot peut légitimement RESTREINDRE : la card de l'avatarizer prend la VOIX
    (politique déclarée `VOICE_SAMPLE_EXTENSIONS`), l'avatar s'importe par la galerie.
    Ces écarts sont ASSUMÉS dans `_ecarts_assumes()` — un compte à faire DÉCROÎTRE, jamais
    à relever machinalement ; la vraie case déclarative du slot est le chantier
    ROUTE §S2bis.6 (b) (déclaration d'entrées PAR SLOT), pas un littéral de plus.
    """

    # `file_accept='littéral'` OU `file_accept=expression` (dérivé — groupe 1 absent).
    _RE_ACCEPT = re.compile(r"file_accept=(?:'([^']*)'|(\S+))")

    @staticmethod
    def _familles():
        """Jeton MIME générique → extensions de la catégorie (la sémantique voulue de `accept`)."""
        from wama.common.app_registry import (AUDIO_EXTENSIONS, IMAGE_EXTENSIONS,
                                              VIDEO_EXTENSIONS)
        return {'image/*': set(IMAGE_EXTENSIONS), 'video/*': set(VIDEO_EXTENSIONS),
                'audio/*': set(AUDIO_EXTENSIONS)}

    @staticmethod
    def _ecarts_assumes():
        """{app: extensions déclarées mais volontairement absentes de la card} — à faire décroître.

        L'égalité est STRICTE dans les deux sens : une app qui s'aligne doit retirer son
        entrée ici, sinon le contrôle échoue — c'est ce qui empêche la liste de monter seule
        (leçon `CIBLES_ASSUMEES`, 2026-08-27).
        """
        from wama.common.app_registry import (AUDIO_EXTENSIONS, IMAGE_EXTENSIONS,
                                              VOICE_SAMPLE_EXTENSIONS)
        return {
            # Slot voix : la restriction SUIT la politique déclarée (pas un littéral orphelin) ;
            # l'avatar (image) n'a pas d'input fichier sur la card (galerie d'avatars).
            'avatarizer': ((set(AUDIO_EXTENSIONS)
                            - {'.' + e for e in VOICE_SAMPLE_EXTENSIONS})
                           | set(IMAGE_EXTENSIONS)),
            # La card annonce « fichier de prompts .txt/.csv » alors que TEXT_EXTENSIONS est
            # déclaré en entier et que les parsers batch lisent aussi md/pdf/docx — écart réel,
            # à trancher avec la déclaration PAR SLOT (§S2bis.6 (b)), pas par un patch de plus.
            'imager': {'.md', '.pdf', '.docx'},
        }

    @classmethod
    def _cards(cls):
        """{app: [(gabarit relatif, littéral ou None), …]} — None = `file_accept` DÉRIVÉ."""
        from wama.common.app_registry import APP_CATALOG
        base = _base()
        out = {}
        for app, spec in sorted(APP_CATALOG.items()):
            if spec.get('generated_from'):
                continue  # jumelle de bac à sable : gabarits générés, comparés à leur source
            releves = []
            for racine in ('wama', 'wama_lab'):
                dossier = base / racine / app / 'templates'
                if not dossier.is_dir():
                    continue
                for gabarit in sorted(dossier.rglob('*.html')):
                    for ligne in gabarit.read_text(encoding='utf-8').splitlines():
                        if '_new_item_card.html' not in ligne:
                            continue
                        m = cls._RE_ACCEPT.search(ligne)
                        if m:
                            releves.append((str(gabarit.relative_to(base)), m.group(1)))
            if releves:
                out[app] = releves
        return out

    def test_le_releve_trouve_les_cards(self):
        # Anti « vert sur du vide » : si le parseur ne trouve plus les includes (paramètre
        # renommé, include éclaté multi-lignes), les deux contrôles suivants mentiraient.
        cards = self._cards()
        self.assertGreaterEqual(len(cards), 8, f"relevé quasi vide ({sorted(cards)})")
        self.assertGreaterEqual(sum(len(v) for v in cards.values()), 10)

    def test_la_card_n_offre_rien_que_l_app_ne_declare(self):
        from wama.common.app_registry import APP_CATALOG
        familles = self._familles()
        for app, releves in self._cards().items():
            declarees = {e.lower() for e in APP_CATALOG[app].get('input_extensions', ())}
            for gabarit, litteral in releves:
                if litteral is None:
                    continue  # dérivé du catalogue : fidèle par construction
                for jeton in filter(None, (t.strip() for t in litteral.split(','))):
                    with self.subTest(app=app, jeton=jeton):
                        if jeton == '*/*':
                            continue
                        if jeton in familles:
                            self.assertTrue(
                                declarees & familles[jeton],
                                f"{gabarit} offre {jeton} mais aucune extension de cette "
                                f"catégorie n'est déclarée dans input_extensions")
                        else:
                            self.assertIn(
                                jeton.lower(), declarees,
                                f"{gabarit} offre une extension absente d'input_extensions")

    def test_aucune_card_d_entree_ne_demarre_DEPLIEE(self):
        """Une card d'entrée repliable démarre REPLIÉE — l'imager était le seul écart.

        Mesuré au navigateur le 2026-09-08 sur les 10 apps (constat Fabien : « la card
        d'entrée de l'Imager est dépliée par défaut alors que toutes les autres se comportent
        correctement ») : 9 repliées, imager déplié sur ses DEUX cards. Cause = `deployed=True`
        déclaré dans son gabarit au portage `b02ca266`, sans une ligne de justification.

        Le mécanisme n'a AUCUNE mémoire d'état (`wama-new-item-card.js` ne persiste rien) :
        l'état initial vient du seul gabarit, donc un test statique suffit et ne peut pas
        mentir. Le prompt reste visible replié (rendu HORS du bloc repliable) : replier ne
        cache jamais l'action principale.

        ⚠ Si une app doit un jour démarrer dépliée, ce test est le lieu où l'écart se
        DÉCLARE — pas un paramètre qu'on repose en silence dans un gabarit.
        """
        base = _base()
        deployees = []
        for racine in ('wama', 'wama_lab'):
            for gabarit in sorted((base / racine).glob('*/templates/*/*.html')):
                if '_01/' in gabarit.as_posix():
                    continue                    # jumelle : gabarits générés, jugés sur leur source
                for n, ligne in enumerate(gabarit.read_text(encoding='utf-8').splitlines(), 1):
                    if '_new_item_card' in ligne and re.search(r'\bdeployed=True\b', ligne):
                        deployees.append(f'{gabarit.relative_to(base).as_posix()}:{n}')
        self.assertEqual(deployees, [],
                         f"card(s) d'entrée démarrant dépliées : {deployees} — le parc "
                         f"démarre replié ; retirer `deployed=True` ou déclarer l'écart ici")

    def test_deux_cards_sur_une_page_portent_deux_ids_DISTINCTS(self):
        """Deux cards d'entrée dans un même gabarit doivent déclarer des `card_id` différents.

        Défaut MESURÉ le 2026-09-08 : l'enhancer rendait ses deux cards (média et audio) sans
        `card_id`, donc toutes deux avec le défaut `newItemCard` — et `newItemCardBody` en
        double. `wama-new-item-card.js` résout par `getElementById(card.id + 'Body')`, qui
        rend TOUJOURS le premier : cliquer l'en-tête de la card AUDIO dépliait la card MÉDIA,
        pendant que l'audio recevait le chevron « dépliée » sans s'ouvrir. Zéro erreur JS —
        le défaut était entièrement silencieux, et aucun contrôle ne le voyait.

        L'imager portait déjà la bonne forme (`imgNewCard` / `vidNewCard`) : ce test fige la
        règle plutôt que de la laisser dépendre de l'attention de qui écrit le gabarit.
        """
        base = _base()
        fautifs = []
        for racine in ('wama', 'wama_lab'):
            for gabarit in sorted((base / racine).glob('*/templates/*/*.html')):
                if '_01/' in gabarit.as_posix():
                    continue
                ids = []
                for ligne in gabarit.read_text(encoding='utf-8').splitlines():
                    if '_new_item_card' not in ligne or '{% include' not in ligne:
                        continue
                    m = re.search(r"card_id='([^']*)'", ligne)
                    ids.append(m.group(1) if m else 'newItemCard')   # défaut du partial
                if len(ids) > 1 and len(set(ids)) != len(ids):
                    fautifs.append(f'{gabarit.relative_to(base).as_posix()} → {ids}')
        self.assertEqual(fautifs, [],
                         f"cards d'entrée à id DUPLIQUÉ sur la même page : {fautifs} — "
                         f"déclarer un `card_id` par card (getElementById rend le premier)")

    def test_aucun_wrapper_de_file_en_overflow_x_hidden(self):
        """Garde anti-récidive (2026-08-30, constat Fabien sur converter_01, JUMEAU sur 7 apps).

        `overflow-x:hidden` force `overflow-y` en `auto` (spec CSS) : le wrapper devient un
        conteneur de défilement dont la hauteur suit le contenu, et les menus déroulants de la
        barre commune (densités Tt) se rognent au bas d'une file COURTE — symptôme
        intermittent, donc quasi indétectable à l'œil. `overflow-x:clip` rogne pareil SANS
        conteneur de défilement. Le motif reviendra par copier-coller : ce test le refuse.
        """
        base = _base()
        coupables = []
        for racine in ('wama', 'wama_lab'):
            for gabarit in sorted((base / racine).glob('*/templates/*/index.html')):
                texte = gabarit.read_text(encoding='utf-8')
                if 'overflow-x:hidden' in texte or 'overflow-x: hidden' in texte:
                    coupables.append(str(gabarit.relative_to(base)))
        self.assertEqual(coupables, [],
                         f'wrappers en overflow-x:hidden (menus rognés sur file courte) : '
                         f'{coupables} — utiliser overflow-x:clip')

    def test_la_card_ne_grise_rien_que_l_app_declare(self):
        from wama.common.app_registry import APP_CATALOG
        familles = self._familles()
        assumes = self._ecarts_assumes()
        for app, releves in self._cards().items():
            declarees = {e.lower() for e in APP_CATALOG[app].get('input_extensions', ())}
            offertes = set()
            for _gabarit, litteral in releves:
                if litteral is None:
                    offertes |= declarees  # dérivé du catalogue : couvre tout par construction
                    continue
                for jeton in filter(None, (t.strip() for t in litteral.split(','))):
                    if jeton == '*/*':
                        offertes |= declarees
                    else:
                        offertes |= familles.get(jeton, {jeton.lower()})
            with self.subTest(app=app):
                self.assertEqual(
                    declarees - offertes, assumes.get(app, set()),
                    "extensions déclarées mais grisées par la card (le défaut du converter) — "
                    "ou écart assumé PÉRIMÉ : si l'app s'est alignée, retirer son entrée "
                    "de _ecarts_assumes()")


class FunctionCatalogConformiteTest(TestCase):
    """Le 4ᵉ registre déclaratif — `FUNCTION_CATALOG` — n'avait **aucun test** (mesuré le
    2026-09-04, 55 entrées). Même angle mort que les trois autres avant ce fichier.

    Ce qui l'a révélé : une fonction livrée ce jour-là déclarait un port d'entrée typé,
    donc s'annonçait chaînable, alors que son `fn` prenait des tuples et rendait un `dict`.
    `can_connect` disait oui ; `view.apply()`, qui appelle `spec.fn(entrée_typée, **params)`
    et range un `TypedFrame`, aurait cassé à l'exécution. **Rien ne le voyait** — ni
    `manage.py check`, ni la suite, ni le catalogue lui-même.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.catalog.function_catalog import load_all, FUNCTION_CATALOG, Binding
        load_all()
        cls.catalogue = FUNCTION_CATALOG
        cls.Binding = Binding

    #: Fonctions pures dont le `fn` n'annonce pas le contrat `TypedFrame → TypedFrame`.
    #: Dette ANTÉRIEURE au contrôle, nommée pour que le budget ne puisse que DESCENDRE :
    #: une 4ᵉ entrée fait tomber le test. Ne jamais ajouter une clé ici pour faire passer
    #: du code neuf — c'est exactement le geste que ce contrôle existe pour empêcher.
    CONTRAT_ASSUME = {'depth_contact_distance', 'depth_ground_plane', 'trajectory_offset'}

    def test_le_registre_est_peuple(self):
        """Le piège du vert sur du vide (cf. en-tête) : sans ça, tout ce qui suit ment."""
        self.assertGreaterEqual(len(self.catalogue), 40)

    def test_TOUT_port_porte_une_description(self):
        """Un port sans description n'est pas apparaissable — ni par un humain qui câble le
        canvas, ni par un LLM qui doit rapprocher une colonne de données d'une entrée.

        ⚠ Mesuré le 2026-09-09 : **66 ports sur 143** étaient muets (46 %), sans qu'aucune
        autre déclaration ne manque — c'était le SEUL déficit systématique du catalogue.
        Soldé le même jour. Ce test empêche la dette de revenir port par port, ce qui est
        exactement la façon dont elle s'était installée.

        Le seuil est ZÉRO et non un budget dégressif : contrairement au contrat `fn`
        ci-dessous, écrire une description ne demande aucun portage — il n'y a donc pas de
        dette légitime à tolérer.
        """
        muets = [f'{cle}.{p.key}[{cote}]'
                 for cle, spec in self.catalogue.items()
                 for cote, ports in (('in', spec.inputs), ('out', spec.outputs))
                 for p in ports if not (p.description or '').strip()]
        self.assertEqual(muets, [], f"{len(muets)} port(s) sans description : {muets[:5]}")

    def test_la_cle_du_dict_et_la_cle_declaree_coincident(self):
        for cle, spec in self.catalogue.items():
            with self.subTest(fonction=cle):
                self.assertEqual(cle, spec.key)

    def test_tout_port_porte_un_type_DE_LA_TAXONOMIE(self):
        """Étendre la taxonomie AVANT d'inventer un type (checklist §7bis)."""
        from wama.common.catalog.data_types import DataType
        # `DataType` est une classe de CONSTANTES, pas un `Enum` : elle ne s'itère pas.
        connus = {v for k, v in vars(DataType).items()
                  if not k.startswith('_') and isinstance(v, str)}
        self.assertIn('table', connus, "relevé des types vide → le contrôle serait muet")
        for cle, spec in self.catalogue.items():
            for sens, ports in (('entrée', spec.inputs), ('sortie', spec.outputs)):
                for p in ports:
                    valeur = getattr(p.data_type, 'value', p.data_type)
                    with self.subTest(fonction=cle, sens=sens, port=p.key):
                        self.assertIn(valeur, connus)

    def test_une_fonction_APP_declare_son_implementation_et_son_app(self):
        """`binding='app'` n'a pas de `fn` : `impl` est le SEUL moyen de la retrouver."""
        for cle, spec in self.catalogue.items():
            if spec.binding != self.Binding.APP:
                continue
            with self.subTest(fonction=cle):
                self.assertTrue(spec.impl, "app-bound sans `impl` : introuvable")
                self.assertTrue(spec.app, "app-bound sans `app` : propriétaire inconnu")

    def test_une_fonction_PURE_a_bien_un_fn_appelable(self):
        for cle, spec in self.catalogue.items():
            if spec.binding == self.Binding.APP:
                continue
            with self.subTest(fonction=cle):
                self.assertTrue(callable(spec.fn),
                                "pure sans `fn` : ni chaînable, ni retrouvable")

    def test_une_fonction_PURE_CHAINABLE_annonce_le_contrat_TypedFrame(self):
        """⚠ Contrôle par ANNOTATION — c'est un PROXY, pas une preuve d'exécution.

        Il n'atteste pas que `fn` rende vraiment un `TypedFrame` ; il atteste que l'auteur
        a écrit le contrat, ce qui suffit à faire échouer le cas réel qui a motivé ce test
        (un noyau branché en `fn` à la place de son wrapper). La vérification forte serait
        d'appeler chaque `fn` sur une donnée valide — hors de portée d'un contrôle générique,
        chaque fonction ayant ses champs requis. **26/30 conformes à l'écriture.**
        """
        manquants = set()
        for cle, spec in self.catalogue.items():
            if spec.binding == self.Binding.APP or not spec.inputs or not callable(spec.fn):
                continue
            sig = inspect.signature(spec.fn)
            params = list(sig.parameters.values())
            entree_ok = bool(params) and 'TypedFrame' in str(params[0].annotation)
            retour_ok = 'TypedFrame' in str(sig.return_annotation)
            if not (entree_ok and retour_ok):
                manquants.add(cle)

        self.assertEqual(
            manquants, self.CONTRAT_ASSUME,
            "une fonction PURE déclare un port d'entrée sans annoncer `TypedFrame → "
            "TypedFrame` — `view.apply()` lui passera un TypedFrame et rangera son retour. "
            "Corriger la fonction (noyau + wrapper, patron `placement_metrics`), pas la liste.")

    def test_toute_fonction_du_catalogue_s_extrait_en_manifeste_VALIDE(self):
        """La chaîne registre → manifeste (demande Fabien 2026-09-05 : « voir si toute la
        chaîne tient »). Le kind `function` existait sans jamais être exporté ; ce test atteste
        que CHAQUE entrée du catalogue s'extrait ET passe la validation du kind — sans quoi
        `manifest_export --kind function` refuserait de l'écrire et le corpus la tairait."""
        from wama.common.manifests.ingest import extract, validate
        for cle, spec in self.catalogue.items():
            with self.subTest(fonction=cle):
                m = extract('function', cle)
                self.assertIsNotNone(m, "extraction impossible")
                self.assertEqual(m.get('manifest_kind'), 'function')
                self.assertEqual(m.get('key'), cle)
                self.assertEqual((m.get('body') or {}).get('binding'), spec.binding)
                self.assertEqual(list(validate(m) or []), [],
                                 "manifeste invalide → refusé à l'export")

    # ── Marche C (rôle des ports) + facette estimateur ⑤b — 2026-09-09 ──────────────────

    def test_tout_port_honore_sa_facette_rôle_ou_estimateur(self):
        """La MÊME règle que le kind manifeste `function` applique à l'ingest : un rôle
        (`group`) hors vocabulaire, une estimation sans provenance ou sans incertitude, une
        facette de sortie posée sur une entrée — tout cela est refusé ICI, au catalogue, avant
        que le corpus ne l'écrive."""
        from wama.common.catalog.function_catalog import validate_port_facet
        for cle, spec in self.catalogue.items():
            for side, ports in (('input', spec.inputs), ('output', spec.outputs)):
                for p in ports:
                    with self.subTest(fonction=cle, sens=side, port=p.key):
                        self.assertEqual(validate_port_facet(p.port_dict(side), side), [])

    def test_le_role_d_un_port_d_entree_est_emprunte_au_vocabulaire_des_apps(self):
        """`group` ∈ INPUT_TYPES[*]['port'] (app_modes) — jamais un 3ᵉ enum (marche C)."""
        from wama.common.utils.app_modes import INPUT_TYPES
        roles_apps = {v.get('port') for v in INPUT_TYPES.values() if v.get('port')}
        self.assertTrue(roles_apps, "INPUT_TYPES sans rôle → contrôle muet")
        for cle, spec in self.catalogue.items():
            for p in spec.inputs:
                with self.subTest(fonction=cle, port=p.key):
                    self.assertIn(p.port_dict('input')['group'], roles_apps)

    def test_function_node_ports_a_la_MEME_forme_que_studio_node_ports(self):
        """Marche C : la card v4 et le Studio lisent `{inputs:[{id,label,group,types,multi}],
        output:{id,label,types}}` — une fonction doit rendre EXACTEMENT ces clés (un superset
        est toléré, un manque casse le consommateur en silence)."""
        from wama.common.app_registry import studio_node_ports, APP_CATALOG
        from wama.common.catalog.function_catalog import function_node_ports
        modele = next(studio_node_ports(a) for a in APP_CATALOG if studio_node_ports(a))
        cles_entree = set(modele['inputs'][0]) if modele['inputs'] else {'id', 'label', 'group', 'types', 'multi'}
        cles_sortie = set(modele['output'])
        self.assertIsNone(function_node_ports('fonction.inexistante'))
        for cle in self.catalogue:
            ports = function_node_ports(cle)
            with self.subTest(fonction=cle):
                self.assertIsNotNone(ports)
                self.assertEqual(set(ports) >= {'inputs', 'output', 'outputs'}, True)
                for p in ports['inputs']:
                    self.assertTrue(cles_entree <= set(p), f"clés manquantes : {cles_entree - set(p)}")
                    self.assertEqual(len(p['types']), 1, "un port de fonction a UN type déclaré")
                if ports['output'] is not None:
                    self.assertTrue(cles_sortie <= set(ports['output']))

    def test_le_type_de_sortie_d_un_noeud_fonction_inclut_ses_super_types(self):
        """Le canvas apparie par INTERSECTION : `geo_track` doit pouvoir entrer dans `table`."""
        from wama.common.catalog.function_catalog import function_node_ports
        ports = function_node_ports('ego_track_filter')
        self.assertEqual(ports['output']['types'], ['geo_track', 'table', 'timeseries'])

    def test_la_facette_estimateur_est_posee_sur_les_leviers_releves(self):
        """§INVENTAIRE C → ⑤b : les producteurs de cap, distance, plan de sol et position
        DÉCLARENT ce qu'ils estiment et de quelle donnée native. Un producteur qui perd sa
        facette redevient invisible pour la fusion — c'est un bug de manifeste."""
        from wama.common.catalog.function_catalog import port_estimate_meta
        attendus = {
            'ego_track_filter': ('heading', ['gps']),
            'ego_rotation': ('yaw', ['image']),
            'cam_analyzer.shuttle_filter': ('heading', ['gps']),
            'cam_analyzer.distance': ('distance', ['bbox']),
            'cam_analyzer.depth_analysis': ('distance', ['depth_map']),
            'cam_analyzer.ground_calib': ('ground_plane', ['bbox', 'gps']),
            'cam_analyzer.depth_ground_plane': ('ground_plane', ['depth_map', 'segmentation']),
            'cam_analyzer.global_tracking': ('position', ['bbox', 'gps']),
            'cam_analyzer.ortho_recalage': ('offset', ['orthophoto', 'segmentation']),
        }
        for cle, (grandeur, natives) in attendus.items():
            with self.subTest(fonction=cle):
                spec = self.catalogue[cle]
                facettes = [port_estimate_meta(p) for p in spec.outputs if p.estimates]
                self.assertTrue(facettes, "aucune sortie ne porte de facette")
                self.assertIn((grandeur, natives), [(f['quantity'], f['derived_from']) for f in facettes])
        # et la facette voyage : elle est dans le manifeste extrait, pas seulement en mémoire
        from wama.common.manifests.ingest import extract
        m = extract('function', 'ego_track_filter')
        port = m['body']['outputs'][0]
        self.assertEqual(port['estimates'], 'heading')
        self.assertEqual(port['uncertainty'], {'model': 'held', 'field': 'heading_f_held', 'sigma': 3.0})
        self.assertEqual(port['derived_from'], ['gps'])

    def test_le_kind_function_refuse_une_facette_bancale_a_l_ingest(self):
        """Ce que le catalogue refuse, le manifeste le refuse aussi — sinon un manifeste ingéré
        pourrait déclarer une estimation sans provenance, et la fusion la prendrait."""
        from wama.common.manifests.builtin.function import validate_function_body
        body = {'binding': 'pure', 'inputs': [{'key': 'x', 'data_type': 'table', 'group': 'autre'}],
                'outputs': [{'key': 'y', 'data_type': 'scalar', 'estimates': 'heading'}]}
        errs = validate_function_body(body)
        self.assertTrue(any("group 'autre'" in e for e in errs), errs)
        self.assertTrue(any('derived_from' in e for e in errs), errs)
        self.assertTrue(any('uncertainty' in e for e in errs), errs)
        sain = {'binding': 'pure', 'outputs': [{'key': 'y', 'data_type': 'scalar', 'estimates': 'heading',
                                               'uncertainty': 3.0, 'derived_from': ['gps']}]}
        self.assertEqual(validate_function_body(sain), [])

    def test_les_params_declares_sont_acceptes_en_MOTS_CLES_par_le_fn(self):
        """`view.apply()` fait `spec.fn(entrée, **params)` : un ParamSpec que la signature
        n'accepte pas est un `TypeError` à l'exécution, invisible au catalogue."""
        for cle, spec in self.catalogue.items():
            if spec.binding == self.Binding.APP or not callable(spec.fn):
                continue
            sig = inspect.signature(spec.fn)
            if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                continue  # **kwargs : accepte tout par construction
            acceptes = {n for n, p in sig.parameters.items()
                        if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                      inspect.Parameter.KEYWORD_ONLY)}
            for ps in spec.params:
                with self.subTest(fonction=cle, param=ps.key):
                    self.assertIn(ps.key, acceptes,
                                  f"`{ps.key}` est déclaré au manifeste mais absent de la "
                                  f"signature de {spec.fn.__name__}")


class VocabulaireDesEntreesTest(TestCase):
    """`INPUT_TYPES` ne contient QUE des entrées — ni modalité, ni geste, ni réglage.

    Le vocabulaire confondait QUATRE axes orthogonaux, et c'est ce mélange qui rendait
    insoluble toute discussion « travail vs référence » : on demandait à une catégorie de
    trancher ce qui relève de trois autres plans.
      • un JETON d'entrée — ce que l'élément consomme (`prompt`, `work_image`…) ;
      • une MODALITÉ — comment un fichier atteint un slot (`url` y figurait, alors que la card
        v4 rend un champ URL PAR VOLET DE PORT) ;
      • une VOIE — par où le fichier entre dans WAMA (`MEDIA_STORAGE_TIERING §8.2`) ;
      • un GESTE de LOT — `prompt_file` y figurait, libellé « Fichier de prompts (batch) »,
        alors que « le LOT n'a pas de port, c'est le GESTE qui le crée » (Fabien, 05/09).

    Ces intrus étaient tous INERTES, donc invisibles : `studio_node_ports` ne retient des
    `inputs` d'une app que les jetons `port == 'reference'`. Un contrôle vaut mieux qu'une
    intention — sans lui, le prochain jeton hors-axe rentrera aussi silencieusement.
    """

    PORTS_VALIDES = {'travail', 'prompt', 'reference'}

    def test_chaque_jeton_declare_un_port_VALIDE(self):
        from wama.common.utils.app_modes import INPUT_TYPES
        fautifs = {k: v.get('port') for k, v in INPUT_TYPES.items()
                   if v.get('port') not in self.PORTS_VALIDES}
        self.assertEqual({}, fautifs,
                         "port hors vocabulaire — un `None` trahit un RÉGLAGE déguisé en "
                         f"entrée, un nom inconnu une 4ᵉ famille non décidée : {fautifs}")

    def test_aucune_MODALITE_ni_GESTE_ne_revient_dans_le_vocabulaire(self):
        from wama.common.utils.app_modes import INPUT_TYPES
        intrus = {'url', 'prompt_file', 'batch_file', 'negative_prompt'} & set(INPUT_TYPES)
        self.assertEqual(set(), intrus,
                         "ces clés ne sont pas des ENTRÉES : `url` est une modalité (déjà "
                         "servie par `input_slots.mods`), `prompt_file`/`batch_file` sont le "
                         "geste de LOT (brique commune), `negative_prompt` un réglage. "
                         f"Revenues : {sorted(intrus)}")

    def test_le_PROMPT_n_est_pas_un_port_de_travail(self):
        """Le seul endroit du dépôt qui disait le contraire, jusqu'au 2026-09-10.

        `studio_node_ports` lui donne un groupe `prompt` distinct, la card v4 l'exclut des
        onglets pour le rendre en cellule primaire, et la règle de preview d'entrée écrit
        `group ∈ {travail, prompt}` — donc deux choses. L'accesseur d'union lira ce champ pour
        assigner le groupe d'un jeton : s'il redevient `travail`, le prompt retournerait sur le
        port de travail et la card v4 en ferait un onglet fichier.
        """
        from wama.common.utils.app_modes import INPUT_TYPES
        self.assertEqual('prompt', INPUT_TYPES['prompt']['port'])

    def test_tout_jeton_declare_par_un_MODELE_existe_dans_le_vocabulaire(self):
        """La garde qui protège l'auto-adaptation aux modèles (INPUT_MODEL_MATCHING §6.3).

        Les slots d'une app dériveront de l'union des `inputs_required`/`inputs_optional` de
        ses modèles. Un modèle qui déclare un jeton absent d'`INPUT_TYPES` produirait un slot
        SANS libellé, sans `accept` et sans port — donc un onglet muet, ou pas d'onglet du
        tout. Mesuré au 2026-09-10 : les deux vocabulaires sont alignés (0 écart).
        """
        from wama.model_manager.models import AIModel
        from wama.common.utils.app_modes import INPUT_TYPES

        vus = set()
        for caps in AIModel.objects.values_list('capabilities', flat=True):
            if isinstance(caps, dict):
                vus.update(caps.get('inputs_required') or [])
                vus.update(caps.get('inputs_optional') or [])
        orphelins = sorted(vus - set(INPUT_TYPES))
        self.assertEqual([], orphelins,
                         "des modèles déclarent des entrées que le vocabulaire ignore : "
                         f"{orphelins} — l'union produirait des slots muets")

    def test_chaque_jeton_porte_un_texte_qui_dit_A_QUOI_il_sert(self):
        """Demande Fabien (10/09) : deux onglets « Image » ne se distinguent pas par leur type.

        Ce qu'un jeton NOMMÉ doit dire, et qu'une catégorie travail/référence ne dit pas :
        lequel sera ÉDITÉ, lequel GUIDERA. La case existait déjà dans le contrat de port
        (`portEl()` la prend en 6ᵉ argument).
        """
        from wama.common.utils.app_modes import INPUT_TYPES
        muets = [k for k, v in INPUT_TYPES.items() if not (v.get('description') or '').strip()]
        self.assertEqual([], muets, f'entrées sans texte explicatif : {muets}')


class UnionDesEntreesDeModelesTest(TestCase):
    """`app_input_ports` — les slots d'une app dérivent des CAPACITÉS DE SES MODÈLES.

    Exigence de Fabien (2026-09-10) : *« la seule solution stable dans le temps quel que soit
    l'ajout de nouveaux modèles est l'union des capacités d'entrée de tous les modèles acceptés
    par une application »*. Un modèle qui arrive avec une modalité de plus apporte son slot,
    sans qu'aucun gabarit ni aucune déclaration d'app ne soit retouché.

    ⚠ FIXTURES LOCALES, jamais le catalogue ambiant. Première version écrite contre les
    `AIModel` réels : elle échouait en base de TEST (catalogue vide) — et surtout, elle aurait
    changé de verdict au premier modèle ajouté au parc. Un test qui lit l'état du monde ne
    mesure pas un invariant, il le suit.
    """

    #: source dédiée — n'entre en collision avec aucune app réelle du catalogue.
    APP = 'app_temoin_union'

    def _modele(self, cle, requis=(), optionnels=(), task=None):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(
            model_key=f'{self.APP}:{cle}', name=cle, source=self.APP,
            capabilities={'inputs_required': list(requis),
                          'inputs_optional': list(optionnels),
                          **({'task': task} if task else {})})

    def test_une_app_sans_modele_declarant_rend_VIDE_et_non_un_port_invente(self):
        """Le repli qui garantit qu'aucune app ne régresse.

        Une app dont les modèles ne déclarent AUCUNE entrée (converter : aucun moteur IA, N/A
        mesuré `INPUT_MODEL_MATCHING §5`) doit rendre vide, pour que l'appelant garde sa
        dérivation actuelle. Fabriquer un port serait pire que ne rien rendre.
        """
        from wama.common.app_registry import app_input_ports
        self._modele('sans_entrees')                      # modèle présent, mais muet
        self.assertEqual([], app_input_ports(self.APP))

    def test_l_obligation_est_l_INTERSECTION_l_offre_est_l_UNION(self):
        """La sémantique qui rend le système « non bloquant » (référence Suno, §6.2).

        Un jeton exigé par TOUS les modèles est requis ; exigé par UN SEUL, il est seulement
        OFFERT. C'est ce qui permet « une entrée suffit, plusieurs sont acceptées » sans qu'un
        modèle minoritaire impose sa contrainte à toute l'app. L'obligation réelle au moment du
        lancement reste l'affaire de `matches_inputs` selon le modèle CHOISI.
        """
        from wama.common.app_registry import app_input_ports
        self._modele('txt', requis=['prompt'])
        self._modele('edit', requis=['prompt', 'work_image'])
        self._modele('i2i', requis=['prompt'], optionnels=['work_image'])

        ports = {p['id']: p['required'] for p in app_input_ports(self.APP)}
        self.assertEqual({'prompt': True, 'work_image': False}, ports,
                         'prompt exigé par les 3 → requis ; work_image par 2 sur 3 → offert')

    def test_un_jeton_exige_par_TOUS_devient_requis(self):
        from wama.common.app_registry import app_input_ports
        self._modele('a', requis=['work_audio'])
        self._modele('b', requis=['work_audio'], optionnels=['reference_voice'])
        ports = {p['id']: p['required'] for p in app_input_ports(self.APP)}
        self.assertEqual({'work_audio': True, 'reference_voice': False}, ports)

    def test_la_forme_rendue_est_celle_d_un_PORT_augmentee_de_l_obligation(self):
        from wama.common.app_registry import app_input_ports
        from wama.common.utils.app_modes import INPUT_TYPES

        self._modele('m', requis=['prompt'], optionnels=['reference_melody'])
        ports = app_input_ports(self.APP)
        self.assertEqual(2, len(ports))
        for p in ports:
            self.assertEqual({'id', 'label', 'group', 'types', 'multi', 'required', 'description'},
                             set(p), f'forme de port inattendue : {p}')
            self.assertIn(p['id'], INPUT_TYPES)
            self.assertIn(p['group'], {'travail', 'prompt', 'reference'})
            self.assertTrue(p['description'], f"port sans texte explicatif : {p['id']}")
        # Le prompt vient EN TÊTE : c'est la consigne, et la card v4 la rend au-dessus des onglets.
        self.assertEqual('prompt', ports[0]['id'])

    def test_un_jeton_hors_vocabulaire_ne_fabrique_PAS_de_port_muet(self):
        """Un modèle mal déclaré ne doit pas produire un onglet sans libellé ni `accept`.
        Le contrôle `VocabulaireDesEntreesTest` refuse ce cas en amont ; ici on vérifie que
        l'accesseur ne MENT pas si ça arrive quand même."""
        from wama.common.app_registry import app_input_ports
        self._modele('exotique', requis=['prompt'], optionnels=['entree_inconnue_xyz'])
        ids = [p['id'] for p in app_input_ports(self.APP)]
        self.assertEqual(['prompt'], ids)

    def test_le_domaine_se_DERIVE_de_la_tache_jamais_d_une_table_par_app(self):
        """`model_type` ne sépare rien — il vaut `diffusion` pour les 12 modèles de l'imager,
        image ET vidéo confondues. Le discriminant est `capabilities.task`, dont la CIBLE est le
        domaine de sortie."""
        from wama.common.app_registry import _domaine_dune_tache

        self.assertEqual('image', _domaine_dune_tache('text-to-image'))
        self.assertEqual('image', _domaine_dune_tache('image-to-image'))
        self.assertEqual('video', _domaine_dune_tache('image-to-video'))
        self.assertIsNone(_domaine_dune_tache(None))
        self.assertIsNone(_domaine_dune_tache('transcription'))

    def test_le_filtre_par_domaine_retient_les_modeles_de_CE_domaine(self):
        from wama.common.app_registry import app_input_ports
        self._modele('t2i', requis=['prompt'], task='text-to-image')
        self._modele('i2v', requis=['prompt', 'work_image'], task='image-to-video')

        image = {p['id'] for p in app_input_ports(self.APP, domain='image')}
        video = {p['id'] for p in app_input_ports(self.APP, domain='video')}
        self.assertEqual({'prompt'}, image, 'le modèle vidéo ne doit pas peupler le domaine image')
        self.assertEqual({'prompt', 'work_image'}, video)
        # Domaine COMPOSÉ (`image_video` de l'enhancer) : il retient ses composantes.
        self.assertEqual({'prompt', 'work_image'},
                         {p['id'] for p in app_input_ports(self.APP, domain='image_video')})

    def test_une_tache_NON_NOMMABLE_ne_disparait_pas_du_filtre(self):
        """Garde anti-silence : filtrer sur une inconnue ferait disparaître des slots sans
        rien dire — exactement le défaut que ce mécanisme existe pour supprimer."""
        from wama.common.app_registry import app_input_ports
        self._modele('sans_tache', requis=['work_file'])          # aucune `task` déclarée
        self.assertEqual({'work_file'},
                         {p['id'] for p in app_input_ports(self.APP, domain='image')})
