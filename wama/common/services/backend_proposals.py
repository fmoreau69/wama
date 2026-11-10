"""
BACKENDS PROPOSÉS par le rôle `backend` (marche B2) — contrôles, résolution simulée, smoke,
puis le geste « Valider » qui ÉCRIT le module dans `wama/common/backends/`.

POURQUOI UN MODULE COMMUN. Les contrôles servent deux fois : au RÔLE, qui juge sa propre sortie
avant de la rendre, et au GESTE, qui les REFAIT au moment d'écrire — un fichier d'`outputs/`
peut avoir été modifié entre-temps, et un contrôle qui ne vit que dans le rôle ne protège pas
l'écriture. *Une garde qui vit dans une vue ne protège que cette vue* (leçon du 19/09).

LA RÈGLE LEVÉE (décision de Fabien, 2026-09-29) : « l'agent n'écrit jamais dans `wama/` »
(surface dev, 15/09) est levée POUR CE GESTE-CI, et pour lui seul : un backend validé par un
humain s'écrit dans `wama/common/backends/`. C'est l'essai d'autonomie sur l'intégration de
modèles — hors des apps média. Garde-fous qui restent :
  • un humain décide (le bouton), un compte admin/dev ;
  • les contrôles sont REFAITS à l'écriture ;
  • on n'écrase JAMAIS un module existant ;
  • rien n'est commité : le dépôt reste l'affaire d'un humain.

CE QUE LES CONTRÔLES DISENT, ET CE QU'ILS NE DISENT PAS. Ils attestent la FORME (contrat, moteur,
déclaration, interdits) et la RÉSOLUTION (l'inventaire choisira bien ce backend). Le smoke, un par
contrat (`SMOKES`), atteste qu'une exécution CPU aboutit : génération d'images, ou transcription
d'un extrait de parole réelle (depuis le 2026-10-02) avec un garde-fou contre l'absurde. AUCUN ne
juge la QUALITÉ : c'est à l'humain de regarder, et à la campagne d'évaluation de mesurer.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import re
import time
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Contrat à implémenter selon la TÂCHE du modèle : la table vit dans `backend_inventory`
#: (`TASK_CONTRACTS`), là où elle filtre aussi la résolution — une seule table, deux usages.
#: Le reste se DÉRIVE du contrat (méthodes abstraites, lues par AST).
DEFAULT_CONTRACT = ('base', 'BaseModelBackend')

#: Mutation du cache HF dans l'environnement — interdite (AGENTS.md, 2026-09-03).
HF_ENV_MUTATION = re.compile(
    r"os\.(environ\s*\[\s*['\"]|environ\.setdefault\(\s*['\"]|putenv\(\s*['\"])"
    r"(HF_HUB_CACHE|HUGGINGFACE_HUB_CACHE|HF_HOME)")
#: Téléchargement au chargement — interdit : les poids sont INSTALLÉS (`component_paths`).
NETWORK_FETCH = re.compile(r'\b(snapshot_download|hf_hub_download)\s*\(')
#: Nom de module autorisé pour un backend écrit dans le paquet.
MODULE_NAME = re.compile(r'^[a-z][a-z0-9_]{2,60}_backend$')


def backends_dir() -> Path:
    return Path(settings.BASE_DIR) / 'wama' / 'common' / 'backends'


def outputs_dir() -> Path:
    return Path(settings.BASE_DIR) / 'wama-dev-ai' / 'outputs'


def contract_for_task(task: str) -> tuple:
    """(module, classe) du contrat qu'un backend écrit pour `task` doit implémenter."""
    from .backend_inventory import TASK_CONTRACTS
    spec = TASK_CONTRACTS.get(task or '')
    return spec[:2] if spec else DEFAULT_CONTRACT


def required_methods(contract: tuple) -> set:
    """Méthodes abstraites que le contrat laisse à implémenter — lues par AST, jamais importées
    (même lecture que l'inventaire, `backend_inventory._file_classes`)."""
    from .backend_inventory import _contract_abstract_methods, _file_classes
    module, cls = contract
    classes, _ = _file_classes(backends_dir() / f'{module}.py')
    info = classes.get(cls)
    base_abstract = set(_contract_abstract_methods())
    if info is None:                                   # le contrat commun lui-même
        return base_abstract
    return (set(info['propres_abstraites']) | base_abstract) - set(info['definies'])


def contract_must_read(contract: tuple) -> dict:
    """`{méthode: (paramètres…)}` que le CONTRAT déclare impossibles à ignorer (`MUST_READ`, lu par
    AST dans son module, jamais importé — même lecture que `required_methods`)."""
    module, cls = contract
    try:
        tree = ast.parse((backends_dir() / f'{module}.py').read_text(encoding='utf-8'))
    except (OSError, SyntaxError):
        return {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for s in node.body:
                if isinstance(s, ast.Assign) and any(getattr(t, 'id', '') == 'MUST_READ'
                                                     for t in s.targets):
                    value = _literal(s.value)
                    return value if isinstance(value, dict) else {}
    return {}


def model_id_of(model_key: str) -> str:
    """Identifiant que `SUPPORTED_MODELS` doit déclarer — la règle de `backend_for_model`,
    désormais commune (`model_keys.backend_model_id`, 2026-10-07)."""
    from wama.common.utils.model_keys import backend_model_id
    return backend_model_id(model_key)


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _is_vendored_engine(engine: str) -> bool:
    """Le moteur est-il celui d'une librairie VENDORISÉE du registre (route library, voie vendor) ?"""
    try:
        from wama.common.models import Library
        return any((lib.vendor or {}).get('engine') == engine
                   for lib in Library.objects.exclude(vendor={}))
    except Exception:
        return False


def _vendored_code_caps_process_vram(engine: str) -> bool:
    """Le code vendorisé pose-t-il un plafond de VRAM à l'échelle du PROCESSUS ? (YuE2 : ~92 %,
    réglage qui survit au déchargement — mesuré au constructeur de `YuE2Pipeline`, 2026-10-01)."""
    from django.conf import settings
    root = Path(settings.BACKEND_VENDOR_DIR) / engine
    for path in root.rglob('*.py'):
        if 'tests' in path.parts:
            continue
        try:
            if 'set_per_process_memory_fraction' in path.read_text(encoding='utf-8', errors='ignore'):
                return True
        except OSError:
            continue
    return False


def _vendored_top_packages(engine: str) -> set:
    """Paquets de premier niveau du clone (racine ou `src/`) — des noms d'import ABSENTS du venv."""
    from django.conf import settings

    from wama.common.utils.download_calls import code_packages
    return code_packages(Path(settings.BACKEND_VENDOR_DIR) / engine, modules=False)


def _vendored_import_errors(tree, engine: str) -> list:
    """Chaque `import_vendored('<module>', subdir=…)` désigne-t-il un module IMPORTABLE du clone ?

    Mesuré le 2026-10-01 (YuE2) : le rôle avait écrit `import_vendored('pipeline',
    subdir='src/yue2')` — le fichier existe, mais c'est un module d'un PAQUET (`yue2/__init__.py`,
    imports relatifs) : importé seul, il échoue au premier `from .storage import …`. La règle :
    un module situé dans un paquet s'importe par son nom COMPLET depuis la racine du paquet."""
    from django.conf import settings
    root = Path(settings.BACKEND_VENDOR_DIR) / engine
    errors = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'import_vendored'
                and node.args and isinstance(node.args[0], ast.Constant)):
            continue
        module = str(node.args[0].value)
        subdir = next((str(k.value.value) for k in node.keywords
                       if k.arg == 'subdir' and isinstance(k.value, ast.Constant)), '')
        base = root / subdir if subdir else root
        target = base.joinpath(*module.split('.'))
        if not (target.with_suffix('.py').is_file() or (target / '__init__.py').is_file()):
            errors.append(f"import_vendored({module!r}, subdir={subdir!r}) : aucun module à "
                          f"{target.relative_to(root)} dans le clone")
        elif (base / '__init__.py').is_file():
            errors.append(f"import_vendored({module!r}, subdir={subdir!r}) : « {subdir} » est un "
                          f"PAQUET — importer par le nom complet depuis sa racine "
                          f"(ex. subdir={str(Path(subdir).parent)!r}, "
                          f"module='{Path(subdir).name}.{module}')")
    return errors


