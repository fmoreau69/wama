"""
Briques COMMUNES des pilotes de rôle (librarian, scout, integrator) — extraites de
run_librarian.py le 2026-08-27 au moment d'écrire les deux rôles frères (zéro duplication,
même règle que wama/common/ côté produit).

Tout est BORNÉ (leçons wama-dev-ai) : un appel Ollama one-shot, sorties dans outputs/ avec
PENDING_HUMAN_VALIDATION, jamais d'auto-application.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = Path(__file__).resolve().parent / 'outputs'
PROMPTS = Path(__file__).resolve().parent / 'prompts'

# Ollama (gateway) SANS proxy — le proxy UGE avalerait 172.x ; le web AVEC proxy (défaut env).
_OPENER_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ollama_host():
    """Adresse d'Ollama — DÉLÈGUE à la brique commune (2026-09-07).

    Ce fichier en portait une copie. Elle n'était pas « une variante » : la brique commune
    `common/utils/ollama_host.py` a justement été EXTRAITE de `run_librarian.py` le
    2026-08-02 comme « seule implémentation correcte du repo » — et sa source ne l'a jamais
    adoptée. *Une brique qu'on extrait sans que son origine l'adopte laisse deux vérités
    derrière elle.*

    Les deux résolvaient la même adresse aujourd'hui (mesuré : `http://172.21.96.1:11434`
    des deux côtés), mais la copie était en retard sur TROIS points, tous latents :
      • elle lisait `os.environ` BRUT au lieu du registre `external_sources` — le jour où
        l'adresse est posée par réglage Django et non par l'environnement, elle vise encore
        la boucle locale, avec le symptôme trompeur que la brique commune documente
        (« Ollama ne répond pas » alors qu'il tourne) ;
      • son `subprocess` n'avait AUCUN timeout — un `ip route` qui pend gèle le rôle ;
      • passerelle introuvable = retour silencieux sur la boucle locale, sans avertissement.

    Import PARESSEUX : `role_utils` reste importable sans Django, et Django n'est exigé qu'à
    l'appel — les 5 rôles font tous `django.setup()` avant d'importer ce module (vérifié).
    Pas de repli « si Django manque » : ce serait exactement le second chemin qu'on retire.
    """
    from wama.common.utils.ollama_host import ollama_base
    return ollama_base()


def model_vocabularies() -> str:
    """Vocabulaires FERMÉS d'un manifeste `model`, SERVIS par le code (l'agent choisit dedans,
    il n'invente pas) — accesseur UNIQUE des rôles qui écrivent un manifeste `model`.

    Vivait dans `run_model_manifest.py` (`vocabulaires`). Remonté ici le 2026-09-30 : le rôle
    frère `scout` écrit le MÊME manifeste et ne recevait AUCUN de ces vocabulaires. Vécu au
    1er passage réel des avatars (qwen3.8, LongCat-Video-Avatar-1.5) : `inputs_required
    ['audio']`, `inputs_optional ['image']` — manifeste invalide, exactement le défaut que
    `e750fa74` avait corrigé pour le seul rôle `model`. *Une garde se pose avec ses jumeaux.*

    Import PARESSEUX, comme `ollama_host` : Django n'est exigé qu'à l'appel.
    """
    from wama.common.backends.manager import known_engines
    from wama.common.utils.app_modes import INPUT_TYPES
    from wama.common.utils.model_capabilities import CANONICAL_CAPABILITIES
    from wama.model_manager.models import ModelSource, ModelTask, ModelType

    engines = sorted(known_engines())
    return (
        f"capabilities.task — valeurs autorisées : {', '.join(sorted(ModelTask.values))}\n"
        # Servi depuis le 2026-09-29 : sans lui, gpt-oss-120b a déclaré `seed, steps, cfg`
        # (des réglages) comme entrées d'un modèle texte→image.
        f"capabilities.inputs_required / inputs_optional — ids d'ENTRÉES (données fournies, "
        f"jamais des réglages) : {', '.join(sorted(INPUT_TYPES))}\n"
        f"identity.model_type — valeurs autorisées : {', '.join(sorted(ModelType.values))}\n"
        f"identity.source — valeurs autorisées : {', '.join(sorted(ModelSource.values))}\n"
        f"clés canoniques de `capabilities` : {', '.join(sorted(CANONICAL_CAPABILITIES))}\n"
        f"composition.runtime.engine — moteurs DÉJÀ SERVIS par un backend : "
        f"{', '.join(engines) or '(aucun)'}\n"
    )


def diffusers_class_known(class_name) -> bool:
    """Vrai si `class_name` est exporté par le `diffusers` INSTALLÉ.

    `dir()` d'un module paresseux (`_LazyModule`) liste ses noms SANS importer les sous-modules :
    `hasattr` les importerait (mesuré : TensorFlow et xformers chargés, plusieurs minutes).
    """
    if not class_name:
        return False
    import diffusers
    return str(class_name) in dir(diffusers)


def diffusers_pipeline_class(hf_id):
    """(`_class_name` du `model_index.json` racine, ou None ; raison lisible) — fait MÉCANIQUE."""
    import json as _json
    from huggingface_hub import hf_hub_download
    try:
        path = hf_hub_download(hf_id, 'model_index.json')
    except Exception:
        return None, "aucun model_index.json à la racine du dépôt"
    with open(path, encoding='utf-8') as f:
        class_name = (_json.load(f) or {}).get('_class_name')
    if not class_name:
        return None, "model_index.json sans _class_name"
    return class_name, f"model_index.json nomme {class_name!r}"


def transformers_class_known(class_name) -> bool:
    """Vrai si `class_name` est exporté par le `transformers` INSTALLÉ (même lecture paresseuse
    que `diffusers_class_known` : `dir()` d'un `_LazyModule` n'importe aucun sous-module)."""
    if not class_name:
        return False
    import transformers
    return str(class_name) in dir(transformers)


def transformers_architectures(hf_id):
    """(`architectures` du `config.json` racine, ou [] ; raison lisible) — fait MÉCANIQUE.

    `auto_map` y est signalé : un modèle à code DISTANT ne s'exécute pas par les classes de
    `transformers`, mais par le moteur `transformers-remote-code`."""
    import json as _json
    from huggingface_hub import hf_hub_download
    try:
        path = hf_hub_download(hf_id, 'config.json')
    except Exception:
        return [], "aucun config.json à la racine du dépôt"
    with open(path, encoding='utf-8') as f:
        config = _json.load(f) or {}
    architectures = [a for a in (config.get('architectures') or []) if a]
    if not architectures:
        return [], "config.json sans architectures"
    reason = f"config.json nomme {architectures}"
    if config.get('auto_map'):
        reason += f" ({REMOTE_CODE_MARK})"
    return architectures, reason


#: Marque, dans la raison de `transformers_architectures`, d'un dépôt qui déclare son code.
REMOTE_CODE_MARK = 'code DISTANT déclaré par auto_map'
#: Le moteur d'un modèle dont `transformers` exécute le code EMBARQUÉ (`trust_remote_code`).
REMOTE_CODE_ENGINE = 'transformers-remote-code'


#: Moteurs dont le dépôt PROUVE l'exécutabilité : lecteur du fait, test contre la lib installée,
#: libellé de l'échec. Un moteur absent de cette table n'est pas jugé ici — le fait manque.
ENGINE_PROOFS = {
    'diffusers': (diffusers_pipeline_class, diffusers_class_known, 'classe inconnue de diffusers'),
    'transformers': (transformers_architectures, transformers_class_known,
                     'aucune de ces classes dans le transformers installé'),
}


def repo_files(hf_id) -> list:
    """Chemins des fichiers du dépôt HF ([] s'il est illisible — réseau, dépôt restreint)."""
    try:
        from huggingface_hub import HfApi
        return list(HfApi().list_repo_files(hf_id))
    except Exception:
        return []


def signal_weight_formats(hf_id, concerns, lister=repo_files):
    """Signale les FORMATS de poids du dépôt quand il en porte plusieurs.

    Vécu le 2026-09-30 (LinTO FastConformer) : le rôle a proposé `transformers` sur la foi d'un
    `config.json`, alors que le `.nemo` du MÊME dépôt s'exécute par NeMo. Le rôle ne voyait pas
    l'alternative ; le validateur humain non plus. Les extensions sont celles que la prospection
    reconnaît déjà comme des poids (`prospector._WEIGHT_EXTS`) — aucune liste de plus."""
    from wama.model_manager.services.prospector import _WEIGHT_EXTS
    by_ext = {}
    for path in lister(hf_id):
        ext = next((e for e in _WEIGHT_EXTS if path.lower().endswith(e)), None)
        if ext:
            by_ext.setdefault(ext, []).append(path)
    if len(by_ext) > 1:
        detail = ' ; '.join(f"{ext} ({', '.join(sorted(paths)[:2])}"
                            f"{', …' if len(paths) > 2 else ''})"
                            for ext, paths in sorted(by_ext.items()))
        concerns.append(f"le dépôt porte PLUSIEURS formats de poids — {detail} : le moteur doit "
                        f"être celui du format retenu")
    return by_ext


def enforce_identity(manifest, key, hf_id, concerns, platform_ref=None):
    """La clé et l'identité du manifeste sont celles du modèle DEMANDÉ — jamais celles que le LLM
    a écrites.

    Vécu le 2026-10-01 (gpt-oss-120b sur Albert, `--catalog huggingface:kyutai/stt-1b-en_fr-trfs`) :
    le LLM a rendu la clé `huggingface:kyutai/stt-2.6b-en`, un AUTRE modèle, non installé. Le
    manifeste était « VALIDE », et le contrôle du moteur a lu le `config.json` de ce modèle-là :
    il a RETIRÉ `transformers`, alors que le vrai `config.json` nomme une classe que le
    transformers installé possède. *Une identité fausse fausse tous les faits mécaniques qui en
    dépendent.* Elle est donc imposée, et la correction est DITE : le reste du manifeste a pu
    décrire l'autre modèle, il est à relire."""
    body = manifest.setdefault('body', {})
    identity = body.setdefault('identity', {})
    ref = platform_ref or key
    wrong = [f"{name} {value!r}" for name, value, expected in (
        ('clé', manifest.get('key'), key), ('hf_id', identity.get('hf_id'), hf_id),
        ('platform_ref', identity.get('platform_ref'), ref)) if value and value != expected]
    manifest['key'] = key
    identity['hf_id'] = hf_id
    identity['platform_ref'] = ref
    if wrong:
        # Le NOM suit l'identité fautive (« stt-2.6b-en » pour stt-1b-en_fr-trfs, même run) :
        # il redevient celui du dépôt demandé.
        manifest['name'] = hf_id.rsplit('/', 1)[-1]
        concerns.append(f"identité CORRIGÉE (fait mécanique) : le LLM avait écrit {', '.join(wrong)} "
                        f"pour {key!r} — le manifeste a pu décrire un autre modèle, à relire")
    return manifest


def card_languages(hf_id, snapshot=None) -> list:
    """Langues DÉCLARÉES par la fiche du modèle (en-tête YAML `language`) ; [] si la fiche n'en
    dit rien. Lue dans le snapshot installé, sinon sur le Hub. La traduction en vocabulaire WAMA
    (codes courts, `multilingual` → `['*']`) est celle de la prospection, `card_facts` : un
    manifeste porte les mêmes faits qu'un candidat prospecté."""
    from huggingface_hub.repocard import metadata_load
    from wama.model_manager.services.prospector import card_facts
    try:
        readme = Path(snapshot) / 'README.md' if snapshot else None
        if readme is None or not readme.is_file():
            from huggingface_hub import hf_hub_download
            readme = hf_hub_download(hf_id, 'README.md')
        meta = metadata_load(readme) or {}
    except Exception:
        return []
    return card_facts('', card_data=meta)['capabilities'].get('languages', [])


def enforce_language_facts(manifest, languages, concerns):
    """Les langues du modèle sont celles que sa FICHE déclare, pas celles que le LLM a lues ailleurs.

    Vécu le 2026-10-01 (Kyutai) : la fiche, partagée par deux modèles, décrit aussi un modèle
    anglais seul ; le LLM a écrit `['en']` pour un modèle `['en', 'fr']`. Au geste « Valider »,
    ce champ VIDE au catalogue aurait été comblé avec la valeur fausse."""
    if not languages:
        return manifest
    capabilities = manifest.setdefault('body', {}).setdefault('capabilities', {})
    current = capabilities.get('languages') or []
    if sorted(set(current)) != sorted(set(languages)):
        capabilities['languages'] = list(languages)
        concerns.append(f"langues {'CORRIGÉES' if current else 'POSÉES'} (fait mécanique, fiche du "
                        f"modèle) : {list(languages)}" + (f" au lieu de {current}" if current else ''))
    return manifest


def format_engines() -> dict:
    """Formats de poids qui PROUVENT un moteur — la table vit au substrat
    (`prospector.WEIGHT_FORMAT_ENGINES`), partagée avec la dérivation du balayage.
    Vécu le 2026-10-01 (LinTO FastConformer) : le dépôt porte un `.nemo`, le moteur `transformers`
    proposé est retiré à juste titre, mais AUCUN moteur n'était proposé alors que le backend NeMo
    existe. Le 2026-10-06 (Swin2SR) : le scout ne proposait aucun moteur pour un `.onnx`."""
    from wama.model_manager.services.prospector import WEIGHT_FORMAT_ENGINES
    return WEIGHT_FORMAT_ENGINES

#: Dossier où les exports ONNX d'Optimum / transformers.js rangent leurs VARIANTES : `model.onnx`
#: est la pleine précision, les suffixes (`_fp16`, `_q4`, `_int8`, `_quantized`…) des
#: quantifications. Convention de ces deux outils, pas une devinette sur un nom de fichier.
ONNX_EXPORT_DIR = 'onnx/'
ONNX_REFERENCE_VARIANT = 'onnx/model.onnx'


def _engine_from_format(manifest, by_ext, concerns):
    """Pose le moteur que le FORMAT des poids prouve, s'il n'y en a aucun et qu'un backend le sert."""
    from wama.common.backends.manager import known_engines
    for ext, engine in format_engines().items():
        if ext in by_ext and engine in known_engines():
            composition = manifest.setdefault('body', {}).setdefault('composition', {})
            composition.setdefault('runtime', {})['engine'] = engine
            concerns.append(f"engine {engine!r} PROPOSÉ (fait mécanique) : le dépôt porte "
                            f"{sorted(by_ext[ext])[0]} et un backend sert le moteur {engine!r} — "
                            f"qu'il serve CE modèle reste à vérifier")
            return


def enforce_component_facts(manifest, hf_id, concerns, lister=repo_files):
    """Pose l'ANATOMIE d'un modèle SIMPLE quand le manifeste n'en déclare aucune.

    Vécu le 2026-10-01 (FrWhisper, Kyutai, LinTO) : le rôle `backend` exige
    `composition.components`, et un modèle d'un seul tenant n'en recevait jamais — l'anatomie
    n'avait été pensée que pour les modèles COMPOSÉS. Le fait est mécanique : les poids du dépôt
    sont d'UN format → un composant `model` qui les désigne (le fichier, ou le motif des fichiers
    découpés `x-00001-of-0000N`). Plusieurs formats → celui du moteur prouvé par le format
    (`format_engines`), sinon RIEN : choisir serait deviner, et c'est dit."""
    from wama.model_manager.services.prospector import _WEIGHT_EXTS
    body = manifest.setdefault('body', {})
    composition = body.get('composition') or {}
    if composition.get('components'):
        return manifest
    by_ext = {}
    paths = list(lister(hf_id))
    for path in paths:
        ext = next((e for e in _WEIGHT_EXTS if path.lower().endswith(e)), None)
        if ext and '/' not in path:                      # les poids du modèle, à la racine
            by_ext.setdefault(ext, []).append(path)
    if not by_ext and ONNX_REFERENCE_VARIANT in paths:
        # Export Optimum / transformers.js (2026-10-06, Swin2SR) : aucun poids à la racine, les
        # variantes sous `onnx/`. Sans composant, l'installation tirait les HUIT (210 Mo pour
        # 51 utiles) ; la pleine précision est la référence, les autres restent un choix.
        others = sorted(p for p in paths if p.startswith(ONNX_EXPORT_DIR) and p.endswith('.onnx')
                        and p != ONNX_REFERENCE_VARIANT)
        body.setdefault('composition', composition)['components'] = [
            {'role': 'model', 'pattern': ONNX_REFERENCE_VARIANT, 'format': 'onnx'}]
        concerns.append(f"anatomie POSÉE (fait mécanique, export ONNX) : un composant `model` = "
                        f"{ONNX_REFERENCE_VARIANT}" + (f" ; variantes non retenues : {others}"
                                                       if others else ''))
        return manifest
    engine = (composition.get('runtime') or {}).get('engine')
    proven = [ext for ext, eng in format_engines().items() if eng == engine and ext in by_ext]
    if len(by_ext) == 1:
        ext = next(iter(by_ext))
    elif proven:
        ext = proven[0]
    else:
        if by_ext:
            concerns.append(f"anatomie NON posée : poids en {len(by_ext)} formats "
                            f"({', '.join(sorted(by_ext))}) et aucun ne prouve le moteur")
        return manifest
    files = sorted(by_ext[ext])
    shard = re.match(r'^(.+)-\d{5}-of-\d{5}' + re.escape(ext) + '$', files[0])
    pattern = (files[0] if len(files) == 1 else f'{shard.group(1)}-*{ext}' if shard else f'*{ext}')
    body.setdefault('composition', composition)['components'] = [
        {'role': 'model', 'pattern': pattern, 'format': ext.lstrip('.')}]
    concerns.append(f"anatomie POSÉE (fait mécanique) : un composant `model` = {pattern}")
    return manifest


def adapter_parent(hf_id, loader=None):
    """`(dépôt parent, révision)` qu'un `config.json` racine nomme par `base_model_name_or_path`,
    ou `(None, None)` — un adaptateur ne s'exécute pas sans son parent."""
    import json as _json

    def _load():
        from huggingface_hub import hf_hub_download
        with open(hf_hub_download(hf_id, 'config.json'), encoding='utf-8') as f:
            return _json.load(f)
    try:
        config = (loader or _load)() or {}
    except Exception:
        return None, None
    parent = config.get('base_model_name_or_path') if isinstance(config, dict) else None
    if not isinstance(parent, str) or not _HF_REPO_ID.match(parent) or parent.lower() == hf_id.lower():
        return None, None
    return parent, config.get('base_model_revision')


def enforce_adapter_parent(manifest, hf_id, concerns, loader=None):
    """Ajoute le PARENT d'un adaptateur à l'anatomie — un composant `base` = son dépôt.

    Vécu le 2026-10-03 (SheetSage2) : le dépôt ne porte qu'un adaptateur ; son `config.json` nomme
    `base_model_name_or_path: m-a-p/MERT-v2-FullSong` (2,5 Go, chargé par le code du modèle).
    Le rôle rendait un seul composant `model` : le poids réel était sous-estimé et le parent
    jamais téléchargé par `request_install`. Fait mécanique : le fichier le dit, on le pose."""
    parent, revision = adapter_parent(hf_id, loader=loader)
    if not parent:
        return manifest
    body = manifest.setdefault('body', {})
    composition = body.get('composition') if isinstance(body.get('composition'), dict) else {}
    components = list(composition.get('components') or [])
    if any(isinstance(c, dict) and str(c.get('repo', '')).lower() == parent.lower()
           for c in components):
        return manifest
    roles = {c.get('role') for c in components if isinstance(c, dict)}
    role = 'base' if 'base' not in roles else 'base_model'
    components.append({'role': role, 'repo': parent})
    composition['components'] = components
    body['composition'] = composition
    concerns.append(f"parent d'adaptateur POSÉ (fait mécanique, config.json) : {role}={parent}"
                    + (f" @ {revision[:12]}" if isinstance(revision, str) and revision else ''))
    return manifest


def enforce_engine_facts(manifest, hf_id, concerns, reader=None, lister=repo_files):
    """Retire `composition.runtime.engine` quand le dépôt ne le PROUVE pas, et dit ce qu'il porte.

    Vécu le 2026-09-30 (qwen3.8, avatars) : LongCat-Video-Avatar-1.5 et SoulX-FlashHead portent
    un `model_index.json` et des fichiers `diffusion_pytorch_model.safetensors`, et le rôle a
    déclaré `diffusers` — alors que leur `_class_name` (absent, `WanModelAudioProject`) n'existe
    pas dans `diffusers`, et que sa PROPRE remarque disait « pas un pipeline diffusers standard ».
    La consigne alignée n'a rien changé au run suivant : *une consigne de prompt n'est pas un
    contrôle*. Un moteur faux ne grise pas le modèle (le backend existe) : il le rend proposable
    puis fait échouer le chargement. Retirer le moteur le laisse GRISÉ avec sa raison, ce qui est
    le comportement voulu tant qu'aucun backend ne l'exécute.
    Même défaut le même jour sur `transformers` (LinTO FastConformer, `ParakeetForRNNT` absente
    du transformers installé) : la preuve est désormais une TABLE par moteur (`ENGINE_PROOFS`).
    Un moteur qu'AUCUN backend ne sert (`known_engines`) n'est pas retiré — c'est peut-être le
    backend à écrire — mais il est DIT : le modèle restera grisé jusque-là.
    Les faits mécaniques priment sur le jugement du LLM, comme la licence ou la taille.
    `reader` remplace le lecteur du fait (tests) ; `lister`, l'inventaire du dépôt.
    """
    by_ext = signal_weight_formats(hf_id, concerns, lister=lister)
    runtime = (((manifest.get('body') or {}).get('composition') or {}).get('runtime') or {})
    engine = runtime.get('engine')
    if not engine:
        _engine_from_format(manifest, by_ext, concerns)
        return manifest
    proof = ENGINE_PROOFS.get(engine)
    if proof is None:
        from wama.common.backends.manager import known_engines
        if engine not in known_engines():
            concerns.append(f"engine {engine!r} servi par AUCUN backend — le modèle restera "
                            f"grisé jusqu'à ce qu'un backend le serve")
        return manifest
    read, known, failure = proof
    names, reason = (reader or read)(hf_id)
    names = [names] if isinstance(names, str) else list(names or [])
    if any(known(n) for n in names):
        return manifest
    if engine == 'transformers' and REMOTE_CODE_MARK in (reason or ''):
        # Le dépôt déclare son code (`auto_map`) : c'est `transformers` qui l'exécute, par
        # `trust_remote_code` — le moteur est PROUVÉ par le dépôt, pas retiré (2026-10-03,
        # SheetSage2 ; même moteur qu'Audio8). Que ce code tourne avec NOTRE transformers reste
        # à éprouver par le backend : c'est dit.
        runtime['engine'] = REMOTE_CODE_ENGINE
        concerns.append(f"engine 'transformers' → {REMOTE_CODE_ENGINE!r} (fait mécanique) : "
                        f"{reason} — compatibilité du code embarqué avec le transformers "
                        f"installé à éprouver par le backend")
        return manifest
    runtime.pop('engine', None)
    if not runtime:
        manifest['body']['composition'].pop('runtime', None)
    concerns.append(f"engine {engine!r} RETIRÉ (fait mécanique) : {reason}, "
                    f"{failure} — un backend dédié reste à écrire")
    _engine_from_format(manifest, by_ext, concerns)
    return manifest


#: Fichiers qui font d'un dépôt un PAQUET que pip sait installer (`pip install .`).
PACKAGING_FILES = ('pyproject.toml', 'setup.py', 'setup.cfg')


def vendor_engine_name(repo: str) -> str:
    """Nom de moteur dérivé du dépôt (`TMElyralab/MuseTalk` → `musetalk`) — la forme exigée par
    `vendor_spec_error` ; c'est aussi la clé du manifeste et le dossier sous le vendor."""
    name = re.sub(r'[^a-z0-9]+', '_', repo.rsplit('/', 1)[-1].lower()).strip('_')
    return name if re.match(r'^[a-z]', name) else f'engine_{name}'


def github_head_sha(repo: str, branch: str, fetcher=None) -> str:
    """SHA complet de la tête de `branch` — MESURÉ par l'API GitHub (source déclarée `github_api`)."""
    from wama.common.external_sources import base_url
    raw = (fetcher or fetch)(f"{base_url('github_api')}/repos/{repo}/commits/{branch}")
    return json.loads(raw)['sha']


def http_status(url, user_agent='wama-dev-ai'):
    """Code HTTP d'un `HEAD` (proxy d'environnement) — le statut seul, sans lire de corps."""
    import urllib.error
    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': user_agent})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


def pypi_published(dist_name: str, version: str = '', status_of=None):
    """Le paquet — à CETTE version si elle est donnée — est-il PUBLIÉ sur PyPI ?
    True / False (404) / None (non mesuré). Source déclarée `pypi`.

    Le NOM ne suffit pas (mesuré le 2026-09-30) : `ace-step` existe sur PyPI, mais en 0.1.0
    seulement — un ancien paquet ; la 1.5.0 que proposait le rôle y est introuvable. Et un `HEAD`
    plutôt qu'une lecture : le proxy coupait le JSON en cours de route (`IncompleteRead`) alors
    que PyPI avait répondu 200 — seul le statut compte.
    """
    from wama.common.external_sources import base_url
    if not dist_name:
        return False
    path = f"{dist_name}/{version}" if version else dist_name
    try:
        code = (status_of or http_status)(f"{base_url('pypi')}/pypi/{path}/json")
    except Exception:
        return None
    if code == 200:
        return True
    return False if code == 404 else None


def requirements_verdict(requirement_lines, installed=None) -> dict:
    """Exigences d'un dépôt confrontées au venv de RÉFÉRENCE — `{satisfied, conflicts, missing}`.

    Vendoriser le code ne règle pas ses dépendances : elles vivent dans le venv commun, qui fait
    référence (une lib s'y adapte, jamais l'inverse). Ce verdict dit, AVANT toute installation,
    ce que le moteur exigerait de déplacer — mesuré le 2026-09-30 sur ACE-Step, qui veut
    `transformers` 5 quand le venv porte 4.57. `installed` remplace la lecture du venv (tests).
    """
    import importlib.metadata as im

    from packaging.requirements import InvalidRequirement, Requirement

    def version_of(name):
        if installed is not None:
            return installed.get(name.lower().replace('_', '-'))
        try:
            return im.version(name)
        except im.PackageNotFoundError:
            return None

    # `pinned` ≠ `conflicts` : une épingle EXACTE d'amont (`torch==2.10.0`) dit la version que
    # l'auteur a testée, pas une incompatibilité — MuseTalk en épingle quatre (numpy, transformers,
    # tensorflow, diffusers) et tourne avec le venv (`setup_avatarizer.sh`, 2026-09-07). Seule une
    # BORNE non satisfaite (`transformers>=5`, `numpy<2`) est un conflit.
    verdict = {'satisfied': [], 'conflicts': [], 'pinned': [], 'missing': []}
    for raw in requirement_lines or []:
        line = raw.split('#', 1)[0].strip()
        if not line or line.startswith(('-', 'git+', 'http')):
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement:
            continue
        if req.marker is not None and not req.marker.evaluate({'extra': ''}):
            continue
        have = version_of(req.name)
        if have is None:
            verdict['missing'].append(str(req))
        elif req.specifier and not req.specifier.contains(have, prereleases=True):
            exact = all(spec.operator in ('==', '===') for spec in req.specifier)
            verdict['pinned' if exact else 'conflicts'].append(
                {'requirement': str(req), 'installed': have})
        else:
            verdict['satisfied'].append(req.name)
    return verdict


def repo_requirements(files: dict) -> list:
    """Lignes d'exigences d'un dépôt, depuis `requirements.txt` et `[project].dependencies`."""
    import tomllib
    lines = list((files.get('requirements.txt') or '').splitlines())
    try:
        project = tomllib.loads(files.get('pyproject.toml') or '').get('project') or {}
        lines += list(project.get('dependencies') or [])
    except tomllib.TOMLDecodeError:
        pass
    # Un dépôt déclare souvent la même exigence aux deux endroits (ACE-Step) : une seule fois.
    return list(dict.fromkeys(line.strip() for line in lines if line.strip()))


def complete_library_envelope(manifest, repo, notes):
    """Enveloppe d'un manifeste `library` : ses CONSTANTES posées mécaniquement.

    Une librairie est un asset transverse et public (`extract_library` écrit les mêmes valeurs).
    Mesuré le 2026-09-30 : sur 5 dépôts, le LLM a omis `name` deux fois, `world` et `visibility`
    une fois — trois manifestes refusés à la validation pour des champs que rien ne laisse au
    jugement. Un champ absent se pose ; un champ fourni n'est jamais écrasé.
    """
    defaults = {'manifest_kind': 'library', 'schema_version': '1.0', 'world': 'transverse',
                'visibility': 'public', 'projects': [],
                'name': repo.rsplit('/', 1)[-1]}
    filled = [k for k in defaults if manifest.get(k) in (None, '')]
    for key in filled:
        manifest[key] = defaults[key]
    if filled:
        notes.append(f"enveloppe complétée (constantes du kind) : {', '.join(filled)}")
    return manifest


def enforce_install_channel(manifest, repo, packaging, sha, notes, published=None):
    """Pose le CANAL d'installation d'après les FAITS du dépôt, jamais d'après le LLM.

    Route `library` (ROADMAP D-a, 2026-09-30) : pip est la norme ; un dépôt qui n'est pas un
    paquet PUBLIÉ sur PyPI ne s'installe pas par la route pip (elle exige `nom==version` sur
    PyPI) et se VENDORISE — dépôt épinglé au commit MESURÉ. Avant ce contrôle, le rôle écrivait
    `install.pip` pour MuseTalk ou TripoSR, et le manifeste mourait au verrou : la chaîne
    scout → install apportait manifeste et poids, jamais le moteur.
    ⚠ Un fichier de paquet ne SUFFIT pas (corrigé le même soir) : YuE et ACE-Step ont un
    `pyproject.toml` et ne sont pas publiés (`yue2-infer`, `acestep` : 404).
    `packaging` = fichiers de paquet trouvés à la racine ; `sha` = tête mesurée (ou None) ;
    `published` = publication PyPI du nom proposé (True / False / None = non mesurée).
    """
    body = manifest.setdefault('body', {})
    install = body.get('install') if isinstance(body.get('install'), dict) else {}
    if packaging and published is not False:
        if install.pop('vendor', None) is not None:
            notes.append(f"install.vendor RETIRÉ : le dépôt est un paquet ({', '.join(packaging)}) "
                         "— la norme est pip")
        if published is None:
            notes.append("publication PyPI NON mesurée : install.pip gardé, à vérifier à la main")
        body['install'] = install
        return manifest
    if packaging:
        notes.append(f"paquet ({', '.join(packaging)}) NON publié sur PyPI "
                     f"({install.get('pip')!r}) — la route pip le refuserait")
    if not sha:
        notes.append("dépôt SANS fichier de paquet mais tête non mesurée : install.vendor à "
                     "compléter à la main (commit exact)")
        return manifest
    engine = vendor_engine_name(repo)
    if install.get('pip') and not packaging:
        notes.append(f"install.pip {install['pip']!r} RETIRÉ (fait mécanique) : aucun "
                     f"{'/'.join(PACKAGING_FILES)} à la racine — pip ne sait pas l'installer")
    body['install'] = {'vendor': {'repo': repo, 'commit': sha, 'engine': engine}}
    identity = body.setdefault('identity', {})
    identity['version'] = sha[:12]
    identity['repository'] = f'https://github.com/{repo}'
    manifest['key'] = engine
    manifest['source'] = {'type': 'authored', 'ref': f'github:{repo}@{sha}'}
    notes.append(f"voie VENDOR : commit {sha[:12]} mesuré, moteur {engine!r} — à aligner sur "
                 "l'ENGINE du backend qui l'exécutera ; correctif local éventuel sous patches/")
    return manifest


_HF_REPO_ID = re.compile(r'^[\w.-]+/[\w.-]+$')


def vendored_libraries() -> list:
    """`[{key, repo, engine}]` des librairies VENDORISÉES du registre (route library, voie vendor)."""
    from wama.common.models import Library
    return [{'key': lib.key, 'repo': lib.vendor.get('repo', ''), 'engine': lib.vendor.get('engine', '')}
            for lib in Library.objects.exclude(vendor={}) if lib.vendor]


def vendor_loader_defaults(engine_dir, hf_id) -> list:
    """`[(argument, dépôt HF)]` lus par AST dans le `from_pretrained` du code vendorisé qui charge
    `hf_id` par DÉFAUT — c'est le code lui-même qui dit de quels dépôts le modèle se compose
    (YuE : `from_pretrained(model="m-a-p/YuE2-3B", *, vae="m-a-p/YuE2-Vae")`). Les tests sont ignorés."""
    import ast
    found = []
    for path in sorted(Path(engine_dir).rglob('*.py')):
        if 'tests' in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding='utf-8', errors='replace'))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != 'from_pretrained':
                continue
            args = node.args
            pairs = list(zip(args.args[len(args.args) - len(args.defaults):], args.defaults))
            pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
            repos = [(a.arg, d.value) for a, d in pairs
                     if isinstance(d, ast.Constant) and isinstance(d.value, str)
                     and _HF_REPO_ID.match(d.value)]
            if any(repo.lower() == hf_id.lower() for _, repo in repos):
                found += [r for r in repos if r not in found]
    return found


