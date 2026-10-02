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


def model_id_of(model_key: str) -> str:
    """Identifiant que `SUPPORTED_MODELS` doit déclarer — la règle de `backend_for_model`."""
    return (model_key or '').rsplit(':', 1)[-1]


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
    root = Path(settings.BACKEND_VENDOR_DIR) / engine
    return {p.parent.name for base in (root, root / 'src') if base.is_dir()
            for p in base.glob('*/__init__.py')}


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


#: Un essai par CONTRAT — un contrat sans entrée le dit (`smoke`).
SMOKES = {'ImageGenerationBackend': _smoke_image, 'SpeechToTextBackend': _smoke_speech}


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


def _load(name: str) -> tuple:
    f = outputs_dir() / Path(name).name          # jamais un chemin hors d'outputs/
    if not f.is_file() or not f.name.startswith('backend_'):
        raise FileNotFoundError(name)
    return f, json.loads(f.read_text(encoding='utf-8'))


def apply(name: str, user=None) -> dict:
    """ÉCRIT le backend validé dans `wama/common/backends/<module>.py` — contrôles REFAITS,
    jamais par-dessus un module existant. L'inventaire le découvre seul (AST, `ENGINE`)."""
    f, data = _load(name)
    module, code = data.get('module') or '', data.get('code') or ''
    if not MODULE_NAME.match(module):
        return {'applied': False, 'errors': [f'nom de module refusé : {module!r}']}
    target = backends_dir() / f'{module}.py'
    if target.exists():
        return {'applied': False, 'errors': [f'{target.name} existe déjà — jamais écrasé']}
    contract = tuple(data.get('contract') or DEFAULT_CONTRACT)
    checks = check_source(code, engine=data.get('engine') or '',
                          model_id=model_id_of(data.get('model_key') or ''), contract=contract)
    if not checks['ok']:
        return {'applied': False, 'errors': checks['errors']}
    try:
        written = str(target.relative_to(settings.BASE_DIR))
    except ValueError:
        written = str(target)
    target.write_text(code, encoding='utf-8')
    data.update(status='APPLIED', applied_by=getattr(user, 'username', None),
                applied_at=time.strftime('%Y-%m-%dT%H:%M:%S'), written=written)
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.warning("[backend_proposals] %s écrit par %s (proposition %s) — à relire et commiter",
                   target.name, getattr(user, 'username', '?'), f.name)
    return {'applied': True, 'written': data['written'],
            'note': "rechargez les workers pour qu'ils importent le nouveau backend"}


def reject(name: str, user=None) -> bool:
    f, data = _load(name)
    if data.get('status') != 'PENDING_HUMAN_VALIDATION':
        return False
    data.update(status='REJECTED', rejected_by=getattr(user, 'username', None))
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return True