#: Ce qu'une entrée `SUPPORTED_MODELS` d'un modèle INSTALLÉ porte toujours sans justification : le
#: nom de sa ligne de catalogue (le champ de `pyannote_diarizer`). Toute AUTRE valeur doit être LUE
#: par le module — un paramètre d'exécution (`multitask` de NeMo, `platform_ref` de pyannote) se garde ;
#: une valeur que personne ne lit est une seconde vérité. Vécu le 2026-10-06 : la consigne du rôle
#: exigeait `{'name', 'description', 'vram'}`, recopiés dans cinq backends (Supra2-IMG, FrWhisper,
#: SheetSage2, Kyutai, YuE2) et lus par PERSONNE — l'inventaire ne lit que les clés, les faits sont
#: au registre. Première version (le même jour) : `model_key` SEUL — trop stricte, elle aurait
#: refusé un vrai paramètre d'exécution ; la règle est « lue », pas « absente ».
SUPPORTED_ENTRY_KEYS = frozenset({'model_key'})


def _unread_keys(entry: dict, code: str) -> list:
    """Clés de l'entrée que le module ne LIT nulle part hors de la table elle-même — `code` est le
    source du module, la table `SUPPORTED_MODELS` comprise (on l'en retire avant de chercher)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    rest = code
    for n in tree.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and getattr(n.targets[0], 'id', '') == 'SUPPORTED_MODELS'):
            rest = code.replace(ast.get_source_segment(code, n) or '', '', 1)
    return sorted(k for k in entry if k not in SUPPORTED_ENTRY_KEYS
                  and f"'{k}'" not in rest and f'"{k}"' not in rest)


def supported_entry_errors(model_id: str, entry, code: str = None) -> list:
    """Erreurs de l'entrée `SUPPORTED_MODELS[model_id]` d'un modèle installé : `model_key` (s'il
    est là) désigne CE modèle, et toute autre valeur est lue par le module (`code`)."""
    if not isinstance(entry, dict):
        return [f"SUPPORTED_MODELS[{model_id!r}] n'est pas un dict"]
    errors = []
    unread = _unread_keys(entry, code) if code is not None else []
    if unread:
        errors.append(f"SUPPORTED_MODELS[{model_id!r}] porte {unread}, que le module ne LIT pas : "
                      f"une seconde vérité (nom, description, VRAM sont au CATALOGUE) — ne garder "
                      f"que `model_key` et les paramètres d'exécution que le code emploie")
    key = entry.get('model_key')
    if key is not None and model_id_of(str(key)) != model_id:
        errors.append(f"SUPPORTED_MODELS[{model_id!r}]['model_key'] = {key!r} désigne un AUTRE "
                      f"modèle")
    return errors


def replacing_loaders(engine: str, entry: str) -> str:
    """Ce qu'un backend appelle À LA PLACE de `entry`, une fonction du moteur vendorisé qui
    télécharge — dit en clair, pour le refus de `check_source` et la matière du rôle : ses
    chargeurs qui ne téléchargent ni n'écrivent, et les étapes qu'il laisse
    (`download_calls.entry_loaders`). Vécu le 2026-11-09 : deux modèles, refusés sur
    « appeler les chargeurs qu'elles appellent », ont rappelé `initialize_service` faute de les
    connaître."""
    from wama.common.utils.download_calls import entry_loaders
    from wama.model_manager.services.vendor_installer import vendor_dir
    parts = entry_loaders(vendor_dir(engine), entry)
    if not parts['loaders']:
        return (f"{entry} : reproduire ses étapes sans télécharger, sur les chemins installés "
                "(component_paths)")
    owners = parts['owners']
    skipped = [f'{n} (télécharge)' for n in parts['downloads']] + \
              [f'{n} (écrit un fichier)' for n in parts['writes']]

    def named(name, where):
        return (f'{name} (méthode de {owners[name]}, {where})' if name in owners
                else f'{name} (fonction de module, {where})')
    # L'objet qui porte l'entrée (2026-11-10, ACE-Step : des méthodes de mixins appelées comme des
    # fonctions de leur module, `AttributeError` à l'essai).
    host = ''
    if entry in owners:
        heirs = ', '.join(f'{c} ({w})' for c, w in parts['heirs'].items())
        host = (f" ; {entry} est une méthode de {owners[entry]}"
                + (f", dont hérite {heirs}" if heirs else '')
                + " : ses chargeurs-méthodes s'appellent sur la MÊME instance "
                  "(`instance.<chargeur>(…)`), jamais sur le module qui les définit")
    return (f"à la place de {entry}, appeler sur les chemins installés (component_paths) ses "
            f"chargeurs qui ne téléchargent ni n'écrivent : "
            + ', '.join(named(n, where) for n, where in parts['loaders'].items())
            + (f" — sans {', '.join(skipped)}" if skipped else '') + host)


def check_source(code: str, *, engine: str, model_id: str, contract: tuple) -> dict:
    """Contrôles de FORME d'un module de backend proposé. `ok` = aucune erreur."""
    errors, warnings = [], []
    try:
        tree = ast.parse(code)
        compile(code, '<backend proposé>', 'exec')
    except SyntaxError as e:
        return {'ok': False, 'errors': [f'syntaxe : {e}'], 'warnings': [], 'class_name': None}

    supported = None
    for n in tree.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and getattr(n.targets[0], 'id', '') == 'SUPPORTED_MODELS'):
            supported = _literal(n.value)
    if not isinstance(supported, dict):
        errors.append('SUPPORTED_MODELS absent du NIVEAU MODULE, ou pas un dict littéral')
    elif model_id not in supported:
        errors.append(f"SUPPORTED_MODELS ne déclare pas « {model_id} » : l'inventaire ne "
                      "choisirait pas ce backend face à un autre du même moteur")
    else:
        errors += supported_entry_errors(model_id, supported[model_id], code)

    base_name = contract[1]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
               and any((b.id if isinstance(b, ast.Name) else getattr(b, 'attr', '')) == base_name
                       for b in n.bases)]
    if len(classes) != 1:
        errors.append(f'{len(classes)} classe(s) héritant de {base_name} (attendu : 1)')
        return {'ok': False, 'errors': errors, 'warnings': warnings, 'class_name': None}
    cls = classes[0]
    attrs, defined = {}, set()
    for s in cls.body:
        if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
            attrs[s.targets[0].id] = _literal(s.value)
        elif (isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)
              and s.value is not None):
            # `REQUIRED_PACKAGES: list = []` — la forme ANNOTÉE, celle d'audiocpp_backend : la
            # lire comme absente refusait un backend juste (2026-10-01, YuE2).
            attrs[s.target.id] = _literal(s.value)
        elif isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(s.name)
    if attrs.get('ENGINE') != engine:
        errors.append(f"ENGINE = {attrs.get('ENGINE')!r}, attendu {engine!r} (moteur déclaré)")
    if not isinstance(attrs.get('REQUIRED_PACKAGES'), list):
        errors.append('REQUIRED_PACKAGES absent (liste littérale de noms d\'import)')
    missing = sorted(required_methods(contract) - defined)
    if missing:
        errors.append(f'méthodes du contrat non implémentées : {missing}')
    for method, params in contract_must_read(contract).items():
        node = next((s for s in cls.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and s.name == method), None)
        if node is None:
            continue
        read = {n.id for statement in node.body for n in ast.walk(statement)
                if isinstance(n, ast.Name)}
        unread = [p for p in params if p not in read]
        if unread:
            errors.append(f"{method} ne lit jamais {unread} : le contrat veut qu'un moteur qui ne "
                          "les suit pas les REFUSE en le disant (ex. self.refuse_score), jamais en "
                          "les ignorant")
    if HF_ENV_MUTATION.search(code):
        errors.append("mutation du cache HF dans l'environnement (interdit, AGENTS.md)")
    if NETWORK_FETCH.search(code):
        errors.append('téléchargement au chargement (snapshot_download/hf_hub_download) : les '
                      'poids sont installés, ils se lisent par component_paths')
    if _is_vendored_engine(engine):
        # Le code d'un moteur vendorisé n'est PAS dans le venv (2026-10-01 : le backend de YuE2
        # proposé importait `yue2` à nu — ImportError au premier chargement, invisible ici).
        if attrs.get('VENDORED') is not True:
            errors.append(f"moteur VENDORISÉ « {engine} » : déclarer VENDORED = True (le clone "
                          "absent entre alors dans missing_packages)")
        if 'import_vendored(' not in code:
            errors.append(f"moteur VENDORISÉ « {engine} » : importer son code par "
                          "self.import_vendored(...) — il n'est pas installé dans le venv")
        errors += _vendored_import_errors(tree, engine)
        # Ce que le moteur télécharge LUI-MÊME (2026-11-08, ACE-Step : `initialize_service` y mène
        # par `_ensure_models_present`) : la lecture du contrôle de la route sur le clone. Le
        # contrôle par motif ci-dessus ne voit que les appels écrits dans le backend.
        from wama.common.utils.download_calls import called_name, functions_reaching_download
        from wama.model_manager.services.vendor_installer import vendor_dir
        reaching = functions_reaching_download(vendor_dir(engine))
        reached = sorted({called_name(n) for n in ast.walk(tree) if isinstance(n, ast.Call)}
                         & set(reaching))
        if reached:
            errors.append(f"appelle {', '.join(f'{n} ({reaching[n]})' for n in reached)} : "
                          f"le code du moteur « {engine} » y télécharge lui-même — "
                          + '; '.join(replacing_loaders(engine, n) for n in reached))
        own = _vendored_top_packages(engine) & set(attrs.get('REQUIRED_PACKAGES') or [])
        if own:
            errors.append(f"REQUIRED_PACKAGES nomme le code VENDORISÉ lui-même ({sorted(own)}) : "
                          "il n'est pas dans le venv, missing_packages() le déclarerait absent à "
                          "vie — VENDORED = True suffit à dire que le clone est requis")
        if (_vendored_code_caps_process_vram(engine)
                and not re.search(r'set_per_process_memory_fraction\(\s*1(\.0*)?\b', code)):
            errors.append(f"le moteur VENDORISÉ « {engine} » plafonne la VRAM de TOUT le processus "
                          "(set_per_process_memory_fraction) : la rendre (1.0) dans unload(), sinon "
                          "le worker GPU partagé reste bridé pour les modèles suivants")
    if 'component_paths' not in code:
        warnings.append("n'emploie pas component_paths : d'où viennent les poids ?")
    if 'NotImplementedError' in code:
        warnings.append('trou DÉCLARÉ (NotImplementedError) — à lire avant de valider')
    return {'ok': not errors, 'errors': errors, 'warnings': warnings, 'class_name': cls.name}