def enforce_vendor_engine(manifest, hf_id, sources_text, concerns, libraries=None, vendor_root=None):
    """Moteur et composants d'un modèle servi par un moteur VENDORISÉ — posés par les FAITS.

    Vécu le 2026-10-01 (YuE2-3B) : la découverte devinait `transformers` (retiré à juste titre :
    `YuE2ForCausalLM` n'existe pas dans le transformers installé) et le rôle rendait une
    composition VIDE — donc un modèle que le rôle `backend` refuse. Les faits étaient là : le
    README cite `github.com/multimodal-art-projection/YuE`, dépôt d'une librairie VENDORISÉE
    déclarée, et le code de celle-ci nomme ses dépôts par défaut. Deux faits, aucun jugement.
    Ne touche à rien si les sources ne citent aucune — ou plusieurs — librairie vendorisée.

    ⚠ Une CITATION ne suffit pas (vécu le 2026-10-03, SheetSage2) : son README cite le dépôt de
    YuE — le modèle vient du même labo —, et le rôle a reçu le moteur `yue`, qui ne sait pas le
    charger. Le moteur n'est posé que si le code vendorisé CHARGE ce dépôt par défaut
    (`vendor_loader_defaults` non vide) ; sinon la citation reste une piste, dite en souci.
    """
    libs = libraries if libraries is not None else vendored_libraries()
    cited = {m.lower().removesuffix('.git')
             for m in re.findall(r'github\.com/([\w.-]+/[\w.-]+)', sources_text or '')}
    matches = [lib for lib in libs if lib['repo'] and lib['repo'].lower() in cited]
    if len(matches) != 1:
        if len(matches) > 1:
            concerns.append(f"sources citant PLUSIEURS moteurs vendorisés "
                            f"({', '.join(m['engine'] for m in matches)}) — moteur laissé au jugement")
        return manifest
    lib = matches[0]
    from django.conf import settings
    root = Path(vendor_root or settings.BACKEND_VENDOR_DIR) / lib['engine']
    defaults = vendor_loader_defaults(root, hf_id) if root.is_dir() else []
    if not defaults:
        concerns.append(f"les sources citent le dépôt vendorisé {lib['repo']}, mais son code "
                        f"ne charge pas {hf_id} (aucun from_pretrained par défaut sous {root}) — "
                        f"moteur {lib['engine']!r} NON posé")
        return manifest
    body = manifest.setdefault('body', {})
    compo = body.get('composition') if isinstance(body.get('composition'), dict) else {}
    runtime = compo.setdefault('runtime', {})
    if runtime.get('engine') not in (None, '', lib['engine']):
        concerns.append(f"engine {runtime['engine']!r} REMPLACÉ par {lib['engine']!r} : le code "
                        f"vendorisé {lib['repo']} charge ce modèle")
    runtime['engine'] = lib['engine']
    if not compo.get('components'):
        compo['components'] = [
            {'role': arg, 'pattern': '*.safetensors'} if repo.lower() == hf_id.lower()
            else {'role': arg, 'repo': repo}
            for arg, repo in defaults]
        concerns.append(f"composants lus dans le code vendorisé ({lib['engine']}) : "
                        + ', '.join(f'{a}={r}' for a, r in defaults))
    body['composition'] = compo
    return manifest


