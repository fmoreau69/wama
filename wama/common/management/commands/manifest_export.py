"""
Exporte les manifestes d'app en fichiers — le CORPUS d'exemples de référence.

But (cadré par Fabien, 2026-08-02) : disposer d'exemples réels et valides de manifestes, à
partir desquels **wama-dev-ai traduira des projets GitHub en manifestes WAMA**. Ce sont donc
des supports d'apprentissage : un manifeste invalide exporté enseignerait une erreur, la
commande REFUSE de l'écrire.

  python manage.py manifest_export                  # les 10 apps → manifests/apps/
                                                    #  + libraries déjà semées → manifests/libraries/
                                                    #  + modèles cités par les requires → manifests/models/
  python manage.py manifest_export transcriber      # une seule app
  python manage.py manifest_export --kind library faster-whisper   # SEMER une library au corpus
  python manage.py manifest_export --kind function                 # TOUT le FUNCTION_CATALOG → manifests/functions/
  python manage.py manifest_export --check          # n'écrit rien ; sort en erreur si périmé
  python manage.py manifest_export --check --kind function         # idem, fonctions seules
  python manage.py manifest_export --kind pipeline                 # pipelines DÉCLARÉS EN CODE → manifests/pipelines/

Fonctions (2026-09-05, demande Fabien « voir si toute la chaîne manifeste → registre →
utilisation tient ») : le kind `function` existait (extract/validate/write-back borné à
`binding=user`) mais n'était JAMAIS exporté — le corpus n'avait que apps/libraries/models.
Exportées par ÉNUMÉRATION du `FUNCTION_CATALOG` (fonctions SYSTÈME, `pure` + `app`) ; les
`UserFunction` (binding `user`, données en base, scopées) ne sont pas un corpus d'exemples et
ne s'exportent qu'à la clé explicite. Sans clé : `--kind function` n'exporte QUE les fonctions
— c'est le seul mode qui ne touche pas aux libraries, donc le seul sûr depuis venv_win (cf. ⚠
ENVIRONNEMENT ci-dessous) ; l'export complet (sans `--kind`) les inclut désormais aussi.

Libraries (SPEC §7.4-3) : le semis est EXPLICITE (`--kind library <clé>`) — aucun critère de
sélection inventé ; sans clé, la commande rafraîchit/contrôle ce qui a déjà été semé.

Modèles (micro-marche pré-B, actée 2026-08-12) : exportés par DÉRIVATION — les modèles cités
par les `requires` des apps (composition `app → model`), plus le refresh des déjà exportés.
L'export fichier sert la REVUE HUMAINE et le few-shot du rôle codegen ; la mécanique de
composition, elle, résout les requires par EXTRACTION LIVE (elle ne lit pas ces fichiers).
Les clés modèle portent un `:` (`transcriber:whisper`) interdit dans un nom de fichier
Windows → nom assaini `transcriber__whisper.json` (réversible au glob).

Le corpus est un artefact DÉRIVÉ mais VERSIONNÉ : le `git diff` du corpus est la revue de ce
qui change dans la surface déclarée d'une app. `--check` permet de refuser un commit qui
modifie un registre sans régénérer le corpus.

⚠ ENVIRONNEMENT (vécu 2026-08-26) : les manifestes LIBRARY s'extraient des métadonnées pip
du venv COURANT — les régénérer depuis venv_win a écrit transformers 5.12.1 (la dérive
connue de venv_win) et un torch amputé de ses paquets nvidia (wheel Windows). La référence
des libraries est venv_linux (WSL2) : ne les régénérer QUE depuis là. Les manifestes MODEL
(extraits du catalogue en base) et APP (registres) sont insensibles au venv.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand

DOSSIERS = {'app': 'manifests/apps', 'library': 'manifests/libraries',
            'model': 'manifests/models', 'function': 'manifests/functions',
            'pipeline': 'manifests/pipelines'}


def _pipeline_keys() -> list:
    """Clés des pipelines DÉCLARÉS EN CODE (`register_pipeline_source`, ex. `cam_analyzer`).
    Les pipelines du canvas (StudioPipeline, clé = pk) sont PRIVÉS : jamais au corpus."""
    from wama.common.manifests.builtin.pipeline import registered_pipeline_keys
    return registered_pipeline_keys()


def _function_keys() -> list:
    """Clés des fonctions SYSTÈME du catalogue code (pure + app), triées.

    `load_all()` parcourt les apps installées et importe leur module déclarant — c'est la
    même énumération que `/model-manager/functions/` : ce que la page montre, le corpus l'a.
    """
    from wama.common.catalog.function_catalog import load_all, FUNCTION_CATALOG
    try:
        load_all()
    except Exception:
        pass
    return sorted(FUNCTION_CATALOG)


def _model_keys() -> list:
    """Clés des modèles du catalogue à porter au corpus — ÉNUMÉRATION, comme les fonctions.

    Pourquoi (2026-09-19, chantier « source unique des capacités ») : les modèles n'entraient
    que par DÉRIVATION (cités par les `requires` d'une app) ∪ refresh des déjà semés. Un modèle
    qu'aucune app ne déclare n'avait donc jamais de manifeste : mesuré, **12 lignes cloud**
    (11 `anthropic:*` + `claude_code:default`) — exactement celles que la découverte cloud
    apporte sans app propriétaire.

    ⚠ Les lignes RETIRÉES sont exclues, et ce n'est pas un détail de propreté : `retire_unlisted`
    MARQUE (`is_available=False`) au lieu de supprimer, pour garder l'historique d'une ligne que
    la source ne liste plus. Deux résidus d'avant la normalisation des clés existent
    (`albert:openai/gpt-oss-120b`, `albert:qwen3-coder-30b-A3b-instruct`) et c'est l'export de
    l'un d'eux qui, le 2026-09-18, a ÉCRASÉ un manifeste valide : sous Windows son nom de
    fichier ne différait que par la casse. *Exporter une ligne morte ne crée pas un fichier de
    plus, il peut en détruire un vivant.*
    """
    from wama.model_manager.models import AIModel
    return sorted(AIModel.objects.filter(is_proposed=False, is_available=True)
                  .values_list('model_key', flat=True))


def _nom_fichier(cle: str, connues=()) -> str:
    """Nom de fichier assaini : les clés modèle portent `:` (interdit sous Windows) et les
    snapshots HF un `/` d'organisation (`huggingface:Org/Nom`, 2026-08-27) qui créerait un
    SOUS-DOSSIER au corpus — vécu : export en échec FileNotFoundError sur le premier modèle
    installé par la chaîne générique. `~` n'appartient pas à l'alphabet des ids HF ni des
    clés WAMA : la réversibilité du glob inverse est exacte.

    `connues` : les autres clés du même lot. Deux clés qui ne diffèrent que par la CASSE
    donnent le même fichier sur un système insensible à la casse (Windows, macOS) — vécu le
    2026-09-18 : `albert:qwen3-coder-30b-A3b-instruct` a écrasé le manifeste de
    `albert:qwen3-coder-30b-a3b-instruct`, restauré par `git checkout`. On refuse, comme pour
    `__`/`~` : *refuser vaut mieux que corrompre en silence.*
    """
    if '__' in cle or '~' in cle:   # collision avec l'assainissement → le glob inverse
        raise ValueError(           # rendrait une autre clé ; refuser vaut mieux que
            f"clé {cle!r} : '__' ou '~' entre en collision "  # corrompre en silence.
            "avec l'assainissement de ':' et '/'")
    jumelles = [k for k in connues if k != cle and k.lower() == cle.lower()]
    if jumelles:
        raise ValueError(
            f"clé {cle!r} : même nom de fichier que {jumelles!r} à la casse près — sur un "
            "système insensible à la casse, l'un écraserait l'autre")
    return cle.replace(':', '__').replace('/', '~')


def _cle_du_stem(stem: str) -> str:
    return stem.replace('__', ':').replace('~', '/')


#: Clés d'`extra_info` qui décrivent L'ÉTAT DE CETTE MACHINE, pas le modèle — retirées à
#: l'export (2026-09-19). Même motif que `_missing_facets` : « le corpus ne doit contenir que du
#: DÉCLARATIF », un LLM entraîné dessus apprendrait à inventer des chemins et des états.
#:
#: Mesuré sur les 141 manifestes avant filtrage : `path` sur **82** d'entre eux, avec le chemin
#: ABSOLU de cette machine (`/mnt/d/WAMA/…`) — dans un dépôt PUBLIC, et doublon de `local_path`
#: que le write-back PRÉSERVE déjà (il ne projette jamais `extra_info`, vérifié :
#: `write_back_model` ne touche que `_CHAMPS_PROJETES` + capabilities + gated). Retirer ne perd
#: donc rien : ni au registre, ni à la composition (qui résout les requires par extraction LIVE).
#:
#: ⚠ Liste NOIRE, jamais blanche : une app qui déclare demain une méta-info propre doit la voir
#: arriver au corpus sans rien modifier ici — c'est l'ouverture que WAMA vise. On ne retire que
#: ce dont on a établi la nature.
_EXTRA_INFO_ETAT_MACHINE = frozenset({
    # Chemins de CETTE machine
    'path', 'install_dir', 'models_dir',
    # Mesures de disque — `resources.disk_gb` porte déjà le fait
    'size_bytes', 'size_mb', 'disk_gb',
    # Présence / bon fonctionnement à l'instant T
    'installed', 'ready', 'models_dir_exists', 'models_cached', 'error', 'hf_authenticated',
    # Empreintes et marqueurs posés par la DÉCOUVERTE
    'ollama_id', 'hf_snapshot', 'vram_estimated', 'update_check', 'declared',
    # Relevé de poids PAR COMPOSANT du snapshot LOCAL (`model_sync.persist_weights`, 19/09) :
    # il porte `root` — le chemin ABSOLU de cette machine — plus `signature` et `at`, qui ne
    # décrivent que cet exemplaire installé. Mesuré le 2026-09-20 : sans cette ligne, un export
    # a mis `/mnt/d/WAMA/…` dans **15** manifestes d'un dépôt PUBLIC, et
    # `tests_catalogues.test_aucun_chemin_absolu_de_cette_machine` l'a attrapé.
    # ⚠ Ce qui est perdu au corpus est le RELEVÉ, pas le FAIT : l'anatomie vit dans
    # `body.composition.components` (déclaratif, exporté), et le poids se re-dérive d'elle par
    # `components_for_spec`. *Une clé collante neuve n'est pas automatiquement du déclaratif :
    # la liste noire ne la connaît pas, et c'est à son auteur de l'y inscrire.*
    'weights',
})


def _sans_etat_machine(extra_info: dict) -> dict:
    """`extra_info` débarrassé de l'état machine — cf. `_EXTRA_INFO_ETAT_MACHINE`."""
    return {k: v for k, v in (extra_info or {}).items()
            if k not in _EXTRA_INFO_ETAT_MACHINE}


class Command(BaseCommand):
    help = "Exporte les manifestes (apps + libraries semées) en JSON — corpus d'exemples."

    def add_arguments(self, parser):
        parser.add_argument('cle', nargs='?',
                            help="Clé à exporter (app_id, ou nom de library avec --kind library). "
                                 "Défaut : toutes les apps + les libraries déjà semées.")
        parser.add_argument('--kind', default='app', choices=sorted(DOSSIERS),
                            help="Kind de la clé explicite (défaut app).")
        parser.add_argument('--out', default=None,
                            help="Dossier de sortie (défaut : celui du kind).")
        parser.add_argument('--check', action='store_true',
                            help="N'écrit rien ; code de sortie 1 si le corpus est périmé.")
        parser.add_argument('--force', action='store_true',
                            help="Écrit même les manifestes invalides (déconseillé).")

    def handle(self, *args, **o):
        from django.conf import settings
        from wama.common.app_registry import APP_CATALOG
        from wama.common.manifests.ingest import extract, validate

        base = Path(settings.BASE_DIR)
        extraits = {}          # (kind, clé) → manifeste : la pré-passe requires ne ré-extrait pas

        def _extract(kind, cle):
            if (kind, cle) not in extraits:
                extraits[(kind, cle)] = extract(kind, cle)
            return extraits[(kind, cle)]

        if o['cle']:
            cibles = [(o['kind'], o['cle'])]
        elif o['kind'] == 'function':
            # Fonctions SEULES : le seul mode sans clé qui ne touche pas aux libraries
            # (venv-dépendantes) — utilisable depuis n'importe quel venv.
            cibles = [('function', k) for k in _function_keys()]
        elif o['kind'] == 'pipeline':
            cibles = [('pipeline', k) for k in _pipeline_keys()]
        elif o['kind'] == 'model':
            # Modèles SEULS, par énumération du catalogue (2026-09-19) : comme `function`, ce
            # mode ne touche pas aux libraries (venv-dépendantes), donc il est sûr partout.
            # ∪ REFRESH des déjà semés : une ligne ÉCARTÉE garde son manifeste (le YOLO visages
            # exclu le 12/08 pour 0 détection sur une scène de rue), et ce manifeste doit être
            # relu comme les autres — sinon il fossilise ce que l'export ne produit plus
            # (mesuré : il était le seul à garder un chemin absolu après le filtrage).
            semes = {_cle_du_stem(f.stem)
                     for f in (base / DOSSIERS['model']).glob('*.json')}
            cibles = [('model', k) for k in sorted(set(_model_keys()) | semes)]
        else:
            # Jumelles bac à sable EXCLUES : le corpus décrit les apps RÉELLES — une jumelle
            # est jetable et se COMPARE à sa source (route §10.3 marche S, fuite mesurée
            # 18/08 : converter_01 entrait au corpus).
            from wama.common.sandbox import non_sandbox_apps
            cibles = [('app', a) for a in non_sandbox_apps(APP_CATALOG)]
            cibles += [('library', _cle_du_stem(f.stem))
                       for f in sorted((base / DOSSIERS['library']).glob('*.json'))]
            # Modèles : DÉRIVÉS des requires des apps (composition app → model) ∪ refresh
            # des déjà exportés ∪ ÉNUMÉRATION du catalogue (2026-09-19). La dérivation seule
            # laissait dehors tout modèle qu'aucune app ne déclare — mesuré : 12 lignes cloud
            # (11 `anthropic:*` + `claude_code:default`), celles que la découverte cloud
            # apporte sans app propriétaire. Le refresh des semés reste utile : il rattrape un
            # modèle retiré du catalogue dont le manifeste, lui, doit être relu et signalé.
            cites = {r['key'] for genre, a in cibles if genre == 'app'
                     for r in ((_extract('app', a) or {}).get('requires') or [])
                     if isinstance(r, dict) and r.get('kind') == 'model' and r.get('key')}
            semes = {_cle_du_stem(f.stem)
                     for f in (base / DOSSIERS['model']).glob('*.json')}
            cibles += [('model', k) for k in sorted(cites | semes | set(_model_keys()))]
            # Fonctions : ÉNUMÉRÉES depuis le catalogue code (pas de semis, pas de dérivation).
            cibles += [('function', k) for k in _function_keys()]
            # Pipelines déclarés en code (D13, 2026-09-09) : même énumération, même garde.
            cibles += [('pipeline', k) for k in _pipeline_keys()]

        w, s, e, warn = self.stdout.write, self.style.SUCCESS, self.style.ERROR, self.style.WARNING
        ecrits, perimes, refuses, inchanges = [], [], [], []
        #: Les clés du lot, par kind : `_nom_fichier` y voit une collision de CASSE avant
        #: d'écrire (deux clés → un seul fichier sous Windows, vécu le 2026-09-18).
        lot = {}
        for kind, cle in cibles:
            lot.setdefault(kind, []).append(cle)

        for kind, app_id in cibles:
            dossier = base / (o['out'] or DOSSIERS[kind])
            if not o['check']:
                dossier.mkdir(parents=True, exist_ok=True)
            manifest = _extract(kind, app_id)
            if not manifest:
                w(e(f"  {app_id:14s} extraction impossible"))
                continue

            erreurs = list(validate(manifest) or [])
            if erreurs and not o['force']:
                refuses.append(app_id)
                w(e(f"  {app_id:14s} REFUSÉ — {len(erreurs)} erreur(s) de validation"))
                for m in erreurs[:5]:
                    w(e(f"    - {m}"))
                continue

            # Le corpus ne doit contenir que du DÉCLARATIF. `_missing_facets` (et tout futur
            # `_`) est un diagnostic DÉRIVÉ, calculé à l'extraction pour `facet_report` : un
            # LLM entraîné là-dessus apprendrait à l'inventer. Retiré du fichier, remonté en
            # console pour ne pas perdre l'information.
            body = manifest.get('body') or {}
            absentes = list(body.get('_missing_facets') or [])
            manifest = dict(manifest)
            manifest['body'] = {k: v for k, v in body.items() if not k.startswith('_')}
            # Même règle un cran plus bas : `extra_info` d'un modèle mélange le déclaratif
            # (aliases, famille, classes, contrat) et l'état de CETTE machine (chemins absolus,
            # tailles, « installé », empreintes). Seul le déclaratif est un exemple.
            if 'extra_info' in manifest['body']:
                manifest['body'] = dict(manifest['body'],
                                        extra_info=_sans_etat_machine(manifest['body']['extra_info']))

            # `sort_keys` + indentation stable : le diff git doit refléter un changement de
            # contenu, jamais un réordonnancement de dict.
            texte = json.dumps(manifest, ensure_ascii=False, indent=2,
                               sort_keys=True, default=str) + '\n'
            cible = dossier / f"{_nom_fichier(app_id, lot.get(kind, ()))}.json"
            actuel = cible.read_text(encoding='utf-8') if cible.exists() else None

            if actuel == texte:
                inchanges.append(app_id)
                continue
            if o['check']:
                perimes.append(app_id)
                w(warn(f"  {app_id:14s} PÉRIMÉ ({'absent' if actuel is None else 'différent'})"))
                continue

            cible.write_text(texte, encoding='utf-8', newline='\n')
            ecrits.append(app_id)
            note = f" · facettes absentes : {', '.join(absentes)}" if absentes else ""
            w(s(f"  {app_id:14s} écrit — {len(manifest['body'])} facettes, "
                f"{len(texte):,} octets{note}"))

        # ── Manifestes AUTORÉS : le seul angle mort de cette garde (2026-09-07) ────────────
        # Un kind sans `extract` (`dataset` : « AUTORÉ — le manifeste est l'origine ») n'a
        # rien à régénérer, donc pas d'entrée dans DOSSIERS, donc il ne passait NI par la
        # boucle ci-dessus, NI par `manifest_roundtrip` (apps seules). Résultat : le seul
        # manifeste du corpus écrit À LA MAIN était le seul qu'aucun contrôle ne relisait.
        # Rien à REGÉNÉRER ne veut pas dire rien à VALIDER — la validation, elle, ne demande
        # aucune source. Balayage par dossier NON couvert : un futur kind autoré est pris
        # automatiquement, sans qu'on ait à y penser.
        couverts = {base / d for d in DOSSIERS.values()}
        autores, invalides = [], []
        for f in sorted(base.glob('manifests/*/*.json')):
            if f.parent in couverts:
                continue
            autores.append(f)
            try:
                manuel = json.loads(f.read_text(encoding='utf-8'))
            except (ValueError, OSError) as exc:
                invalides.append((f, [f"illisible : {exc}"]))
                continue
            erreurs_a = list(validate(manuel) or [])
            if erreurs_a:
                invalides.append((f, erreurs_a))
        if autores:
            rel = lambda p: p.relative_to(base).as_posix()          # noqa: E731
            for f, msgs in invalides:
                w(e(f"  {rel(f)} INVALIDE — {len(msgs)} erreur(s)"))
                for m in msgs[:5]:
                    w(e(f"    - {m}"))
            if not invalides:
                w(s(f"  {len(autores)} manifeste(s) AUTORÉ(S) relu(s) — tous valides "
                    f"({', '.join(sorted({rel(f.parent) for f in autores}))})"))

        w("")
        if o['check']:
            if perimes or refuses or invalides:
                détail = (f"{len(perimes)} à régénérer, {len(refuses)} invalide(s)"
                          + (f", {len(invalides)} autoré(s) invalide(s)" if invalides else ""))
                w(e(f"Corpus PÉRIMÉ : {détail}. "
                    f"Lancer : python manage.py manifest_export"))
                raise SystemExit(1)
            w(s(f"Corpus à jour ({len(inchanges)} manifeste(s), "
                f"+ {len(autores)} autoré(s) valide(s))."))
            return

        w(f"{len(ecrits)} écrit(s), {len(inchanges)} inchangé(s), {len(refuses)} refusé(s) "
          f"→ {', '.join(sorted({DOSSIERS[k] for k, _ in cibles}))}")
        if refuses:
            w(warn("Les manifestes refusés ne sont PAS des exemples utilisables : corriger "
                   "l'extraction ou la donnée source avant de les faire servir de référence."))