def simulate_resolution(code: str, *, module: str, engine: str, model_id: str,
                        task: str = '') -> dict:
    """La résolution que l'inventaire fera APRÈS écriture : le vivier réel + cette entrée.
    ⚠ L'entrée simulée n'existe pas sur disque : sa lignée est inconnue (`_class_lineage` →
    None), donc le filtre de contrat la GARDE — c'est `check_source` qui atteste son contrat."""
    from .backend_inventory import BackendEntry, resolvable_entries, resolve_entry
    tree = ast.parse(code)
    supported = []
    for n in tree.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and getattr(n.targets[0], 'id', '') == 'SUPPORTED_MODELS'):
            value = _literal(n.value)
            supported = list(value) if isinstance(value, dict) else []
    mine = BackendEntry(app='common', name=module, path=module, kind='classe', engine=engine,
                        supported_models=supported, module=f'wama.common.backends.{module}')
    rivals = [e for e in resolvable_entries() if e.engine == engine]
    chosen = resolve_entry(engine, model_id, entries=resolvable_entries() + [mine], task=task)
    return {'resolved': chosen is mine,
            'rivals': [e.module or e.name for e in rivals],
            'chosen': (chosen.module if chosen is not None else None)}


#: Images demandées au smoke : DEUX, pour éprouver le contrat `num_images` (2026-09-30). Mesuré
#: sur Supra2-IMG le jour même : deux backends proposés passaient un smoke à UNE image alors que
#: l'un rendait une seule image pour quatre demandées (deepseek) et l'autre quatre images
#: IDENTIQUES (qwen3.8, graine non déclinée par image) — ce que la génération réelle a montré.
SMOKE_IMAGES = 2


def smoke(code: str, *, module: str, model_key: str, contract: tuple, out_dir: Path) -> dict:
    """Exécute le backend proposé SUR CPU, sans l'écrire dans le paquet — un essai par CONTRAT
    (`SMOKES`) ; un contrat sans essai le DIT, et l'humain sait qu'il valide sans exécution."""
    runner = SMOKES.get(contract[1])
    if runner is None:
        return {'ran': False, 'reason': f'pas de smoke pour le contrat {contract[1]}'}
    return runner(code, module=module, model_key=model_key, out_dir=out_dir)