#: Clés qui, dans un fichier de config à la RACINE du dépôt, disent la taille de travail d'un
#: modèle image (`pipeline_config.json` de Supra2-IMG : `image_size: 256`). Un entier = côté
#: d'une image carrée. Liste DÉCLARÉE, à étendre au premier dépôt qui en porte une autre.
RESOLUTION_KEYS = ('image_size',)


def root_config_values(hf_id, keys, lister=repo_files, loader=None) -> dict:
    """`{fichier: {clé: valeur}}` des clés `keys` trouvées dans les .json à la RACINE du dépôt."""
    import json as _json

    def _load(name):
        from huggingface_hub import hf_hub_download
        with open(hf_hub_download(hf_id, name), encoding='utf-8') as f:
            return _json.load(f)

    out = {}
    for name in lister(hf_id):
        if '/' in name or not name.endswith('.json'):
            continue
        try:
            data = (loader or _load)(name)
        except Exception:
            continue
        found = {k: data[k] for k in keys if isinstance(data, dict) and k in data}
        if found:
            out[name] = found
    return out


#: Fragment d'une classe d'`architectures` (config.json) → (tâche, catégorie) qu'elle PROUVE.
#: Vécu le 2026-10-06 (Swin2SR ONNX) : l'étiquette HF `image-to-image` mélange édition et
#: agrandissement, le dépôt ne porte pas le tag `super-resolution` qui les sépare
#: (`prospector.hf_task_to_wama`), et le scout a écrit `image-to-image` — un modèle d'ÉDITION,
#: donc proposé à l'imager. La classe `Swin2SRForImageSuperResolution` le dit, elle.
#: Liste DÉCLARÉE, à étendre au premier dépôt qui en porte une autre.
ARCHITECTURE_TASKS = {'SuperResolution': ('upscale', 'upscaling')}
#: Clé de config qui dit le FACTEUR d'un agrandisseur (`Swin2SRConfig.upscale`).
SCALE_KEYS = ('upscale',)
#: Tâches dont la sortie SUIT la taille de l'entrée : un `image_size` y est la taille des
#: fenêtres d'entraînement, pas une taille de travail (Swin2SR : 64, et il agrandit du 80×128 —
#: mesuré). La poser ferait réduire les entrées à 64 px par l'appariement.
SIZE_FOLLOWS_INPUT_TASKS = ('upscale', 'denoise', 'face-restoration')


