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