def _proposed_backend(code: str, module: str, tmp: str, method: str):
    """Instance du backend proposé, chargé depuis `tmp` sous un nom DANS le paquet : les imports
    relatifs (`from .image_generation_base …`) résolvent, alors que le fichier n'y est pas —
    l'inventaire ne le voit donc pas pendant le smoke. La classe est celle qui porte `method`."""
    path = Path(tmp) / f'{module}.py'
    path.write_text(code, encoding='utf-8')
    spec = importlib.util.spec_from_file_location(f'wama.common.backends.{module}', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    classes = [c for c in vars(mod).values() if isinstance(c, type)
               and c.__module__ == mod.__name__ and hasattr(c, method)]
    return classes[0]()


def _smoke_image(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement puis une génération de `SMOKE_IMAGES` images, qui doivent être autant et
    DISTINCTES."""
    import tempfile
    from unittest import mock

    from wama.common.backends.image_generation_base import GenerationParams
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'generate')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            with mock.patch('wama.common.utils.onnx_utils.onnx_providers',
                            lambda *a, **k: ['CPUExecutionProvider']):
                if not backend.load(model_id_of(model_key)):
                    return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
                # 10 pas : on éprouve un COMPORTEMENT (chargement, nombre, variété), pas une
                # qualité — deux images à 10 pas coûtent ce qu'une coûtait à 20.
                result = backend.generate(GenerationParams(
                    prompt='a red apple on a wooden table', model=model_id_of(model_key),
                    width=256, height=256, steps=10, guidance_scale=4.0, seed=0,
                    num_images=SMOKE_IMAGES))
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    if not getattr(result, 'success', False) or not result.images:
        return {'ran': True, 'ok': False, 'error': getattr(result, 'error', 'aucune image'),
                'seconds': round(time.time() - started, 1)}
    images = list(result.images)
    if len(images) != SMOKE_IMAGES:
        return {'ran': True, 'ok': False, 'seconds': round(time.time() - started, 1),
                'error': f'num_images={SMOKE_IMAGES} demandé, {len(images)} image(s) rendue(s) '
                         f'— le backend ignore num_images'}
    if len({img.tobytes() for img in images}) < len(images):
        return {'ran': True, 'ok': False, 'seconds': round(time.time() - started, 1),
                'error': f'{len(images)} images IDENTIQUES — la graine ne varie pas d\'une '
                         f'image à l\'autre'}
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = out_dir / f'backend_smoke_{module}.png'
    result.images[0].save(image_path)
    return {'ran': True, 'ok': True, 'seconds': round(time.time() - started, 1),
            'image': str(image_path.relative_to(settings.BASE_DIR)),
            'size': list(result.images[0].size)}


#: L'extrait que transcrit le smoke de PAROLE (2026-10-02) : `SMOKE_SPEECH_SECONDS` à partir de
#: `SMOKE_SPEECH_START` d'un enregistrement des corpus d'évaluation versés en médiathèque système
#: (`asr_eval_corpus`), celui du corpus `SMOKE_SPEECH_CORPUS` de préférence : de la parole réelle
#: AVEC sa référence, donc un taux d'erreur, pas seulement « du texte est sorti ».
#: Pourquoi il existe : le 01/10, deux backends de transcription proposés passaient les contrôles
#: et la résolution sans aucun essai — et échouaient à CHAQUE transcription (audio passé en
#: position au processeur ; `pipeline` qui importe torchcodec, cassé dans le venv).
SMOKE_SPEECH_CORPUS = 'summ-re'
SMOKE_SPEECH_START = 60.0
SMOKE_SPEECH_SECONDS = 30.0
#: Au-delà, la sortie n'a plus de rapport avec la parole (langue, audio mal lu, boucle) : c'est un
#: garde-fou contre l'absurde, pas un critère de qualité — le juger reste la campagne d'évaluation.
SMOKE_SPEECH_MAX_WER = 0.75


def smoke_speech_clip():
    """`(SystemAsset de parole, chemin de sa référence | None)` de l'extrait du smoke, ou
    `(None, None)` si aucun corpus n'est versé. Les VARIANTES (dégradées, nivelées, améliorées)
    sont écartées : le smoke juge le backend, pas un prétraitement."""
    from wama.media_library.models import SystemAsset
    variants = ('base', 'degradation', 'leveled', 'enhancement')
    clips = [a for a in SystemAsset.objects.filter(asset_type='speech').order_by('name')
             if (a.attributes or {}).get('corpus') and a.file
             and not any((a.attributes or {}).get(k) for k in variants)]
    if not clips:
        return None, None
    clips.sort(key=lambda a: ((a.attributes or {}).get('corpus') != SMOKE_SPEECH_CORPUS, a.name))
    clip = clips[0]
    # Même convention que le banc : `attributes['reference']`, sinon `<nom>_reference`.
    ref_name = (clip.attributes or {}).get('reference') or f'{clip.name}_reference'
    reference = SystemAsset.objects.filter(asset_type='document', name=ref_name).first()
    return clip, (reference.file.path if reference and reference.file else None)


def _reference_window(path, start: float, seconds: float):
    """`(début, fin, texte)` de l'extrait CALÉ sur des segments ENTIERS de la référence : ceux qui
    tiennent dans [start, start + seconds], l'extrait allant du premier au dernier. Une phrase
    coupée par le bord de l'extrait comptait comme erreur (calibration du 2026-10-02 : FrWhisper,
    juste, à 75 %). Lus par le lecteur que la surface `transcriber` déclare à l'évaluation — le
    registre, pas un import d'app. Sans référence lisible : l'extrait brut, sans texte."""
    raw = (start, start + seconds, '')
    from .result_evaluation import evaluation_spec
    spec = evaluation_spec('transcriber')
    if not path or spec is None or spec.read_reference_segments is None:
        return raw
    inside = [s for s in (spec.read_reference_segments(path) or [])
              if float(s.get('start_time') or 0) >= start
              and float(s.get('end_time') or 0) <= start + seconds]
    if not inside:
        return raw
    return (min(float(s['start_time']) for s in inside), max(float(s['end_time']) for s in inside),
            ' '.join(str(s.get('text') or '') for s in inside).strip())


def _smoke_speech(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis transcription d'un extrait de parole réelle : un texte, des segments
    ordonnés et DANS l'extrait, et un taux d'erreur qui ne soit pas absurde face à la référence."""
    import tempfile
    from unittest import mock

    import soundfile as sf

    from wama.common.utils.audio_decode import decode_window
    clip, reference = smoke_speech_clip()
    if clip is None:
        return {'ran': False, 'reason': 'aucun corpus de parole versé en médiathèque système '
                                        '(manage.py asr_eval_corpus)'}
    started = time.time()
    begin, end, expected = _reference_window(reference, SMOKE_SPEECH_START, SMOKE_SPEECH_SECONDS)
    # La langue que le corpus DÉCLARE pour l'enregistrement (une seule) ; sinon le moteur détecte.
    language = (clip.attributes or {}).get('language')
    language = language if isinstance(language, str) else None
    with tempfile.TemporaryDirectory() as tmp:
        audio, rate = decode_window(clip.file.path, 16000, begin, end - begin)
        extract = Path(tmp) / 'smoke_speech.wav'
        sf.write(str(extract), audio, rate)
        duration = len(audio) / float(rate)
        try:
            backend = _proposed_backend(code, module, tmp, 'transcribe')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            # CPU, comme le smoke image : le rôle ne dispute jamais le GPU au worker.
            with mock.patch('torch.cuda.is_available', return_value=False):
                if not backend.load(model_id_of(model_key)):
                    return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
                result = backend.transcribe(audio_path=str(extract), language=language)
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    text = (getattr(result, 'text', '') or '').strip()
    if not getattr(result, 'success', False) or not text:
        return {'ran': True, 'ok': False, 'seconds': seconds,
                'error': getattr(result, 'error', None) or 'aucun texte'}
    segments = list(result.segments or [])
    starts = [s.start_time for s in segments]
    if not segments or starts != sorted(starts) or any(
            s.end_time < s.start_time or s.end_time > duration + 1.0 for s in segments):
        return {'ran': True, 'ok': False, 'seconds': seconds,
                'error': f'segments hors de l\'extrait ou désordonnés ({len(segments)} segment(s), '
                         f'extrait de {duration:.1f} s)'}
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'clip': clip.name,
           'window': [round(begin, 2), round(end, 2)], 'segments': len(segments),
           'text': text[:200]}
    if expected:
        from .text_metrics import word_error_rate
        wer = word_error_rate(expected, text, language).rate
        out['wer'] = round(wer, 3) if wer is not None else None
        if wer is not None and wer > SMOKE_SPEECH_MAX_WER:
            out.update(ok=False, error=f'taux d\'erreur {wer:.0%} sur l\'extrait (> '
                                       f'{SMOKE_SPEECH_MAX_WER:.0%}) : la sortie n\'a pas de rapport '
                                       f'avec la parole')
    return out