def enforce_task_facts(manifest, hf_id, concerns, reader=None, lister=repo_files, loader=None):
    """Pose la TÂCHE (et la catégorie, le facteur) que les classes du `config.json` PROUVENT.

    Une tâche corrigée remet aussi les modalités et les entrées à celles que la tâche implique
    (`default_inputs_for`) : celles du LLM décrivaient l'AUTRE tâche. Le facteur d'un
    agrandisseur se lit dans la config (`SCALE_KEYS`). Rien n'est posé sans classe connue."""
    from wama.model_manager.models import default_inputs_for
    names, _reason = (reader or transformers_architectures)(hf_id)
    names = [names] if isinstance(names, str) else list(names or [])
    fact = next((ARCHITECTURE_TASKS[k] for n in names for k in ARCHITECTURE_TASKS if k in str(n)),
                None)
    if fact is None:
        return manifest
    task, model_type = fact
    body = manifest.setdefault('body', {})
    caps = body.setdefault('capabilities', {})
    identity = body.setdefault('identity', {})
    declared = caps.get('task')
    if declared != task:
        caps['task'] = task
        for k in ('modalities', 'inputs_required', 'inputs_optional'):
            caps.pop(k, None)
        caps.update(default_inputs_for(task))
        concerns.append(f"task {'CORRIGÉE ' + repr(declared) + ' → ' if declared else 'POSÉE à '}"
                        f"{task!r} (fait mécanique : config.json nomme {names}) ; entrées "
                        f"remises à celles de la tâche")
    if identity.get('model_type') != model_type:
        concerns.append(f"model_type {identity.get('model_type')!r} → {model_type!r} "
                        f"(suit la tâche {task!r})")
        identity['model_type'] = model_type
    values = root_config_values(hf_id, SCALE_KEYS, lister=lister, loader=loader)
    scales = {int(v) for found in values.values() for v in found.values()
              if isinstance(v, int) and not isinstance(v, bool) and v > 0}
    if len(scales) == 1:
        scale = scales.pop()
        if caps.get('scale') != scale:
            caps['scale'] = scale
            concerns.append(f"scale POSÉ à {scale} (fait mécanique : {', '.join(sorted(values))})")
    return manifest