#: La mélodie dont le smoke de PARTITION extrait les notes (2026-10-03) : gamme de do majeur montante puis
#: descendante, deux fois, en noires à `SMOKE_SCORE_BPM` — SYNTHÉTISÉE ici, donc ses notes sont
#: connues sans aucun fichier versé (la médiathèque système n'a aucune musique). Mesuré sur
#: SheetSage2 : tempo 120 et tonalité C retrouvés, les 32 notes exactes plus une parasite en fin.
#: ⚠ Le silence final n'est pas décoratif : une note collée à la toute fin de l'audio fait lever
#: le moteur (« cannot be represented on the decoded subbeat grid », mesuré le même jour).
SMOKE_SCORE_MIDI = (60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60, 60) * 2
SMOKE_SCORE_BPM = 120
SMOKE_SCORE_TAIL_SECONDS = 2.0
#: En deçà, les notes rendues n'ont plus de rapport avec la mélodie jouée : garde-fou contre
#: l'absurde (audio mal lu, mauvais canal), pas critère de qualité.
SMOKE_SCORE_MIN_MATCH = 0.75
_NOTE_NAMES = 'C_D_EF_G_A_B'
_ABC_HEADER = re.compile(r'^\s*(?:[A-Za-z]:|%)')
_ABC_NOTE = re.compile(r'[_^=]*([A-Ga-g])[,\']*')


def smoke_score_clip(path, rate: int = 22050) -> str:
    """Écrit la mélodie du smoke dans `path` (WAV) et rend ses NOMS de notes attendus (`CDEF…`).

    Timbre à harmoniques et grosse caisse sur chaque temps : un extracteur de partition suit
    la pulsation, une sinusoïde nue n'en donne aucune."""
    import numpy as np
    import soundfile as sf
    beat = 60.0 / SMOKE_SCORE_BPM
    t = np.arange(int(rate * beat)) / rate
    kick = np.sin(2 * np.pi * (60 + 80 * np.exp(-30 * t)) * t) * np.exp(-12 * t)
    envelope = np.minimum(1, t / 0.01) * np.exp(-1.5 * t)
    notes = []
    for midi in SMOKE_SCORE_MIDI:
        f = 440.0 * 2 ** ((midi - 69) / 12)
        tone = sum(a * np.sin(2 * np.pi * f * k * t) for k, a in ((1, 1.0), (2, .5), (3, .3), (4, .15)))
        notes.append(0.25 * tone * envelope + 0.35 * kick)
    audio = np.concatenate(notes + [np.zeros(int(rate * SMOKE_SCORE_TAIL_SECONDS))])
    sf.write(str(path), (audio / np.abs(audio).max() * 0.8).astype('float32'), rate)
    return ''.join(_NOTE_NAMES[m % 12] for m in SMOKE_SCORE_MIDI)


def abc_note_names(abc: str) -> str:
    """Noms des notes d'un texte ABC, dans l'ordre et sans octave (`C4D4|c2` → `CDC`) — en-têtes,
    commentaires, annotations `"…"` et décorations `!…!` écartés ; les silences ne sont pas des
    notes. Lecture MINIMALE, à la mesure du smoke : elle ne juge pas les altérations."""
    names = []
    for line in (abc or '').splitlines():
        if _ABC_HEADER.match(line):
            continue
        line = re.sub(r'"[^"]*"|![^!]*!', '', line)
        names += [m.group(1).upper() for m in _ABC_NOTE.finditer(line)]
    return ''.join(names)


def _smoke_score(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis extraction de la partition de la mélodie connue : un ABC à tonalité (`K:`), dont la
    suite de notes ressemble à celle jouée."""
    import difflib
    import tempfile
    from unittest import mock
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / 'smoke_score.wav'
        expected = smoke_score_clip(clip)
        try:
            backend = _proposed_backend(code, module, tmp, 'extract_score')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            # CPU, comme les autres smokes : le rôle ne dispute jamais le GPU au worker.
            with mock.patch('torch.cuda.is_available', return_value=False):
                if not backend.load(model_id_of(model_key)):
                    return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
                abc = backend.extract_score(model_id=model_id_of(model_key),
                                               audio_path=str(clip),
                                               output_dir=str(Path(tmp) / 'out'),
                                               melody_only=True)
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    if not isinstance(abc, str) or not re.search(r'^\s*K:', abc, re.M):
        return {'ran': True, 'ok': False, 'seconds': seconds,
                'error': f'pas une partition ABC (aucun en-tête K:) : {str(abc)[:120]!r}'}
    found = abc_note_names(abc)
    match = difflib.SequenceMatcher(None, expected, found).ratio()
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'notes': len(found),
           'match': round(match, 3), 'abc': abc[:200]}
    if match < SMOKE_SCORE_MIN_MATCH:
        out.update(ok=False, error=f'{match:.0%} des notes de la mélodie retrouvées (< '
                                   f'{SMOKE_SCORE_MIN_MATCH:.0%}) : la partition n\'a pas de '
                                   f'rapport avec ce qui est joué')
    return out


#: Le smoke de MUSIQUE (2026-11-10, ACE-Step 1.5) : un instrumental court, demandé comme le
#: composer le demande. Avant lui, un backend `text-to-music` qui passait les contrôles se validait
#: sans aucune exécution (`smoke` : « pas de smoke pour le contrat »). 10 s : la durée minimale
#: qu'ACE-Step accepte (`acestep/constants.py`, `DURATION_MIN`), courte pour un essai sur CPU.
SMOKE_MUSIC_PROMPT = 'A calm acoustic guitar instrumental, slow tempo.'
SMOKE_MUSIC_SECONDS = 10.0
#: Sous ce niveau efficace (échantillons dans [-1, 1]), l'audio est du SILENCE — un garde-fou
#: contre l'absurde (latents nuls, décodage raté), pas un critère de qualité.
SMOKE_MUSIC_MIN_RMS = 1e-3


def _progress_misuse(misuse: list) -> str:
    """Ce que l'essai a vu de la forme d'appel du moteur sur le rappel du composer, '' sinon."""
    if not misuse:
        return ''
    args, kwargs = misuse[0]
    return (f" — le rappel de progression du composer (UN argument : un pourcentage de 0 à 100) a "
            f"reçu args={args!r} kwargs={kwargs!r} : c'est ainsi que le MOTEUR appelle sa "
            f"progression ; l'adapter (signature du moteur → pourcentage), jamais le lui passer tel "
            f"quel")


def _smoke_music(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis un court instrumental : le fichier écrit à `output_path` et ce chemin
    rendu (le contrat), lisible, d'une durée plausible (au plus le double de la demande — un moteur
    qui ne la maîtrise pas la traite en borne), fait de valeurs finies et non silencieux."""
    import shutil
    import tempfile
    from unittest import mock

    import numpy as np
    import soundfile as sf
    started, progress, misuse = time.time(), [], []

    def composer_progress(*args, **kwargs):
        """Le rappel du COMPOSER : un argument, un pourcentage. Un autre appel est ENREGISTRÉ —
        c'est la forme d'appel du MOTEUR, que le backend doit adapter (ACE-Step appelle
        `progress(0.51, desc='Preparing inputs...')`) — puis refusé comme le ferait le composer."""
        if len(args) != 1 or kwargs:
            misuse.append((args, kwargs))
            raise TypeError(f'progress_callback prend UN argument ; appelé avec {args!r} {kwargs!r}')
        progress.append(args[0])
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / 'out' / 'smoke_music.wav'
        output.parent.mkdir()                          # le composer donne un dossier existant
        try:
            backend = _proposed_backend(code, module, tmp, 'generate')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            # CPU, comme les autres smokes : le rôle ne dispute jamais le GPU au worker.
            with mock.patch('torch.cuda.is_available', return_value=False):
                if not backend.load(model_id_of(model_key)):
                    return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
                # Le rappel de progression du COMPOSER : un argument, un pourcentage. Sans lui, le
                # backend d'ACE-Step passait l'essai en transmettant au moteur un rappel que ce
                # dernier appelle avec DEUX arguments — l'erreur du tout premier essai (2026-11-10).
                returned = backend.generate(model_id=model_id_of(model_key),
                                            prompt=SMOKE_MUSIC_PROMPT,
                                            duration=SMOKE_MUSIC_SECONDS,
                                            output_path=str(output), sampling={'seed': 0},
                                            progress_callback=composer_progress)
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}'
                    + _progress_misuse(misuse), 'seconds': round(time.time() - started, 1)}
        seconds = round(time.time() - started, 1)
        if misuse:
            return {'ran': True, 'ok': False, 'seconds': seconds,
                    'error': _progress_misuse(misuse).lstrip(' —')}
        if not output.is_file():
            return {'ran': True, 'ok': False, 'seconds': seconds,
                    'error': f'aucun fichier à output_path (rendu : {returned!r})'}
        if Path(str(returned)) != output:
            return {'ran': True, 'ok': False, 'seconds': seconds,
                    'error': f'rend {returned!r} au lieu de output_path (contrat : écrire à '
                             f'output_path et rendre ce chemin)'}
        try:
            audio, rate = sf.read(str(output), always_2d=True, dtype='float32')
        except Exception as e:
            return {'ran': True, 'ok': False, 'seconds': seconds,
                    'error': f'fichier audio illisible : {type(e).__name__}: {e}'}
        out_dir.mkdir(parents=True, exist_ok=True)
        kept = out_dir / f'backend_smoke_{module}.wav'
        shutil.copyfile(output, kept)
    length = len(audio) / rate if rate else 0.0
    finite = bool(audio.size) and bool(np.isfinite(audio).all())
    rms = float(np.sqrt(np.mean(np.square(audio)))) if finite else 0.0
    base = Path(settings.BASE_DIR)
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'duration': round(length, 2),
           'rate': rate, 'rms': round(rms, 4),
           'audio': str(kept.relative_to(base) if kept.is_relative_to(base) else kept)}
    off_scale = [p for p in progress if not isinstance(p, (int, float)) or not 0 <= p <= 100]
    # Jugée AVANT le 100 final : un module qui passait au composer `int(0.51)` envoyait 0 tout du
    # long, puis 100 — le dernier appel masquait la fraction (ACE-Step, 2026-11-10).
    during = progress[:-1] if progress and progress[-1] == 100 else progress
    if not finite:
        out.update(ok=False, error='audio vide ou fait de valeurs non finies (NaN, inf)')
    elif off_scale or (len(during) > 1 and max(during) <= 1):
        out.update(ok=False, error=f'progression hors contrat ({(off_scale or progress)[:5]}) : '
                                   f'progress_callback reçoit un pourcentage, de 0 à 100')
    elif not 1.0 <= length <= 2 * SMOKE_MUSIC_SECONDS:
        out.update(ok=False, error=f'{length:.1f} s pour {SMOKE_MUSIC_SECONDS:g} s demandées '
                                   f'(attendu entre 1 s et le double)')
    elif rms < SMOKE_MUSIC_MIN_RMS:
        out.update(ok=False, error=f'audio SILENCIEUX (niveau efficace {rms:.5f})')
    return out


#: Le texte du smoke des DONNÉES PERSONNELLES (2026-10-28) : une phrase française et une anglaise,
#: chacune avec une personne et une adresse électronique — ce qu'un détecteur multilingue doit
#: voir au minimum. Garde-fou contre l'absurde, pas un critère de qualité : la mesure est la
#: campagne d'évaluation (`WAMA_QUALITE`).
SMOKE_PII_TEXT = ("Bonjour, je suis Marie Dubois, joignable à marie.dubois@exemple.fr. "
                  "Hello, I am John Smith and my email is john.smith@example.com.")
SMOKE_PII_EXPECTED = ('Marie Dubois', 'marie.dubois@exemple.fr', 'John Smith',
                      'john.smith@example.com')


def _smoke_pii(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis détection sur un texte connu : des passages DANS le texte, au vocabulaire
    commun, qui couvrent au moins la moitié des données personnelles qu'il contient."""
    import tempfile
    from unittest import mock

    from wama.common.privacy.entities import ENTITY_TYPES
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'detect_entities')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            # CPU, comme les autres smokes : le rôle ne dispute jamais le GPU au worker.
            with mock.patch('torch.cuda.is_available', return_value=False), \
                    mock.patch('wama.common.utils.onnx_utils.onnx_providers',
                               lambda *a, **k: ['CPUExecutionProvider']):
                if not backend.load(model_id_of(model_key)):
                    return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
                found = backend.detect_entities(model_id=model_id_of(model_key),
                                                text=SMOKE_PII_TEXT, language='fr')
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    bad = [f for f in found or [] if not (0 <= f.get('start', -1) < f.get('end', -1)
                                          <= len(SMOKE_PII_TEXT))
           or f.get('entity') not in ENTITY_TYPES]
    if bad:
        return {'ran': True, 'ok': False, 'seconds': seconds,
                'error': f'passages hors du texte ou hors vocabulaire : {bad[:3]}'}
    spans = [SMOKE_PII_TEXT[f['start']:f['end']] for f in found]
    covered = [e for e in SMOKE_PII_EXPECTED if any(e in s or s in e and len(s) > 3
                                                     for s in spans)]
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'found': len(found),
           'covered': covered}
    if len(covered) * 2 < len(SMOKE_PII_EXPECTED):
        out.update(ok=False, error=f'{len(covered)}/{len(SMOKE_PII_EXPECTED)} données '
                                   f'personnelles du texte connu retrouvées')
    return out