def enforce_resolution_facts(manifest, hf_id, concerns, lister=repo_files, loader=None):
    """Pose `capabilities.native_resolution` quand un fichier de config du dépôt la DIT.

    Vécu le 2026-09-30 : Supra2-IMG génère en 256×256 FIXE — `pipeline_config.json` le dit —,
    mais aucun manifeste ne le portait, et l'imager lui proposait 896×512 (taille ignorée par le
    backend, image de 256 px). Le fait mécanique prime sur le jugement du LLM, comme le moteur :
    une valeur absente est posée, une valeur contraire est CORRIGÉE — et c'est dit. Le caractère
    FIXE (`min_resolution` = `max_resolution`) reste à déclarer : un `image_size` dit la taille
    de travail, pas qu'aucune autre n'est possible.
    Sauf pour une tâche dont la sortie suit l'entrée (`SIZE_FOLLOWS_INPUT_TASKS`) : la valeur
    y est RETIRÉE, d'où qu'elle vienne. À appeler APRÈS `enforce_task_facts`."""
    caps = (manifest.get('body') or {}).get('capabilities') or {}
    if caps.get('task') in SIZE_FOLLOWS_INPUT_TASKS:
        if caps.pop('native_resolution', None):
            concerns.append(f"native_resolution RETIRÉE : la sortie d'un modèle "
                            f"{caps['task']!r} suit la taille de l'entrée")
        return manifest
    values = root_config_values(hf_id, RESOLUTION_KEYS, lister=lister, loader=loader)
    sizes = {int(v) for found in values.values() for v in found.values()
             if isinstance(v, int) and not isinstance(v, bool) and v > 0}
    if len(sizes) != 1:
        if len(sizes) > 1:
            concerns.append(f"tailles contradictoires dans les configs du dépôt : {values}")
        return manifest
    n = sizes.pop()
    fact = f'{n}x{n}'
    body = manifest.setdefault('body', {})
    caps = body.setdefault('capabilities', {})
    declared = str(caps.get('native_resolution') or '').lower()
    if declared == fact:
        return manifest
    caps['native_resolution'] = fact
    source = ', '.join(sorted(values))
    concerns.append(f"native_resolution {'CORRIGÉE ' + repr(declared) + ' → ' if declared else 'POSÉE à '}"
                    f"{fact!r} (fait mécanique : {source})")
    return manifest