def _smoke_language(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis la langue d'un extrait de parole réelle (celui du smoke de PAROLE) : un code
    ISO 639-1, une probabilité dans [0, 1], et la langue que le corpus DÉCLARE quand il en déclare
    une (2026-11-06, contrat `language-identification`)."""
    import tempfile
    from unittest import mock

    from wama.common.utils.audio_decode import decode_window
    clip, _reference = smoke_speech_clip()
    if clip is None:
        return {'ran': False, 'reason': 'aucun corpus de parole versé en médiathèque système '
                                        '(manage.py asr_eval_corpus)'}
    declared = (clip.attributes or {}).get('language')
    declared = declared if isinstance(declared, str) else None
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'identify_language')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            audio, _rate = decode_window(clip.file.path, backend.sample_rate, SMOKE_SPEECH_START,
                                         SMOKE_SPEECH_SECONDS)
            # CPU, comme les autres smokes : le rôle ne dispute jamais le GPU au worker.
            with mock.patch('torch.cuda.is_available', return_value=False):
                if not backend.load(model_id_of(model_key)):
                    return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
                language, probability = backend.identify_language(audio=audio)
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'language': language,
           'probability': probability}
    if not (isinstance(language, str) and len(language) == 2 and 0.0 <= float(probability) <= 1.0):
        out.update(ok=False, error=f'réponse hors contrat : ({language!r}, {probability!r})')
    elif declared and language != declared.split('-')[0].lower():
        out.update(ok=False, error=f'langue « {language} » pour un extrait déclaré « {declared} »')
    return out


def _smoke_end_of_turn(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis l'avis sur un extrait de parole réelle (celui du smoke de PAROLE) : une
    probabilité finie dans [0, 1] (2026-11-08, contrat `end-of-turn`). Le seuil qui en fait un
    verdict n'est pas au contrat : l'essai ne juge pas l'avis, seulement sa forme."""
    import math
    import tempfile
    from unittest import mock

    from wama.common.utils.audio_decode import decode_window
    clip, _reference = smoke_speech_clip()
    if clip is None:
        return {'ran': False, 'reason': 'aucun corpus de parole versé en médiathèque système '
                                        '(manage.py asr_eval_corpus)'}
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'turn_end_probability')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            audio, _rate = decode_window(clip.file.path, backend.sample_rate, SMOKE_SPEECH_START,
                                         SMOKE_SPEECH_SECONDS)
            # CPU, comme les autres smokes : le rôle ne dispute jamais le GPU au worker.
            with mock.patch('torch.cuda.is_available', return_value=False), \
                    mock.patch('wama.common.utils.onnx_utils.onnx_providers',
                               lambda *a, **k: ['CPUExecutionProvider']):
                if not backend.load(model_id_of(model_key)):
                    return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
                probability = backend.turn_end_probability(audio=audio)
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'probability': probability}
    if not (isinstance(probability, float) and math.isfinite(probability)
            and 0.0 <= probability <= 1.0):
        out.update(ok=False, error=f'réponse hors contrat : {probability!r}')
    return out


def smoke_face_image():
    """Le chemin d'un PORTRAIT de la médiathèque système (`SystemAsset`, type `avatar` — ceux de
    l'avatarizer), ou None si aucun n'est versé : le visage du smoke des REPÈRES."""
    from wama.media_library.models import SystemAsset
    portrait = next((a for a in SystemAsset.objects.filter(asset_type='avatar').order_by('name')
                     if a.file), None)
    return portrait.file.path if portrait else None


def _smoke_face_landmarks(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis les repères d'un portrait et d'une image unie : au moins un visage sur le
    portrait, chacun en (N, 3) dans le cadre de l'image ; aucun sur l'image unie (2026-11-08,
    contrat `face-landmark-detection`)."""
    import tempfile

    import numpy as np
    from PIL import Image
    path = smoke_face_image()
    if path is None:
        return {'ran': False, 'reason': 'aucun portrait versé en médiathèque système (type avatar)'}
    with Image.open(path) as source:
        portrait = np.asarray(source.convert('RGB'))
    blank = np.full_like(portrait, 128)
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'detect_face_landmarks')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            if not backend.load(model_id_of(model_key)):
                return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
            faces = backend.detect_face_landmarks(image=portrait)
            none = backend.detect_face_landmarks(image=blank)
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    h, w = portrait.shape[:2]
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'faces': len(faces or []),
           'landmarks': [len(f) for f in faces or []]}
    shaped = all(isinstance(f, np.ndarray) and f.ndim == 2 and f.shape[1] == 3 and len(f)
                 for f in faces or [])
    if not isinstance(faces, list) or not shaped:
        out.update(ok=False, error=f'réponse hors contrat : {type(faces).__name__}')
    elif not faces:
        out.update(ok=False, error='aucun visage sur le portrait')
    elif not all((f[:, 0] >= 0).all() and (f[:, 0] <= w).all() and (f[:, 1] >= 0).all()
                 and (f[:, 1] <= h).all() for f in faces):
        out.update(ok=False, error='des repères hors du cadre (coordonnées non ramenées en pixels ?)')
    elif none:
        out.update(ok=False, error=f'{len(none)} visage(s) sur une image unie')
    return out


def _smoke_face_analysis(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis un portrait : une réponse aux clés du contrat, ou None si le modèle n'y voit
    pas de visage — ce qui ne se confond pas avec une erreur (2026-11-09, contrat `face-analysis`)."""
    import tempfile

    import numpy as np
    from PIL import Image
    path = smoke_face_image()
    if path is None:
        return {'ran': False, 'reason': 'aucun portrait versé en médiathèque système (type avatar)'}
    with Image.open(path) as source:
        portrait = np.asarray(source.convert('RGB'))[:, :, ::-1].copy()     # le contrat lit du BGR
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'analyze_face')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            if not backend.load(model_id_of(model_key)):
                return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
            answer = backend.analyze_face(image=portrait)
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    out = {'ran': True, 'ok': True, 'seconds': round(time.time() - started, 1),
           'attributes': sorted(answer or [])}
    if answer is not None and (not isinstance(answer, dict)
                               or not set(answer) <= {'emotions', 'age', 'gender', 'gender_confidence'}):
        out.update(ok=False, error=f'réponse hors contrat : {answer!r:.120}')
    elif not answer:
        out.update(ok=False, error='aucun attribut lu sur le portrait')
    return out


#: La page que redresse le smoke d'ORIENTATION : des lignes de texte, tournée de ce quart de tour.
SMOKE_ORIENTATION_TURN = 90


def smoke_orientation_page():
    """(page droite, page tournée de `SMOKE_ORIENTATION_TURN`) — des lignes de texte dessinées, la
    forme d'une page de document. Mesuré le 2026-11-07 avec le classifieur de docTR : les quatre
    quarts de tour redressés, confiance ≥ 0,98."""
    from PIL import Image, ImageDraw, ImageFont
    page = Image.new('RGB', (900, 1200), 'white')
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 36)
    except OSError:
        font = ImageFont.load_default(size=36)
    for i in range(14):
        draw.text((60, 60 + i * 75), f"Ligne {i + 1} : le reader redresse la page.", fill='black',
                  font=font)
    return page, page.rotate(SMOKE_ORIENTATION_TURN, expand=True)


def _smoke_orientation(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis l'angle d'une page de texte tournée d'un quart de tour : un angle du
    contrat (0, 90, 180, 270), une confiance dans [0, 1], et la page REDRESSÉE par cet angle —
    comparée pixel à pixel à la page droite (2026-11-07, contrat `page-orientation`)."""
    import tempfile

    import numpy as np
    upright, turned = smoke_orientation_page()
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'page_orientation')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            if not backend.load(model_id_of(model_key)):
                return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
            angle, confidence = backend.page_orientation(image=np.asarray(turned))
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'angle': angle, 'confidence': confidence}
    if angle not in (0, 90, 180, 270) or not 0.0 <= float(confidence) <= 1.0:
        out.update(ok=False, error=f'réponse hors contrat : ({angle!r}, {confidence!r})')
        return out
    reference = np.asarray(upright.convert('L'), dtype=np.int16)
    back = np.asarray(turned.rotate(angle, expand=True).convert('L'), dtype=np.int16)
    if back.shape != reference.shape or float(np.abs(back - reference).mean()) >= 1.0:
        out.update(ok=False, error=f'angle {angle}° : la page tournée de {SMOKE_ORIENTATION_TURN}° '
                                   'ne revient pas droite')
    return out


def _smoke_quality_metric(code: str, *, module: str, model_key: str, out_dir: Path) -> dict:
    """Chargement, puis la note d'une image face à ELLE-MÊME et face à une version bruitée : deux
    nombres finis, un sens déclaré du vocabulaire des mesures (`lower` / `higher`), et l'image
    intacte MIEUX notée que la bruitée dans ce sens (2026-11-07, contrat `quality-metric`)."""
    import math
    import tempfile

    import numpy as np
    rng = np.random.default_rng(0)
    reference = rng.integers(0, 255, (128, 128, 3), dtype=np.uint8)
    noisy = np.clip(reference.astype(np.int16) + rng.integers(-60, 60, reference.shape),
                    0, 255).astype(np.uint8)
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            backend = _proposed_backend(code, module, tmp, 'score')
            if not type(backend).is_available():
                return {'ran': False, 'reason': 'is_available() = False (paquets absents ?)'}
            if not backend.load(model_id_of(model_key)):
                return {'ran': True, 'ok': False, 'error': 'load() a rendu False'}
            same = backend.score(image=reference, reference=reference)
            degraded = backend.score(image=noisy, reference=reference)
            direction = getattr(backend, 'direction', '')
            backend.unload()
        except Exception as e:
            return {'ran': True, 'ok': False, 'error': f'{type(e).__name__}: {e}',
                    'seconds': round(time.time() - started, 1)}
    seconds = round(time.time() - started, 1)
    out = {'ran': True, 'ok': True, 'seconds': seconds, 'same': same, 'degraded': degraded,
           'direction': direction}
    if direction not in ('lower', 'higher') or not all(
            isinstance(v, float) and math.isfinite(v) for v in (same, degraded)):
        out.update(ok=False, error=f'réponse hors contrat : sens {direction!r}, notes '
                                   f'({same!r}, {degraded!r})')
    elif (same >= degraded) if direction == 'lower' else (same <= degraded):
        out.update(ok=False, error=f"l'image intacte n'est pas mieux notée que la bruitée "
                                   f"({same:.4f} / {degraded:.4f}, sens {direction})")
    return out


#: Un essai par CONTRAT — un contrat sans entrée le dit (`smoke`).
SMOKES = {'ImageGenerationBackend': _smoke_image, 'SpeechToTextBackend': _smoke_speech,
          'ScoreExtractionBackend': _smoke_score, 'PIIDetectionBackend': _smoke_pii,
          'MusicGenerationBackend': _smoke_music,
          'LanguageIdentificationBackend': _smoke_language,
          'EndOfTurnBackend': _smoke_end_of_turn,
          'PageOrientationBackend': _smoke_orientation,
          'FaceLandmarkDetectionBackend': _smoke_face_landmarks,
          'FaceAnalysisBackend': _smoke_face_analysis,
          'QualityMetricBackend': _smoke_quality_metric}


# ── Le geste : lister, valider (ÉCRIRE), rejeter ─────────────────────────────────────────────

def pending() -> list:
    """Propositions de backend en attente : `outputs/backend_*.json` au statut PENDING."""
    items = []
    for f in sorted(outputs_dir().glob('backend_*.json'), reverse=True):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if data.get('status') == 'PENDING_HUMAN_VALIDATION' and data.get('code'):
            items.append({'file': f.name, **{k: data.get(k) for k in (
                'model_key', 'module', 'engine', 'contract', 'checks', 'resolution', 'smoke',
                'model')}})
    return items


def refusals(name: str) -> list:
    """Ce que « Valider » refuserait de ce backend proposé MAINTENANT — les contrôles qu'`apply`
    refait, sans rien écrire (le pendant de `proposals.plan` pour un manifeste, 2026-11-08)."""
    _, data = _load(name)
    module = data.get('module') or ''
    if not MODULE_NAME.match(module):
        return [f'nom de module refusé : {module!r}']
    if (backends_dir() / f'{module}.py').exists():
        return [f'{module}.py existe déjà — jamais écrasé']
    return check_source(data.get('code') or '', engine=data.get('engine') or '',
                        model_id=model_id_of(data.get('model_key') or ''),
                        contract=tuple(data.get('contract') or DEFAULT_CONTRACT))['errors']


def _load(name: str) -> tuple:
    f = outputs_dir() / Path(name).name          # jamais un chemin hors d'outputs/
    if not f.is_file() or not f.name.startswith('backend_'):
        raise FileNotFoundError(name)
    return f, json.loads(f.read_text(encoding='utf-8'))


def apply(name: str, user=None) -> dict:
    """ÉCRIT le backend validé dans `wama/common/backends/<module>.py` — contrôles REFAITS,
    jamais par-dessus un module existant. L'inventaire le découvre seul (AST, `ENGINE`)."""
    f, data = _load(name)
    errors = refusals(name)
    if errors:
        return {'applied': False, 'errors': errors}
    module, code = data['module'], data.get('code') or ''
    target = backends_dir() / f'{module}.py'
    try:
        written = str(target.relative_to(settings.BASE_DIR))
    except ValueError:
        written = str(target)
    target.write_text(code, encoding='utf-8')
    # Le vivier de résolution est mémorisé une minute : le backend écrit doit y entrer TOUT DE
    # SUITE, comme après une installation de librairie.
    from wama.common.backends.manager import invalidate_engine_cache
    invalidate_engine_cache()
    data.update(status='APPLIED', applied_by=getattr(user, 'username', None),
                applied_at=time.strftime('%Y-%m-%dT%H:%M:%S'), written=written)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.warning("[backend_proposals] %s écrit par %s (proposition %s) — à relire et commiter",
                   target.name, getattr(user, 'username', '?'), f.name)
    return {'applied': True, 'written': data['written'], 'model_key': data.get('model_key') or '',
            'note': "rechargez les workers pour qu'ils importent le nouveau backend"}


def reject(name: str, user=None) -> bool:
    f, data = _load(name)
    if data.get('status') != 'PENDING_HUMAN_VALIDATION':
        return False
    data.update(status='REJECTED', rejected_by=getattr(user, 'username', None))
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return True