def consigne_role(nom):
    """Consigne système d'un RÔLE de wama-dev-ai (`prompts/<nom>.txt`) — accesseur UNIQUE.

    Il y avait QUATRE chemins vers ce dossier avant le 2026-09-09 : `cli.py::_load_prompt`,
    `run_audit.py` (via `config.PROMPTS_DIR`), un chemin ÉCRIT EN DUR dans `run_codegen.py`,
    et cette constante `PROMPTS` — jamais lue, donc morte. Quatre lectures d'un même dossier,
    c'est quatre endroits où une convention de nommage peut diverger sans que rien ne plante.

    `nom` s'écrit SANS extension (`'audit'`, `'codegen'`). Lève si le fichier manque : une
    consigne absente donnerait un rôle sans posture, ce qui rend une sortie plausible et
    fausse — exactement ce que la validation humaine doit attraper, mais trop tard.
    """
    chemin = PROMPTS / f"{nom}.txt"
    if not chemin.is_file():
        connues = sorted(p.stem for p in PROMPTS.glob('*.txt'))
        raise FileNotFoundError(f"consigne de rôle introuvable : {chemin} (connues : {connues})")
    return chemin.read_text(encoding='utf-8')


def skill_wama(app=None, domain=None, kind='generative'):
    """Skill de prompt WAMA le plus spécifique pour (app, domain, kind) → `(nom, texte)`.

    LE PONT, enfin construit (2026-09-09). Il était ANNONCÉ depuis le 2026-07-08 par trois
    fichiers — `config.py::PROMPT_SKILLS_DIR`, ce README, et la docstring de `prompt_skills.py`
    (« réutilisable depuis TOUTES les sources d'appel : … wama-dev-ai ») — et il n'existait
    dans AUCUN. Les trois descendaient de la MÊME phrase de décision, recopiée : ce n'étaient
    pas trois vérifications, c'était une intention comptée comme faite parce que le chemin
    avait été déclaré. La constante est retirée en même temps que ce pont est posé : un chemin
    déclaré sans lecteur est précisément ce qui a fait croire au pont pendant 14 mois.

    Import PARESSEUX et SANS REPLI, comme `ollama_host()` — mêmes raisons, même précédent.
    ⚠ Aucun `django.setup()` n'est requis : `prompt_skills` n'importe que `pathlib`/`re`/
    `logging`. VÉRIFIÉ empiriquement le 2026-09-09, `DJANGO_SETTINGS_MODULE` non défini —
    la promesse « importable sans Django » de sa docstring tient réellement, elle. Comme pour
    l'audit, aucun `INSTALLED_APPS` n'est chargé : un import cassé dans une app ne peut pas
    empêcher un rôle de tourner.

    ⚠ CE QUE ÇA N'EST PAS : les skills de `prompt_skills/` traitent le prompt d'un
    UTILISATEUR pour un modèle qui ne sait pas choisir (diffusion, SAM3, TTS) — ils sont
    résolus PAR LE CODE. Les consignes de DÉVELOPPEMENT sont d'une autre famille et d'un autre
    format (`.claude/skills/`, `SKILL.md` à frontmatter, choisi par l'agent) : ne pas les
    confondre, `WAMA_LLM §0bis 🔒` trace la frontière.
    """
    from wama.common.utils.prompt_skills import resolve_skill
    return resolve_skill(app=app, domain=domain, kind=kind)


def catalogue_skills():
    """`{nom: texte}` de tous les skills de prompt WAMA — pour un rôle qui explore le corpus."""
    from wama.common.utils.prompt_skills import skills_catalog
    return skills_catalog()


def fetch(url, user_agent='wama-dev-ai'):
    """GET texte via le proxy d'environnement (GitHub/HF passent par le proxy UGE)."""
    req = urllib.request.Request(url, headers={'User-Agent': user_agent})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def call_ollama(model, system, user_msg, num_ctx=16384, keep_alive=None,
                temperature=0.1, timeout=600):
    """Appel Ollama one-shot. `keep_alive='0'` décharge le modèle SITÔT la réponse rendue
    (au lieu des ~5 min de résidence par défaut) — c'est la parade du mode dépannage GPU,
    à passer depuis `resource_governor.pipeline_keep_alive()`. None = défaut Ollama.

    ⚠ `temperature` et `timeout` sont PARAMÈTRES depuis le 2026-09-07, et les défauts ici
    sont EXACTEMENT ceux d'avant (0.1 / 600 s) : les quatre rôles qui appellent sans les
    citer sont donc inchangés au bit près. Ils existent parce que `run_codegen` portait un
    DOUBLON de cette fonction avec trois valeurs différentes (0.2 / 32768 / 900 s) —
    remplacer sans les offrir aurait TRONQUÉ sa matière (jusqu'à 60 000 caractères servis,
    illisibles à num_ctx=16384) et raccourci son délai. *Avant de supprimer un doublon, on
    compare ; s'il diverge, on FUSIONNE — sinon la déduplication perd une capacité.*
    """
    payload = {
        'model': model,
        'messages': [{'role': 'system', 'content': system},
                     {'role': 'user', 'content': user_msg}],
        'stream': False,
        'options': {'temperature': temperature, 'num_ctx': num_ctx},
    }
    if keep_alive is not None:
        payload['keep_alive'] = keep_alive
    req = urllib.request.Request(
        f'{ollama_host()}/api/chat', data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'})
    with _OPENER_DIRECT.open(req, timeout=timeout) as r:
        return json.loads(r.read())['message']['content']


#: Variable d'environnement qui choisit le fournisseur de TOUS les rôles quand la ligne de
#: commande n'en impose aucun. Absente = `ollama`, le comportement d'avant à l'octet.
PROVIDER_ENV = 'WAMA_DEV_AI_PROVIDER'


def add_llm_arguments(parser, role='dev'):
    """Options `--provider` et `--model` des rôles — UNE définition pour les cinq pilotes.

    Posée le 2026-09-15 avec Albert API : chaque pilote déclarait à la main son `--model`
    « Modèle Ollama ». Ajouter un fournisseur aurait voulu dire l'ajouter cinq fois.
    """
    parser.add_argument(
        '--provider', default=os.environ.get(PROVIDER_ENV) or 'ollama',
        help=f"ollama (local) ou un fournisseur de llm_chat : albert, anthropic… "
             f"(défaut : ${PROVIDER_ENV}, sinon ollama)")
    parser.add_argument(
        '--model', default=None,
        help=f"Modèle (défaut : chaîne du rôle {role} en local, modèle par défaut du "
             f"fournisseur sinon)")


def resolve_model(provider, role, model=None):
    """Modèle effectif d'un rôle.

    Local : chaîne de repli RAM-aware de `config.py`. Distant : modèle par défaut du
    fournisseur (`llm_utils.default_cloud_model`) — la VRAM de l'hôte ne dit rien d'un modèle
    qui tourne ailleurs. Résolu ICI plutôt que laissé à `llm_chat` pour que le rapport de
    sortie nomme le modèle réellement employé.
    """
    if model:
        return model
    if provider == 'ollama':
        # BRIDAGE « niveau développement » (Fabien, 2026-09-22 — global à wama-dev-ai) : le
        # tirage passe par le domicile commun `development_models` (plancher sur le score coding
        # du banc, curseur 100, jamais de repli sur un petit modèle). La chaîne de `config.py`
        # finissait sur `fast`/`ultra_fast` dès que la VRAM manquait : c'est exactement le
        # modèle qui invente des imports. Sans catalogue (première installation), la chaîne
        # historique reste le dernier recours — et le dit.
        try:
            from wama.common.services.development_models import (
                development_model, development_refusal)
            key = development_model(None)
        except Exception as e:      # catalogue injoignable : pas une raison de bloquer un rôle
            print(f"[role_utils] catalogue indisponible ({e}) — chaîne de repli de config.py")
            from config import select_model_for_role
            return select_model_for_role(role)[1].ollama_id
        if not key:
            raise RuntimeError(development_refusal(None))
        return key.split(':', 1)[1]
    from wama.common.utils.llm_utils import default_cloud_model
    return default_cloud_model(provider)


def call_llm(provider, model, system, user_msg, num_ctx=16384, keep_alive=None,
             temperature=0.1, timeout=600):
    """Appel one-shot d'un rôle, quel que soit le fournisseur.

    `ollama` → `call_ollama` inchangé (keep_alive et num_ctx compris). Tout autre fournisseur
    → `llm_chat`, la passerelle LiteLLM commune à l'assistant : un seul endroit sait router
    vers Albert. `num_ctx` et `keep_alive` n'y ont pas de sens (fenêtre et résidence sont
    gérées par le fournisseur) ; `num_predict=None` ne plafonne pas la réponse, comme Ollama.

    Lève `RuntimeError` en cas d'échec, comme `call_ollama` lève sur une erreur HTTP : les
    pilotes n'ont pas à distinguer les deux chemins.
    """
    if provider == 'ollama':
        return call_ollama(model, system, user_msg, num_ctx=num_ctx, keep_alive=keep_alive,
                           temperature=temperature, timeout=timeout)
    from wama.common.utils.llm_utils import llm_chat
    text, error = llm_chat(
        [{'role': 'system', 'content': system}, {'role': 'user', 'content': user_msg}],
        model=model or None, provider=provider, num_predict=None,
        temperature=temperature, timeout=timeout)
    if text is None:
        raise RuntimeError(f'{provider} : {error}')
    return text


def extract_json(text):
    """Premier objet JSON équilibré du texte (les modèles emballent parfois en ```json)."""
    text = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M)
    start = text.find('{')
    if start < 0:
        raise ValueError('aucun JSON dans la réponse')
    depth = 0
    for i, c in enumerate(text[start:], start):
        depth += (c == '{') - (c == '}')
        if depth == 0:
            return json.loads(text[start:i + 1])
    raise ValueError('JSON non équilibré')


def write_output(role, slug, payload):
    """Rapport horodaté dans outputs/ — TOUJOURS PENDING_HUMAN_VALIDATION."""
    from datetime import datetime
    OUTPUTS.mkdir(exist_ok=True)
    horodatage = datetime.now().strftime('%Y-%m-%d_%H-%M')
    sortie = OUTPUTS / f"{role}_{slug.replace('/', '_')}_{horodatage}.json"
    sortie.write_text(json.dumps({'status': 'PENDING_HUMAN_VALIDATION', 'role': role,
                                  **payload}, ensure_ascii=False, indent=2), encoding='utf-8')
    return sortie


def manifest_examples(dossier, *, prefer_source='', want_composed=None, limit=2) -> str:
    """
    Exemples du corpus choisis PAR NATURE — le few-shot d'un rôle, pas le premier fichier venu.

    Pourquoi (2026-09-19) : `run_scout.py` prenait `sorted(glob)[:1]`, c'est-à-dire le premier
    par ORDRE ALPHABÉTIQUE — `albert__bge-m3.json`, un modèle CLOUD servi par une API, comme
    unique exemple pour traduire un dépôt HuggingFace LOCAL. Un exemple hors nature enseigne
    la mauvaise forme : il n'a ni poids, ni composition, ni moteur. `run_model_manifest.py`
    faisait déjà le choix par nature (un COMPOSÉ + un simple) : ce corps est le sien, déplacé
    ici pour que les deux rôles le partagent au lieu de le dupliquer.

    `prefer_source` : préfixe de nom de fichier privilégié (`huggingface__`, `ollama__`…) — le
    corpus assainit `:` en `__`, donc la source d'une clé est son préfixe.
    `want_composed` : True = privilégier ceux qui déclarent `composition.runtime`, False =
    l'éviter, None = prendre un de chaque (le défaut, qui montre les deux formes).
    """
    fichiers = sorted(Path(dossier).glob('*.json'))
    if prefer_source:
        meme_nature = [f for f in fichiers if f.name.startswith(prefer_source)]
        fichiers = meme_nature + [f for f in fichiers if f not in meme_nature]

    composes, simples = [], []
    for f in fichiers:
        try:
            d = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        cible = composes if ((d.get('body') or {}).get('composition') or {}).get('runtime') else simples
        cible.append(f)

    if want_composed is True:
        choisis = (composes + simples)[:limit]
    elif want_composed is False:
        choisis = (simples + composes)[:limit]
    else:                      # un de chaque forme, dans l'ordre de préférence de nature
        choisis = [x for x in (composes[:1] + simples[:1]) if x][:limit]
    return '\n\n'.join(f.read_text(encoding='utf-8') for f in choisis)
