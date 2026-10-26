"""
Pipeline accept→download→register — installation de modèles dans WAMA.

Étape 2 du système d'auto-maintenance : une fois un modèle ACCEPTÉ (par l'admin, ou plus tard
par la prospection validée), on le télécharge AU BON ENDROIT puis on l'enregistre dans le
catalogue `AIModel` pour qu'il devienne visible/sélectionnable.

Ollama d'abord : `POST /api/pull` sur le démon LOCAL = API officielle (le démon parle au
registre, pas nous → aucun scraping). HF viendra ensuite (règle AGENTS.md : path→env→import).
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def pull_ollama_model(name: str, timeout: int = 1800, progress=None):
    """
    Télécharge un modèle Ollama via le démon LOCAL (`POST /api/pull`, stream).

    `progress` : callback optionnel(status:str) pour remonter l'avancement.
    Retourne {'ok': bool, 'status': str} ou {'ok': False, 'error': str}.
    """
    import requests
    from wama.common.utils.ollama_host import ollama_base, ollama_kwargs

    base = ollama_base()
    last = None
    try:
        with requests.post(f"{base}/api/pull", json={"name": name, "stream": True},
                           stream=True, **ollama_kwargs(timeout=timeout)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if data.get('error'):
                    return {'ok': False, 'error': data['error']}
                status = data.get('status')
                # Le flux porte `completed`/`total` par couche : un POURCENTAGE dans le
                # statut (2026-08-18, install asynchrone) — le callback garde sa signature
                # (str) et n'est appelé qu'au changement, donc ~100 appels par couche max.
                total, fait = data.get('total'), data.get('completed')
                if status and total and fait is not None:
                    status = f"{status} {int(fait * 100 / total)}%"
                if status and status != last:
                    last = status
                    if progress:
                        progress(status)
        return {'ok': True, 'status': last or 'success'}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def delete_ollama_model(name: str, timeout: int = 60) -> dict:
    """
    Désinstalle un modèle Ollama (`DELETE /api/delete`) — libère sa place sur le volume.

    Sert le REMPLACEMENT : quand un candidat succède à un modèle installé, l'espace du nouveau
    n'est disponible qu'après retrait de l'ancien (D: est à 96 %). Ollama ne supprime que les
    blobs devenus orphelins : les couches partagées avec un autre tag restent en place, donc
    l'espace réellement rendu peut être inférieur à la taille annoncée.

    Envoie `model` ET `name` : la clé du corps a changé selon les versions du démon, et accepter
    les deux évite un échec silencieux sur une machine au démon plus ancien.
    """
    import requests
    from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
    try:
        r = requests.delete(f"{ollama_base()}/api/delete",
                            json={"model": name, "name": name},
                            **ollama_kwargs(timeout=timeout))
        if r.status_code in (200, 204):
            return {'ok': True}
        return {'ok': False, 'error': f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


# ModelType (catalogue) → catégorie de dossier (model_locations.model_dir).
# ⚠ COQUILLE corrigée le 2026-09-02 (audit des emplacements, question de Fabien) : cette
# table envoyait `vision` vers `detect/` et `upscaling` vers `enhance/` — deux dossiers qui
# n'existent PAS (`AI-models/models/` a `vision/` et `upscaling/`, comme `model_locations`
# le prescrit depuis la règle « catégorie = valeur ModelType »). Seul `manage.py pull_model`
# sans `--category` y passait ; le chemin de la prospection (`install_from_spec`) portait la
# catégorie du spec et tombait juste. La table est désormais l'IDENTITÉ, et les anciens mots
# `detect`/`enhance` restent tolérés en entrée (`model_locations._CATEGORY_ALIASES`).
_TYPE_CATEGORY = {
    'diffusion': 'diffusion',
    'speech':    'speech',
    'vlm':       'vlm',
    'vision':    'vision',
    'upscaling': 'upscaling',
    'ocr':       'ocr',
    'music':     'music',
    'llm':       'llm',
    'embedding': 'embedding',
    'lipsync':   'lipsync',
}


#: Message du refus d'un dépôt qui exige un jeton que la personne n'a pas posé (ou dont
#: l'accès n'a pas été accordé à son compte) — il dit où agir, jamais la clé.
GATED_REFUSAL = ("Ce dépôt HuggingFace est soumis à conditions (« gated ») : son téléchargement "
                 "se fait avec VOTRE jeton, et votre compte HuggingFace doit avoir obtenu l'accès "
                 "sur la page du modèle. Posez votre jeton dans Profil → Clés d'API.")


def _is_access_refusal(exc) -> bool:
    """Refus d'ACCÈS du Hub (dépôt gated, jeton absent ou refusé) — par la classe d'erreur de
    `huggingface_hub` quand elle existe, sinon par le statut HTTP (versions de la lib)."""
    if 'Gated' in type(exc).__name__:
        return True
    status = getattr(getattr(exc, 'response', None), 'status_code', None)
    return status in (401, 403)


def pull_hf_model(hf_id: str, category: str, family: str | None = None,
                  dry_run: bool = False, allow_patterns=None, progress=None, token=None):
    """
    Télécharge un modèle HuggingFace DANS LE BON DOSSIER (catégorie WAMA) via l'API officielle
    `snapshot_download(cache_dir=…)` — on catégorise par `cache_dir`, SANS muter `HF_HUB_CACHE`
    global (cause de dispersion/doublons quand plusieurs threads le mutent en concurrence).

    `dry_run` : ne télécharge pas, retourne juste le dossier cible (valide la logique de chemin).
    `token` : `accounts.api_keys.download_token` — le jeton de la personne qui lance, `False`
    si elle n'en a pas (jamais celui de l'instance à sa place), `None` sans utilisateur.
    Retourne {'ok': bool, 'path'|'target'|'error': …}.

    NB : « téléchargé + catalogué » ≠ « utilisable dans l'app » — l'usage requiert un backend qui
    sache charger ce modèle (problème du chargeur générique, séparé).
    """
    import os
    try:
        from wama.common.utils.model_locations import model_dir
        target = str(model_dir(category, family or hf_id.split('/')[-1]))
    except Exception as e:
        return {'ok': False, 'error': f"résolution dossier: {type(e).__name__}: {e}"}

    if dry_run:
        return {'ok': True, 'target': target, 'dry_run': True}

    os.makedirs(target, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
        ignore = None if allow_patterns else format_duplicates(hf_id)
        path = snapshot_download(repo_id=hf_id, cache_dir=target, allow_patterns=allow_patterns,
                                 ignore_patterns=ignore or None, token=token)
        return {'ok': True, 'path': path, 'target': target,
                **({'ignores': ignore} if ignore else {})}
    except Exception as e:
        if _is_access_refusal(e):
            return {'ok': False, 'error': GATED_REFUSAL, 'reason': 'gated'}
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def duplicate_weight_files(files) -> list:
    """
    Fichiers de poids à NE PAS tirer parce que leur jumeau `.safetensors` existe — même
    tenseurs, second format (mesuré le 02/09 : table-transformer et Qwen3-TTS tirés en double,
    `pytorch_model.bin` + `model.safetensors`, 115 Mo ×2 puis 4,2 Go ×2).

    **Dérivation PURE, aucun réseau** (séparée de son appel HTTP le 2026-09-19) : `files`
    accepte les deux formes d'inventaire qui circulent — les chemins nus de
    `HfApi().list_repo_files`, ou les couples `(chemin, taille)` que rend
    `prospector._siblings`. Motif de la séparation : la RÈGLE des jumeaux ne sert pas qu'à
    éviter un double téléchargement, elle sert aussi à **ne pas compter deux fois** un poids ;
    tant qu'elle était soudée à sa requête, tout second lecteur payait un aller-retour HTTP de
    plus sur un dépôt déjà inventorié. Même partage que `_poids_total_gb` / `_repo_weight_gb`.

    Volontairement ÉTROIT : seul un `.bin` / `.pt` / `.pth` / `.ckpt` dont le NOM DE BASE a un
    jumeau `.safetensors` dans le même dossier est écarté. Un `.pt` sans jumeau (les voix de
    Kokoro, un checkpoint YOLO) est GARDÉ — exclure `*.pt` en bloc casserait ces dépôts.
    Retourne des motifs `ignore_patterns` exacts (chemins dans le dépôt).
    """
    names = [f[0] if isinstance(f, (tuple, list)) else f for f in (files or [])]
    present = set(names)
    stem = lambda p: p.rsplit('.', 1)[0]
    safes = {stem(f) for f in names if f.endswith('.safetensors')}
    # Les shards diffusers/transformers : `model-00001-of-00003.safetensors` ↔ `pytorch_model-00001-of-00003.bin`
    safes |= {stem(f).replace('model-', 'pytorch_model-', 1) for f in names
              if f.endswith('.safetensors') and '/model-' in '/' + f}
    duplicates = []
    for f in names:
        if not f.endswith(('.bin', '.pt', '.pth', '.ckpt')):
            continue
        base = stem(f)
        twin = base in safes or base.replace('pytorch_model', 'model', 1) in safes
        if twin and f in present:
            duplicates.append(f)
    return sorted(duplicates)


def format_duplicates(hf_id: str) -> list:
    """Les jumeaux de format d'un dépôt HF — un appel HTTP, la règle vient de
    `duplicate_weight_files`. S'appelait `doublons_de_format` jusqu'au 2026-09-19 (bascule de
    la langue du code). Best-effort : si le listing échoue, on ne filtre rien (le doublon
    coûte du disque, pas l'installation)."""
    try:
        from huggingface_hub import HfApi
        return duplicate_weight_files(HfApi().list_repo_files(hf_id))
    except Exception:
        return []


# Suffixe de nom de poids → sous-dossier de tâche YOLO (AI-models/models/vision/yolo/<task>/).
# ⚠ Ces valeurs SONT le vocabulaire `ModelTask` (segment/obb/pose/classify/detect) : le
# sous-dossier et la tâche déclarée d'un YOLO sont un seul fait, pas deux conventions qui se
# ressemblent — c'est ce qui permet de proposer un candidat YOLO avec sa tâche sans la redeviner.
_YOLO_TASK_DIRS = {'-seg': 'segment', '-obb': 'obb', '-pose': 'pose', '-cls': 'classify'}


#: Chemin STABLE des poids YOLO officiels (assets GitHub Ultralytics) sur la source déclarée
#: `github` — un seul domicile : le téléchargement et le relevé de taille le lisent ici.
#: (2026-10-10 : l'adresse était écrite en dur, `https://github.com/…`, à côté du pilote `github`
#: qui dérive la sienne de la source — deux pilotes, deux règles d'adressage et de proxy.)
_YOLO_ASSET_PATH = "ultralytics/assets/releases/latest/download/{}.pt"


def _yolo_asset_url(base: str) -> str:
    from wama.common.external_sources import base_url
    return f"{base_url('github')}/{_YOLO_ASSET_PATH.format(base)}"


def _yolo_asset_gb(name: str):
    """Poids d'un asset YOLO officiel, par un HEAD sur son URL de release (None si injoignable).
    Branche YOLO de `weight_for_spec` — pas un point d'entrée."""
    from wama.common.external_sources import proxies_for
    base = (name or '')[:-3] if (name or '').endswith('.pt') else (name or '')
    return _asset_gb(_yolo_asset_url(base), proxies=proxies_for('github'))


def _asset_gb(url: str, proxies=None):
    """Poids en Go d'un fichier publié, par un HEAD sur son URL (None si injoignable ou sans
    taille). Corps commun des pilotes à asset (`yolo`, `github`) — extrait de `_yolo_asset_gb`."""
    import requests

    try:
        rep = requests.head(url, timeout=15, allow_redirects=True, proxies=proxies)
        size = int(rep.headers.get('Content-Length') or 0)
    except Exception:
        return None
    return round(size / 1024 ** 3, 3) if size else None


def weight_for_spec(spec: dict):
    """
    Poids en Go de ce qu'un descripteur d'installation va TIRER, ou None si indéterminable.

    JUMEAU de `provenance.identity_for_spec` — même descripteur, même dispatch par `kind`, et
    c'est le motif de la maison (`install_from_spec` dispatche les drivers de la même façon).
    ⚠ Écrit le 2026-09-19 sur une remarque de Fabien (« pourquoi une fonction spécifique à
    YOLO ? ») : la réponse à « combien pèse ce que je vais tirer ? » existait en TROIS exemplaires
    dispersés, chacun appelé à la main par un appelant différent — `_repo_weight_gb` (HF),
    `ollama_registry.size_gb` (Ollama), et un relevé YOLO que je venais d'ajouter en quatrième.
    *Trois réponses à une même question ne divergent pas bruyamment : elles se répartissent entre
    des appelants qui n'en connaissent chacun qu'une.* Ici on ne réécrit RIEN : chaque branche
    appelle la brique existante de sa source.

    None = indéterminable, et l'appelant doit alors REFUSER d'installer plutôt que de supposer
    (sur un volume à 96 %, une supposition optimiste remplit le disque).
    """
    spec = spec or {}
    kind, ref = spec.get('kind'), (spec.get('ref') or '').strip()
    if not ref:
        return None
    if kind == 'hf':
        from .prospector import _repo_weight_gb
        return _repo_weight_gb(ref)
    if kind == 'ollama':
        from .ollama_registry import size_gb
        name, _, tag = ref.partition(':')
        return size_gb(name, tag or 'latest')
    if kind == 'yolo':
        return _yolo_asset_gb(ref)
    if kind == 'github':
        if github_spec_error(spec):
            return None
        from wama.common.external_sources import proxies_for
        return _asset_gb(github_asset_url(spec), proxies=proxies_for('github'))
    if kind == 'files':
        # Fichiers déclarés : leur taille l'est aussi (mesurée, exigée par le verrou).
        if declared_files_error(spec):
            return None
        return round(sum(f['size'] for f in spec['files']) / 1024 ** 3, 3)
    return None


#: Rôle porté par un poids à la RACINE d'un dépôt (modèle monobloc, sans `model_index.json`) :
#: un seul composant, donc somme et plus gros composant se confondent.
_SINGLE_ROLE = 'model'

#: Marqueurs de PRÉCISION dans un nom de fichier de poids. Distincts des `_QUANT_MARKERS` de
#: `prospector` (qui qualifient un DÉPÔT dérivé, pas un fichier) : `bf16`/`fp16` ne sont pas des
#: quantisations, ce sont les précisions natives — un dépôt entier en bf16 est la NORME, un
#: fichier bf16 à côté d'un autre dans le même dossier est une VARIANTE.
_DTYPE_MARKERS = ('bf16', 'fp16', 'fp32', 'f16', 'f32', 'float16', 'float32', 'half')

#: Marqueurs des poids d'un AUTRE moteur — la même chose, réécrite pour un autre runtime.
#: ⚠ On ne les écarte que si un jeu PyTorch existe dans le même rôle : WAMA catalogue de vrais
#: modèles ONNX (`onnx-community/Kokoro-82M-v1.0-ONNX`), pour qui l'ONNX EST le modèle.
_FOREIGN_ENGINE_MARKERS = ('flax', 'openvino', 'onnx', 'tf_model', 'rust_model', 'msgpack',
                           'coreml', 'mlx')

#: `nom-00002-of-00005.safetensors` → base `nom`, découpage `5`. Deux jeux de shards concurrents
#: dans un même dossier ne se distinguent QUE par ce découpage (cas mochi `text_encoder`).
_SHARD_RE = re.compile(r'^(?P<base>.+?)-\d{4,6}-of-(?P<total>\d{4,6})$')


def _weight_set_key(filename: str) -> tuple:
    """Identifie le JEU de poids auquel un fichier appartient, dans son rôle.

    Deux fichiers du même jeu s'ADDITIONNENT (des shards d'un même tenseur) ; deux jeux
    différents sont des ALTERNATIVES, dont une seule sera chargée. La clé porte donc : le nom
    de base (shard retiré), le nombre de shards annoncé, la précision marquée, et le moteur
    étranger éventuel.
    """
    stem = filename.rsplit('.', 1)[0]
    low = filename.lower()
    m = _SHARD_RE.match(stem)
    base, total = (m.group('base'), m.group('total')) if m else (stem, '')
    dtype = next((d for d in _DTYPE_MARKERS if d in low), '')
    foreign = next((f for f in _FOREIGN_ENGINE_MARKERS if f in low), '')
    # Le marqueur de précision fait partie du nom de base : on le retire pour que
    # `x.bf16-00001-of-00003` et `x-00001-of-00005` portent le même base et se comparent.
    for d in _DTYPE_MARKERS:
        base = base.replace('.' + d, '').replace('-' + d, '').replace('_' + d, '')
    return (base, total, dtype, foreign)


def components_of_files(files, *, composition=None, allow_patterns=None) -> dict:
    """Poids PAR COMPOSANT d'un inventaire de fichiers — dérivation PURE, aucun réseau.

    🔴 **UN DÉPÔT N'EST PAS UN MODÈLE : c'est un CATALOGUE de fichiers.** Mesuré le 2026-09-19
    sur les cartes HF des modèles RÉELLEMENT catalogués : `genmo/mochi-1-preview` totalise
    **124,3 Go** de poids, `Lightricks/LTX-Video-0.9.8-13B-distilled` 86,4 Go,
    `stabilityai/stable-diffusion-xl-base-1.0` 45,7 Go — aucun n'est l'empreinte de son modèle.
    *La question n'est donc jamais « que contient le dépôt » mais « que va CHARGER le
    chargeur ».* D'où la restriction ci-dessous, qui n'est pas un filtre de confort : sans elle,
    les deux chiffres feraient écarter du tirage la moitié du parc.

    ⚠ Et les quatre causes du gonflement sont NOMMÉES, chacune par un cas mesuré — c'est ce
    que traitent `_WEIGHT_SET_KEY` et les règles plus bas :
    1. **une copie MONOFICHIER du pipeline entier à la racine**, pour les chargeurs qui ne
       lisent pas l'arborescence diffusers — `genmo/mochi-1-preview:dit.safetensors` 37,4 Go
       en plus de `transformer/` ; `FLUX.2-klein-4B:flux-2-klein-4b.safetensors` 7,2 Go, soit
       EXACTEMENT son `transformer/diffusion_pytorch_model.safetensors` ;
    2. **des variantes de PRÉCISION dans le même dossier** — `transformer/…bf16-00001-of-00003`
       à côté du jeu pleine précision (mochi), `unet/…fp16.safetensors` (SDXL) ;
    3. **les copies d'AUTRES MOTEURS** — `unet/diffusion_flax_model.msgpack`,
       `unet/openvino_model.bin`, `unet/model.onnx_data`, tous trois de 9,56 Go comme le
       `.safetensors` qu'ils recopient (SDXL) ;
    4. **deux jeux de SHARDS concurrents sous le même nom de base** —
       `text_encoder/model-00001-of-00002` (8,9 Go) ET `…-00001-of-00004` (17,8 Go) dans le
       même mochi : rien dans le NOM ne les distingue, seul leur découpage le fait.
    ⚠ Reste un cas que cette dérivation ne sait PAS traiter : un dépôt qui IMBRIQUE un
    pipeline sous un rôle (`Lightricks/…:vae/transformer/…`, `vae/text_encoder/…` — d'où un
    « vae » de 44 Go). Le premier segment n'est alors pas le composant, et seule la lecture de
    `model_index.json` le dirait. C'est pour ces dépôts que la composition DÉCLARÉE est la
    seule réponse juste.

    `composition` : l'anatomie DÉCLARÉE du modèle (`AIModel.composition`, schéma validé par
    `manifests.builtin.model._validate_composition`) — `{'components': [{'role', 'pattern'}]}`.
    Quand elle est là, les rôles et la sélection viennent d'ELLE, pas d'une heuristique : c'est
    la même déclaration que `patterns_from_composition` transforme en `allow_patterns` pour
    l'installation. Une anatomie déclarée UNE fois, deux lectures — ce qu'on tire et ce qu'on
    pèse ne peuvent plus diverger.
    `allow_patterns` : la restriction du descripteur d'installation, quand elle est explicite
    (une variante choisie). Même sémantique `fnmatch` que `snapshot_download`.

    Sans l'une ni l'autre, on retombe sur la convention de fait des pipelines composés : le
    composant est le PREMIER SEGMENT du chemin (`transformer/…`, `text_encoder/…`, `vae/…`),
    un poids à la racine appartenant au modèle monobloc (`_SINGLE_ROLE`). C'est la convention
    de `model_index.json` sans avoir à le lire — mais le résultat est alors marqué
    `source='repo'` : une borne supérieure, pas une empreinte.

    POURQUOI ce chiffre-là (décision A de Fabien, `PROJECT_STATUS §④A` du 16/09) : un modèle
    composé a **deux** empreintes et non une — la SOMME de ses composants (plein GPU) et son
    PLUS GROS composant (déchargement séquentiel, où un composant descend quand le suivant
    monte). Les tenir pour un seul nombre, c'est ce qui a fait écarter du tirage un modèle de
    21 Go qui tourne très bien sur 24 Go en déchargement, et tenter un plein GPU sur 38 Go.
    Ici on ne rend que les FAITS (les Go par rôle) : la marge d'activations et le choix de
    stratégie restent à `memory_manager`, seul endroit qui connaît la carte.

    `files` : `[(chemin, taille)]` ou `[chemin]` — les deux inventaires qui circulent
    (`prospector._siblings` à distance, un parcours de snapshot en local). Sans taille, on ne
    peut rien peser : les entrées sans taille sont IGNORÉES, et un inventaire entièrement sans
    taille rend `{}` plutôt que des zéros (`0.0` se lirait « ça ne pèse rien »).

    Ce que la dérivation ÉCARTE, chacun par une brique existante ou une règle mesurée :
    - les **jumeaux de format** (`.bin` doublant un `.safetensors`) → `duplicate_weight_files` ;
    - dans un rôle, **tous les JEUX de poids sauf un** (`_weight_set_key`) : quantisation
      (`_QUANT_MARKERS`), précision (`_DTYPE_MARKERS`), moteur étranger
      (`_FOREIGN_ENGINE_MARKERS`), découpage de shards concurrent. On garde le jeu **le plus
      LOURD parmi les non marqués** — arbitrage déjà écrit dans `MODEL_SIZE_PRESETS`
      (`memory_manager.py:87-91`) : *sur-estimer coûte de l'offload, sous-estimer fait tenter
      un plein GPU et déborde en RAM hôte*, ce qui a produit les kernel panics du 29/07 ;
    - la **copie monofichier à la racine** quand le dépôt est un pipeline (`model_index.json`
      présent ET des rôles en sous-dossiers).
    Rien n'est jeté : tout ce qui est écarté se retrouve dans `variants`, pour qu'un choix reste
    possible en amont et qu'on voie ce que la règle a fait.

    ⚠ Ce qu'elle NE fait PAS : lire les dtypes RÉELS (un nom de fichier n'est pas une preuve de
    précision — l'en-tête safetensors le dirait, aucune brique ne le lit aujourd'hui), deviner
    les activations, ni distinguer deux composants qui se partagent des poids. Elle pèse des
    FICHIERS. Les shards d'un même jeu s'additionnent : ce sont des morceaux d'un tenseur.
    """
    import fnmatch

    sized = [(f[0], f[1]) for f in (files or [])
             if isinstance(f, (tuple, list)) and len(f) > 1 and (f[1] or 0) > 0]
    if not sized:
        return {}
    from .prospector import _QUANT_MARKERS, _WEIGHT_EXTS
    twins = set(duplicate_weight_files(sized))
    names = {p for p, _ in sized}

    declared = [(c.get('role') or _SINGLE_ROLE, c['pattern'])
                for c in ((composition or {}).get('components') or [])
                if isinstance(c, dict) and c.get('pattern')]
    source = 'declared' if declared else ('allow_patterns' if allow_patterns else 'repo')

    def role_of(path):
        """Rôle du fichier, ou None s'il ne fait pas partie de ce qu'on pèse."""
        if declared:
            # La déclaration tranche : un fichier qu'aucun composant ne réclame n'est pas
            # un poids du modèle (fichier de bord, variante non retenue, version voisine).
            return next((r for r, pat in declared if fnmatch.fnmatch(path, pat)), None)
        if allow_patterns and not any(fnmatch.fnmatch(path, p) for p in allow_patterns):
            return None
        return path.split('/')[0] if '/' in path else _SINGLE_ROLE

    # ── 1. Peser chaque JEU de poids, par rôle ───────────────────────────────────────────
    sets = {}                      # (rôle, clé de jeu) → Go
    members = {}                   # (rôle, clé de jeu) → [(chemin, octets)]
    for path, size in sized:
        if path in twins or not path.lower().endswith(_WEIGHT_EXTS):
            continue
        role = role_of(path)
        if role is None:
            continue
        key = _weight_set_key(path.rsplit('/', 1)[-1])
        sets[(role, key)] = sets.get((role, key), 0.0) + size / 1024 ** 3
        members.setdefault((role, key), []).append((path, size))

    # ── 2. Un seul jeu par rôle ; les autres sont des alternatives ───────────────────────
    # Une composition DÉCLARÉE a déjà tranché : ses patterns disent ce qui est chargé, on ne
    # « corrige » pas son choix. La sélection d'un jeu ne vaut que pour l'heuristique.
    full, variants, kept = {}, {}, {}
    roles = {r for r, _ in sets}
    for role in roles:
        groups = {k: gb for (r, k), gb in sets.items() if r == role}
        if declared:
            full[role] = sum(groups.values())
            kept[role] = [f for k in groups for f in members[(role, k)]]
            continue
        marked = {k: gb for k, gb in groups.items()
                  if k[2] or k[3] or any(m in k[0].lower() for m in _QUANT_MARKERS)}
        plain = {k: gb for k, gb in groups.items() if k not in marked}
        # Un rôle qui n'existe QUE marqué (dépôt fp8 entier, vrai modèle ONNX) pèse ce qu'il
        # pèse : le ranger dans `variants` le ferait disparaître du total.
        candidates = plain or marked
        winner = max(candidates, key=lambda k: candidates[k])
        full[role] = candidates[winner]
        kept[role] = list(members[(role, winner)])
        alt = sum(gb for k, gb in groups.items() if k != winner)
        if alt:
            variants[role] = alt

    # ── 3. La copie MONOFICHIER d'un pipeline n'est pas un composant de plus ─────────────
    if not declared and 'model_index.json' in names and len(roles - {_SINGLE_ROLE}) >= 2 \
            and _SINGLE_ROLE in full:
        variants[_SINGLE_ROLE] = variants.get(_SINGLE_ROLE, 0.0) + full.pop(_SINGLE_ROLE)
        kept.pop(_SINGLE_ROLE, None)

    if not full:
        return {}
    out = {'components': {r: round(gb, 3) for r, gb in sorted(full.items())},
           'total_gb': round(sum(full.values()), 3),
           'largest_gb': round(max(full.values()), 3),
           'source': source,
           # Les FICHIERS retenus par rôle — demande de l'instance qui lit les en-têtes
           # safetensors (2026-09-20) : le poids d'un fichier ne dit pas sa PRÉCISION, et le pic
           # réel d'un composant dépend du dtype auquel il sera chargé. Rendre les chemins évite
           # qu'un second lecteur refasse le tri des jeux, des jumeaux et des variantes pour
           # retrouver QUELS fichiers composent le chiffre. C'est le même relevé, à deux grains.
           'files': {r: sorted(kept.get(r) or []) for r in sorted(full)}}
    if variants:
        out['variants'] = {r: round(gb, 3) for r, gb in sorted(variants.items())}
    return out


#: Un composant peut vivre dans un AUTRE dépôt (`{'role': …, 'repo': 'org/nom'}`) — c'est le
#: second bras du schéma `composition`, et 5 déclarations du catalogue s'en servent
#: (pyannote-diarization, codeformer, les 3 DeepFace). Motif : `org/nom`, sans schéma d'URL.
_HF_REPO_RE = re.compile(r'^[\w.-]+/[\w.-]+$')


def _local_repo_weight_gb(repo: str):
    """Poids d'un dépôt frère DÉJÀ INSTALLÉ, ou None s'il n'est pas sur ce disque.

    Le disque AVANT le réseau (2026-09-20, signalement de l'instance sœur) : `pyannote-diarization`
    rendait `unresolved` sur ses DEUX composants alors que les deux dépôts frères sont installés
    ici — la pesée ne savait aller qu'à distance, et `pyannote/segmentation-3.0` est GATED (l'API
    rend 401). *Un dépôt qu'on a sous la main n'a pas à être demandé à un serveur qui le refuse.*
    Réutilise les deux briques existantes : l'index `hf_id → snapshot` et l'inventaire local.
    """
    try:
        from wama.common.utils.model_locations import installed_snapshots
        from .prospector import local_inventory
    except Exception:
        return None
    try:
        root_path = installed_snapshots().get((repo or '').strip().lower())
        if root_path is None:
            return None
        files = local_inventory(root_path) or []
    except Exception as e:
        logger.debug("[weights] dépôt frère %s illisible en local : %s", repo, e)
        return None
    total = sum(t for _, t in files)
    return round(total / 1024 ** 3, 3) if total else None


def _with_sibling_repos(out: dict, composition) -> dict:
    """Ajoute les composants déclarés par DÉPÔT au relevé — leur poids vit ailleurs.

    Mesuré le 2026-09-19 : sans ça, `transcriber:pyannote-diarization` (deux dépôts frères),
    `avatarizer:codeformer` et les trois DeepFace rendaient « aucun poids » — leur dépôt
    principal ne porte que des fichiers de configuration. Une composition VALIDE et un relevé
    VIDE : le pire cas, puisque rien ne le signalait.

    ⚠ Sur ces 5 déclarations, cette lecture ne PÈSE toujours rien, et c'est exact : pyannote est
    GATED (l'API rend 401), `serengil/deepface_models` et TripoSR ne sont pas des dépôts de
    modèles HF (releases GitHub, URL de dépôt de code). Ce que le correctif change n'est donc pas
    le chiffre, c'est le DIAGNOSTIC : `unresolved` nomme les rôles impesables au lieu de laisser
    croire qu'il n'y a rien à peser. *Ma première rédaction annonçait « 5 déclarations servies » —
    corrigé après mesure : 5 déclarations LUES, 0 pesée, 5 nommées.*

    ⚠ `unresolved` est la clé qui sauve l'appelant : un dépôt injoignable ou non-HF (TripoSR
    déclare une URL GitHub) laisse un rôle SANS poids, et une somme incomplète ne doit jamais
    être prise pour une empreinte. Dire lesquels manquent vaut mieux qu'un total optimiste.
    """
    repos = [(c.get('role') or _SINGLE_ROLE, c['repo'])
             for c in ((composition or {}).get('components') or [])
             if isinstance(c, dict) and c.get('repo') and not c.get('pattern')]
    if not repos:
        return out
    from .prospector import _repo_weight_gb

    parts = dict((out or {}).get('components') or {})
    unresolved = list((out or {}).get('unresolved') or [])
    # ⚠ Un dépôt principal INJOIGNABLE ne doit pas masquer les composants frères qui, eux, sont
    # pesables — vécu le 2026-09-20 sur `avatarizer:codeformer` : ma branche `unreachable`
    # rendait la main avant d'arriver ici, et le relevé perdait ce qu'il savait. Le marqueur
    # voyage avec le résultat au lieu de l'interrompre.
    unreachable = (out or {}).get('unreachable')
    for role, repo in repos:
        gb = _local_repo_weight_gb(repo)
        if gb is None and _HF_REPO_RE.match(repo):
            gb = _repo_weight_gb(repo)
        if gb:
            parts[role] = round(parts.get(role, 0.0) + gb, 3)
        elif role not in parts:
            unresolved.append(role)
    if not parts:
        partial = {}
        if unresolved:
            partial = {'unresolved': sorted(set(unresolved)), 'source': 'declared'}
        if unreachable:
            partial['unreachable'] = unreachable
        return partial
    merged = {'components': dict(sorted(parts.items())),
              'total_gb': round(sum(parts.values()), 3),
              'largest_gb': round(max(parts.values()), 3),
              'source': (out or {}).get('source') or 'declared'}
    for carried in ('variants', 'files'):
        if (out or {}).get(carried):
            merged[carried] = out[carried]
    if unresolved:
        merged['unresolved'] = sorted(set(unresolved))
    if unreachable:
        # Le total est alors INCOMPLET du dépôt principal : le dire, ne pas le taire.
        merged['unreachable'] = unreachable
    return merged


def components_for_spec(spec: dict, *, files=None) -> dict:
    """Poids par composant de ce qu'un descripteur désigne — `{}` si indéterminable.

    JUMEAU de `weight_for_spec` (même descripteur, même dispatch par `kind`) : c'est la MÊME
    question posée un cran plus fin, elle n'a donc pas droit à une seconde porte. `weight_for_spec`
    rend le total, celle-ci rend le détail ; les deux lisent la brique de leur source, et aucune
    ne réinvente d'inventaire.

    La SÉLECTION vient du descripteur lui-même — `spec['composition']` (posée par
    `spec_for_catalog_row`) ou `spec['allow_patterns']` —, donc ce qu'on PÈSE est exactement ce
    que `install_from_spec` va TIRER. Un seul descripteur pour les deux.

    `files` : inventaire DÉJÀ relevé (snapshot local, ou `_siblings` gardé d'un appel précédent).
    Le passer évite la requête — un dépôt inventorié une fois n'a pas à l'être deux fois.

    TROIS RÉPONSES À NE PAS CONFONDRE, et c'est la raison de leurs formes :
      * `{'components': …, 'total_gb': …}` — on a pesé ;
      * `{'unresolved': [rôles]}` **sans** `total_gb` — on a pesé une PARTIE ; le total manquerait
        des composants, donc il n'est pas rendu (une somme incomplète prise pour une empreinte
        est pire qu'un trou déclaré) ;
      * `{'unreachable': ref}` — on n'a rien pu peser, le dépôt n'a pas répondu ;
      * `{}` — il n'y a rien à peser (aucun fichier de poids, aucun motif qui matche).
    Un appelant lit donc `.get('total_gb')`, jamais un `0` : ce chiffre est ABSENT quand il est
    inconnu, il ne vaut jamais zéro par défaut.
    """
    spec = spec or {}
    restriction = {'composition': spec.get('composition'),
                   'allow_patterns': spec.get('allow_patterns')}
    if files is not None:
        return _with_sibling_repos(components_of_files(files, **restriction),
                                   restriction['composition'])
    kind, ref = spec.get('kind'), (spec.get('ref') or '').strip()
    if not ref:
        # Un modèle SANS dépôt principal peut n'exister que par ses dépôts frères — les trois
        # DeepFace n'ont pas de `hf_id` du tout, leur anatomie est entièrement déportée.
        return _with_sibling_repos({}, restriction['composition'])
    if kind == 'hf':
        from .prospector import _siblings
        inventory = _siblings(ref)
        if inventory is None:
            # ⚠ `_siblings` distingue depuis le 2026-09-07 la PANNE (None) du dépôt VIDE ([]) —
            # « l'un est une panne, l'autre un fait ». Rendre `{}` dans les deux cas perdrait
            # cette distinction juste là où elle compte : un appelant lirait « ne pèse rien »
            # d'un dépôt momentanément injoignable. Vécu le 2026-09-19 sur ma propre
            # contre-épreuve : 8 déclarations VÉRIFIÉES ont été rapportées « motif sans
            # fichier » par une salve d'appels HF qui avait échoué en silence.
            # *Un relevé qui dépend du réseau doit dire quand le réseau a manqué.*
            return _with_sibling_repos({'unreachable': ref}, restriction['composition'])
        return _with_sibling_repos(components_of_files(inventory, **restriction),
                                   restriction['composition'])
    # Ollama, YOLO et un asset GitHub ne livrent PAS de composition : un blob GGUF, un `.pt`, un
    # `.onnx` — un seul composant,
    # dont le poids est celui du tout. Le dire explicitement vaut mieux que rendre `{}` : le
    # lecteur a besoin de savoir que « somme » et « plus gros » se confondent ici, pas que
    # l'information manque.
    gb = weight_for_spec(spec)
    if gb is None:
        return {}
    return {'components': {_SINGLE_ROLE: gb}, 'total_gb': gb, 'largest_gb': gb,
            'source': 'registry' if kind == 'ollama' else 'asset'}


def yolo_task_of(name: str) -> str:
    """Tâche (`ModelTask`) d'un poids YOLO, déduite du suffixe de son nom — `detect` par défaut.
    Accesseur UNIQUE : `pull_yolo_weights` en tire son sous-dossier, la proposition d'un
    candidat YOLO en tire `capabilities['task']`."""
    base = (name or '')[:-3] if (name or '').endswith('.pt') else (name or '')
    return next((d for suf, d in _YOLO_TASK_DIRS.items() if base.endswith(suf)), 'detect')


def pull_yolo_weights(name: str, timeout: int = 600, dry_run: bool = False):
    """
    Télécharge des poids YOLO OFFICIELS (assets GitHub Ultralytics, URL stable
    `releases/latest/download/<name>.pt`) DANS LE BON DOSSIER :
    `AI-models/models/vision/yolo/<task>/<name>.pt` — le sous-dossier de tâche est déduit
    du suffixe du nom (-seg/-obb/-pose/-cls, sinon detect), exactement l'arborescence que
    `model_registry` découvre au sync. Ouvre l'installation VISION du model_manager
    (l'endpoint prospect/install n'était qu'Ollama — phase 1).

    `dry_run` : ne télécharge pas, retourne la cible (valide la logique de chemin).
    Retourne {'ok': bool, 'path'|'target'|'error': …}. Idempotent : fichier déjà présent → ok.
    """
    import os
    import re
    from django.conf import settings

    base = name[:-3] if name.endswith('.pt') else name
    # Noms officiels uniquement (yolo11s-seg, yolo26x, yolov12n-seg…) — pas d'URL arbitraire.
    if not re.fullmatch(r'yolo[a-z0-9._\-]+', base, re.IGNORECASE):
        return {'ok': False, 'error': f"nom de poids YOLO invalide: {name!r}"}
    task = yolo_task_of(base)
    target_dir = os.path.join(str(settings.AI_MODELS_DIR), 'models', 'vision', 'yolo', task)
    target = os.path.join(target_dir, f"{base}.pt")
    if dry_run:
        return {'ok': True, 'target': target, 'dry_run': True}
    if os.path.exists(target):
        return {'ok': True, 'path': target, 'already': True}

    os.makedirs(target_dir, exist_ok=True)
    from wama.common.external_sources import proxies_for
    # Garde-fou : une page d'erreur HTML ferait un .pt de quelques Ko.
    return download_asset(_yolo_asset_url(base), target, timeout=timeout,
                          min_bytes=1_000_000, proxies=proxies_for('github'))


# ── Pilote `github` — des poids publiés dans une VERSION GitHub (2026-10-07) ─────────────────
# Le pilote `yolo` ci-dessus EST déjà un asset de version GitHub, verrouillé sur
# `ultralytics/assets` et sur « latest ». Celui-ci reproduit son comportement (dossier canonique,
# idempotence, téléchargement contrôlé) et l'adapte à un dépôt quelconque, avec les verrous de la
# voie VENDOR transposés (`library.vendor_spec_error`) : pas d'URL libre — le dépôt se dit
# « owner/name » (la MÊME règle, importée), l'adresse se dérive de la source déclarée `github`.
# Une différence assumée : la voie vendor exige un COMMIT parce qu'un tag bouge ; une version
# GitHub, elle, s'ADRESSE par son tag. La garantie que donne le commit vient ici de l'EMPREINTE
# épinglée (`sha256`, publiée par l'API GitHub) : un tag déplacé servirait un autre fichier, et
# ce fichier serait refusé.
#
# Un dépôt n'est PAS un modèle : `Phhofm/models` en publie des centaines, une version chacun.
# Le modèle est donc la VERSION (`ref` = « owner/repo:tag »), et `asset` choisit le fichier
# (fp32/fp16…), comme `allow_patterns` choisit dans un dépôt HF.
#
# Disposition, calquée sur celle de HuggingFace (décision de Fabien, 2026-10-07) :
#   HF     : <catégorie>/<famille ou nom court>/models--org--nom/snapshots/<rév.>/<fichiers>
#   GitHub : <catégorie>/<famille ou tag>/github--owner--repo/<tag>/<asset>

#: Le tag entre dans la CLÉ du modèle (`github:owner/repo:tag`) : il n'admet que ce qu'une clé de
#: manifeste admet (`ingest`, « alphanumérique + -_:./ »), sans « / » ni « : » (séparateurs).
_GITHUB_TAG_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$')
_GITHUB_ASSET_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.+-]*$')
_SHA256_RE = re.compile(r'^[0-9a-fA-F]{64}$')
GITHUB_SPEC_FIELDS = ('ref', 'asset', 'sha256')


def github_release_of(ref: str) -> tuple:
    """`owner/repo:tag` → (`owner/repo`, `tag`) ; ('', '') si la forme n'y est pas."""
    repo, sep, tag = str(ref or '').strip().partition(':')
    return (repo, tag) if sep else ('', '')


#: `platform_ref` d'une version : la page de la version, que la fiche déclarée de la plateforme
#: `github` (`external_sources.model_page_url`) rend telle quelle.
_GITHUB_RELEASE_PAGE = '{repo}/releases/tag/{tag}'


def github_platform_ref(ref: str) -> str:
    """`owner/repo:tag` → `github:owner/repo/releases/tag/<tag>` ('' si la forme n'y est pas)."""
    repo, tag = github_release_of(ref)
    return f"github:{_GITHUB_RELEASE_PAGE.format(repo=repo, tag=tag)}" if repo and tag else ''


def github_ref_of_platform(platform_ref: str) -> str:
    """L'inverse : `github:owner/repo/releases/tag/<tag>` → `owner/repo:tag`, sinon ''."""
    platform, _, ident = str(platform_ref or '').partition(':')
    repo, sep, tag = ident.partition('/releases/tag/')
    return f"{repo}:{tag}" if platform == 'github' and sep and repo and tag else ''


def github_release_error(ref) -> str | None:
    """Motif de refus d'une version désignée `owner/repo:tag`, ou None (pur, aucune I/O)."""
    from wama.common.manifests.builtin.library import _VENDOR_REPO_RE

    repo, tag = github_release_of(ref)
    if not _VENDOR_REPO_RE.match(repo) or '..' in repo:
        return (f"ref refusé : {ref!r} — forme exigée « owner/name:tag » (GitHub, "
                "sans URL : l'adresse se dérive de la source déclarée `github`)")
    if not _GITHUB_TAG_RE.match(tag) or tag.lower() == 'latest':
        return (f"tag refusé : {tag!r} — le tag EXACT de la version (jamais « latest », qui "
                "désigne une version différente demain), sans « / »")
    return None


def github_spec_error(spec: dict):
    """Motif de refus d'un descripteur `github`, ou None — pendant de `vendor_spec_error`.

    Pur (aucune I/O) : l'installation, la pesée et la prospection appliquent le même verrou.
    """
    spec = spec or {}
    error = github_release_error(spec.get('ref'))
    if error:
        return error
    asset = str(spec.get('asset') or '')
    if not _GITHUB_ASSET_RE.match(asset) or '..' in asset:
        return f"asset refusé : {asset!r} — le NOM d'un fichier de la version, sans chemin"
    if not _SHA256_RE.match(str(spec.get('sha256') or '')):
        return ("sha256 manquant ou invalide — l'empreinte publiée de l'asset (64 caractères "
                "hexadécimaux, `digest` de l'API GitHub) : sans elle, rien ne garantit qu'on "
                "installe ce qui a été jugé")
    if not spec.get('category'):
        return "category requis — la catégorie WAMA du dossier (`model_locations`)"
    return None


def github_asset_url(spec: dict) -> str:
    """Adresse de téléchargement de l'asset, dérivée de la source déclarée `github` (comme
    `vendor_installer.repo_url`) — jamais écrite en dur, jamais fournie par l'appelant."""
    from wama.common.external_sources import base_url
    repo, tag = github_release_of(spec.get('ref'))
    return f"{base_url('github')}/{repo}/releases/download/{tag}/{spec['asset']}"


def github_release_dir(spec: dict) -> str:
    """Dossier du modèle : `<catégorie>/<famille ou tag>/github--owner--repo/<tag>`."""
    from wama.common.utils.model_locations import github_folder_name, model_dir
    repo, tag = github_release_of(spec.get('ref'))
    cache = model_dir(spec['category'], spec.get('family') or tag)
    return os.path.join(str(cache), github_folder_name(repo), tag)


#: L'empreinte d'un fichier en place est celle de la brique commune (`provenance.sha256_of`),
#: SANS son plafond de 512 Mo — un poids se vérifie quelle que soit sa taille ; '' (illisible) ne
#: vaut jamais une empreinte épinglée. (2026-10-10 : une copie locale du calcul vivait ici.)
_NO_SIZE_CAP = float('inf')


def pull_github_asset(spec: dict, timeout: int = 600, dry_run: bool = False) -> dict:
    """Télécharge l'asset d'une version GitHub DANS LE BON DOSSIER (cf. l'en-tête du pilote).

    Le comportement de `pull_yolo_weights`, adapté : `dry_run` rend la cible ; un fichier déjà
    présent est rendu `already` — mais seulement s'il porte l'empreinte épinglée : un fichier
    DIFFÉRENT à cette place n'est ni repris ni écrasé, il est DIT (on ne remplace pas en silence
    ce qu'on n'a pas installé). Retourne {'ok': bool, 'path'|'target'|'error': …}.
    """
    error = github_spec_error(spec)
    if error:
        return {'ok': False, 'error': error}
    release = github_release_dir(spec)
    target = os.path.join(release, spec['asset'])
    if dry_run:
        return {'ok': True, 'target': target, 'dry_run': True}
    if os.path.exists(target):
        from wama.common.utils.provenance import sha256_of
        if sha256_of(target, limite=_NO_SIZE_CAP) == spec['sha256'].lower():
            return {'ok': True, 'path': target, 'already': True}
        return {'ok': False,
                'error': f"{target} existe avec une AUTRE empreinte que celle épinglée — "
                         "le retirer (désinstallation) avant de réinstaller"}
    os.makedirs(release, exist_ok=True)
    from wama.common.external_sources import proxies_for
    return download_asset(github_asset_url(spec), target, timeout=timeout,
                          sha256=spec['sha256'], proxies=proxies_for('github'))


# ── Pilote `files` — les fichiers qu'une app DÉCLARE, chacun avec son ORIGINE (2026-10-11) ────
# Né le 2026-10-10 comme variante du pilote `github` (CodeFormer : son code vendorisé lit une
# disposition FIXE, l'app déclare les fichiers et leur place sous son dossier). Mais les poids
# d'un même moteur viennent souvent de PLUSIEURS sources — mesuré le 11/10 : MuseTalk lit quatre
# dépôts du Hub, un poids de torchvision et un détecteur publié par l'auteur de sa librairie ;
# l'enhancer, un miroir du Hub ; Face Analyzer, le serveur de modèles de MediaPipe.
# Décision de Fabien (11/10) : chaque fichier NOMME son origine, parmi les sources DÉCLARÉES
# (`external_sources`) — la version officielle quand elle existe, sinon un miroir, accepté
# seulement aux octets déjà jugés (l'empreinte épinglée). La provenance voyage avec le fichier :
# déclarée par l'app, posée sur la ligne du catalogue (`extra_info['declared_files']`), rendue
# fichier par fichier dans le résultat (donc dans le journal des installations).
#
# Trois formes d'origine, toutes FIGÉES — pas d'URL libre, jamais « latest » ni une branche :
#   {'source': 'huggingface', 'repo': 'org/nom', 'revision': '<commit, 40 hex>', 'file': 'a/b'}
#   {'source': 'github', 'release': 'owner/repo:tag', 'file': '<nom de l'asset>'}
#   {'source': '<source déclarée « Outillage et poids »>', 'file': '<chemin sous son adresse>'}
# Verrous communs : empreinte ET taille épinglées (la taille nourrit la garde d'espace disque),
# chemin RELATIF sous le dossier de l'app, lui-même sous la racine des modèles, téléchargement
# commun (`download_asset`), un fichier DIFFÉRENT en place arrête tout avant le moindre octet.

#: Une révision du Hub se fige par son COMMIT : une branche (`main`) sert d'autres octets demain.
_HF_COMMIT_RE = re.compile(r'^[0-9a-f]{40}$')

#: Famille des sources dont un fichier peut être tiré à adresse fixe (`external_sources.KINDS`).
_FILE_HOST_KIND = 'poids'


def _relative_path_error(path) -> bool:
    parts = str(path or '').split('/')
    return not path or any(not _GITHUB_ASSET_RE.match(p) or '..' in p for p in parts)


def declared_origin_error(origin) -> str | None:
    """Motif de refus de l'ORIGINE d'un fichier déclaré, ou None (pur, aucune I/O)."""
    from wama.common.external_sources import by_key
    from wama.common.manifests.builtin.library import _VENDOR_REPO_RE

    origin = origin if isinstance(origin, dict) else {}
    source, file = origin.get('source') or '', str(origin.get('file') or '')
    if source == 'huggingface':
        repo = str(origin.get('repo') or '')
        if not _VENDOR_REPO_RE.match(repo) or '..' in repo:
            return f"dépôt refusé : {repo!r} — forme exigée « org/nom »"
        if not _HF_COMMIT_RE.match(str(origin.get('revision') or '')):
            return ("revision : le COMMIT exact du dépôt (40 hex), jamais une branche — « main » "
                    "sert d'autres octets demain")
        return f"file refusé : {file!r}" if _relative_path_error(file) else None
    if source == 'github':
        error = github_release_error(origin.get('release'))
        if error:
            return error
        return None if _GITHUB_ASSET_RE.match(file) else f"asset refusé : {file!r}"
    declared = by_key().get(source)
    if declared is None or declared.kind != _FILE_HOST_KIND:
        return (f"source refusée : {source!r} — `huggingface`, `github` ou une source DÉCLARÉE "
                "de la famille « Outillage et poids » (`external_sources`)")
    return f"file refusé : {file!r}" if _relative_path_error(file) else None


def declared_files_error(spec: dict) -> str | None:
    """Motif de refus d'un descripteur `files`, ou None — pur : l'installation et la pesée
    appliquent le même verrou."""
    spec = spec or {}
    files = spec.get('files')
    if not isinstance(files, list) or not files:
        return "files : une liste non vide de {path, size, sha256, origin}"
    for f in files:
        f = f if isinstance(f, dict) else {}
        path = str(f.get('path') or '')
        if _relative_path_error(path):
            return (f"fichier refusé : {path!r} — un chemin RELATIF sous le dossier de l'app, "
                    "sans « .. »")
        if not _SHA256_RE.match(str(f.get('sha256') or '')):
            return f"sha256 manquant ou invalide pour {path!r} — l'empreinte épinglée"
        if not isinstance(f.get('size'), int) or f['size'] <= 0:
            return (f"size manquante pour {path!r} — la taille MESURÉE (la garde d'espace "
                    "disque la somme, elle ne suppose rien)")
        error = declared_origin_error(f.get('origin'))
        if error:
            return f"{path} : {error}"
    if not spec.get('target_dir'):
        return "target_dir requis — le dossier de l'app (`install_dir` de sa découverte)"
    return None


def declared_file_url(origin: dict) -> str:
    """Adresse d'un fichier déclaré, DÉRIVÉE de sa source déclarée — jamais écrite en dur."""
    from wama.common.external_sources import base_url
    source, file = origin['source'], origin['file']
    if source == 'huggingface':
        return f"{base_url('huggingface')}/{origin['repo']}/resolve/{origin['revision']}/{file}"
    if source == 'github':
        return github_asset_url({'ref': origin['release'], 'asset': file})
    return f"{base_url(source)}/{file}"


def declared_files_present(install_dir, files) -> bool:
    """Tous les fichiers déclarés sont-ils à leur place ? (présence, sans relire l'empreinte —
    c'est la découverte qui demande, à chaque synchro ; l'installation, elle, vérifie)."""
    return bool(files) and all((Path(install_dir) / f['path']).exists() for f in files)


def _declared_targets(model) -> tuple[Path, list] | None:
    """Le dossier et les fichiers qu'une ligne DÉCLARE (`install_dir` + `declared_files`), ou
    None si elle n'en déclare pas ou qu'un chemin sort de son dossier."""
    info = model.extra_info or {}
    files, install_dir = info.get('declared_files'), (info.get('install_dir') or '').strip()
    if not files or not install_dir:
        return None
    if any(_relative_path_error(str((f or {}).get('path') or '')) for f in files):
        return None
    root = Path(install_dir)
    return root, [root / f['path'] for f in files]


def remove_declared_files(model, include_shared: bool = False) -> dict:
    """Le pendant de `pull_declared_files` pour la désinstallation : retire EXACTEMENT les
    fichiers que la ligne déclare, jamais son dossier — l'enhancer range ses sept modèles dans un
    seul dossier, MuseTalk y garde des poids non déclarés (SyncNet, entraînement seul).

    Un fichier qu'une AUTRE ligne installée déclare aussi est partagé : refus qui la nomme
    (`needs_confirmation`), comme pour un dossier, tant que `include_shared` n'est pas donné.
    Les dossiers vidés par le retrait partent avec lui, jusqu'au dossier de l'app (exclu).
    Rend {'ok', 'freed_gb', 'sharing'} ou {'ok': False, 'error', …}."""
    from wama.common.utils.model_locations import models_root

    from ..models import AIModel, EXECUTION_LOCAL

    declared = _declared_targets(model)
    if declared is None:
        return {'ok': False, 'error': f"« {model.name} » ne déclare aucun fichier retirable."}
    root, targets = declared
    try:
        root.resolve().relative_to(models_root().resolve())
    except (ValueError, OSError):
        return {'ok': False, 'error': f"chemin hors de la racine des modèles : {root}"}
    mine = {t.resolve() for t in targets}
    sharing = []
    others = (AIModel.objects.filter(is_downloaded=True, is_proposed=False,
                                     execution=EXECUTION_LOCAL, extra_info__has_key='declared_files')
              .exclude(pk=model.pk))
    for other in others:
        theirs = _declared_targets(other)
        if theirs and mine & {t.resolve() for t in theirs[1]}:
            sharing.append(other)
    if sharing and not include_shared:
        names = [m.name for m in sharing]
        return {'ok': False, 'needs_confirmation': True, 'sharing': names, 'dependents': [],
                'error': "ces fichiers sont AUSSI ceux de : " + ', '.join(names)
                         + " — ils seront désinstallés ensemble."}
    loaded = [m.name for m in sharing if m.is_loaded]
    if loaded:
        return {'ok': False, 'error': f"« {', '.join(loaded)} » partage ces fichiers et est "
                                      "chargé en mémoire — le décharger d'abord."}
    freed = 0
    for target in targets:
        if target.is_file() and not target.is_symlink():
            freed += target.stat().st_size
        if target.is_file() or target.is_symlink():
            target.unlink()
        parent = target.parent
        while parent != root and root in parent.parents:
            try:
                parent.rmdir()               # seulement s'il est VIDE
            except OSError:
                break
            parent = parent.parent
    return {'ok': True, 'freed_gb': freed / 1024 ** 3, 'sharing': sharing}


def pull_declared_files(spec: dict, timeout: int = 600, dry_run: bool = False,
                        token: str | None = None) -> dict:
    """Les fichiers qu'une app DÉCLARE, posés SOUS son dossier (`target_dir`), chacun tiré de
    son ORIGINE déclarée (cf. l'en-tête du pilote).

    `token` (2026-10-16, MuScriptor) : le jeton Hugging Face du téléchargement, envoyé aux SEULES
    origines `huggingface` — un dépôt à accès contrôlé répond 401 sans lui. Jamais aux autres
    sources : un secret ne part que là où il sert.

    Un fichier présent à la bonne empreinte est gardé ; un fichier présent à une AUTRE empreinte
    arrête tout AVANT le moindre téléchargement (on ne remplace pas en silence ce qu'on n'a pas
    installé, et on ne laisse pas une installation à moitié). Le résultat rend la provenance de
    chaque fichier (`files` : chemin, adresse, empreinte, `kept`|`downloaded`).
    """
    from wama.common.utils.model_locations import models_root

    error = declared_files_error(spec)
    if error:
        return {'ok': False, 'error': error}
    root = Path(spec['target_dir'])
    try:
        root.resolve().relative_to(models_root().resolve())
    except (ValueError, OSError):
        return {'ok': False, 'error': f"{root} hors de la racine des modèles — refusé"}
    targets = [(f, root / f['path']) for f in spec['files']]
    if dry_run:
        return {'ok': True, 'target': str(root), 'files': [str(t) for _, t in targets],
                'dry_run': True}
    from wama.common.utils.provenance import sha256_of
    kept, missing = [], []
    for f, target in targets:
        if target.exists():
            if sha256_of(target, limite=_NO_SIZE_CAP) != f['sha256'].lower():
                return {'ok': False,
                        'error': f"{target} existe avec une AUTRE empreinte que celle épinglée "
                                 "— le retirer avant de réinstaller"}
            kept.append((f, target))
        else:
            missing.append((f, target))
    from wama.common.external_sources import proxies_for

    def provenance(f, target, action):
        return {'path': str(target), 'url': declared_file_url(f['origin']),
                'sha256': f['sha256'].lower(), 'action': action}

    done = [provenance(f, t, 'kept') for f, t in kept]
    for f, target in missing:
        target.parent.mkdir(parents=True, exist_ok=True)
        hub = f['origin']['source'] == 'huggingface'
        res = download_asset(declared_file_url(f['origin']), str(target), timeout=timeout,
                             sha256=f['sha256'], proxies=proxies_for(f['origin']['source']),
                             headers={'Authorization': f'Bearer {token}'} if hub and token else None)
        if not res.get('ok'):
            return {'ok': False, 'error': res.get('error'), 'files': done}
        done.append(provenance(f, target, 'downloaded'))
    downloaded = [d['path'] for d in done if d['action'] == 'downloaded']
    return {'ok': True, 'path': str(root), 'files': done, 'downloaded': downloaded,
            'kept': [str(t) for _, t in kept], 'already': not downloaded}


def download_asset(url: str, target: str, *, timeout: int = 600, min_bytes: int = 0,
                   sha256: str = '', proxies=None, headers=None) -> dict:
    """Télécharge UN fichier publié (asset de version GitHub…) vers `target`, sans jamais laisser
    un fichier partiel à sa place : écriture dans `<target>.part`, contrôles, puis remplacement
    atomique. Retourne {'ok': True, 'path', 'url', 'sha256'} (l'empreinte calculée au fil du
    flux — un appelant qui la MESURE n'a pas à relire le fichier) ou {'ok': False, 'error'},
    sans lever.

    Extrait de `pull_yolo_weights` le 2026-10-07 (pilote `github` : deux pilotes, un corps) —
    c'était le seul téléchargement de qualité installeur du dépôt ; les téléchargeurs écrits
    par app (enhancer, anonymizer, cam_analyzer) n'ont ni partiel ni contrôle.

    Contrôles, du plus faible au plus fort :
      • `min_bytes` : une page d'erreur HTML servie à la place du fichier pèse quelques Ko ;
      • `sha256` : l'empreinte ÉPINGLÉE (publiée par l'API GitHub, `digest`). Un écart refuse le
        fichier : c'est la garantie qu'on installe ce qui a été jugé, pas ce que le serveur
        sert aujourd'hui.
    `proxies` : ceux de la source déclarée (`external_sources.proxies_for`) ; None = l'environnement.
    `headers` : ceux de la requête (le jeton d'un dépôt à accès contrôlé) — `requests` ne les
    renvoie pas vers un autre hôte quand le Hub redirige vers son stockage.
    """
    import hashlib

    import requests

    tmp = target + '.part'
    try:
        digest = hashlib.sha256()
        with requests.get(url, stream=True, timeout=timeout, allow_redirects=True,
                          proxies=proxies, headers=headers) as r:
            r.raise_for_status()
            with open(tmp, 'wb') as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
                    digest.update(chunk)
        size = os.path.getsize(tmp)
        if size < min_bytes:
            os.remove(tmp)
            return {'ok': False,
                    'error': f"téléchargement suspect (<{min_bytes / 1e6:g} Mo) — "
                             f"poids inexistant ? {url}"}
        if sha256 and digest.hexdigest() != sha256.lower():
            os.remove(tmp)
            return {'ok': False,
                    'error': f"empreinte différente de celle épinglée ({sha256[:12]}… attendu, "
                             f"{digest.hexdigest()[:12]}… reçu) — fichier refusé : {url}"}
        os.replace(tmp, target)
        return {'ok': True, 'path': target, 'url': url, 'sha256': digest.hexdigest()}
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def register_after_install():
    """
    Re-synchronise le catalogue `AIModel` pour que le modèle fraîchement installé apparaisse.
    Réutilise `full_sync` (clean=False : ne touche pas aux autres sources). Retourne le résumé.
    """
    from .model_sync import ModelSyncService
    return ModelSyncService().full_sync()


def replaced_model(cand):
    """
    (nom Ollama de l'ancien modèle, espace qu'il rendra en Go) pour un candidat successeur,
    sinon (None, 0.0).

    La prospection écrit l'origine dans `extra_info['prospect']['origin_key']` quand elle a
    identifié une famille supérieure — c'est ce lien qui rend le remplacement possible sans
    demander à l'utilisateur de désigner lui-même ce qu'il faut retirer.
    (Migré depuis views.py le 2026-08-18 : la tâche Celery d'install en a besoin autant
    que la garde d'espace de la vue.)
    """
    from ..models import AIModel
    prospect = (cand.extra_info or {}).get('prospect', {})
    origine, cible = prospect.get('origin_key'), prospect.get('cible')
    if not origine or not cible or cand.proposal_kind != 'update':
        return None, 0.0
    # Un successeur HUGGING FACE (`prospector.seed_hf_successors`, 2026-10-10) n'entraîne aucun
    # retrait : `install_candidate` l'installe par son spec, l'ancien reste en place. Compter son
    # espace comme rendu ferait passer la garde de disque sur un espace qui ne se libère pas.
    if ((prospect.get('spec') or {}).get('kind') or 'ollama') != 'ollama':
        return None, 0.0
    ancien =AIModel.objects.filter(model_key=origine, is_proposed=False).first()
    if ancien is None:
        return None, 0.0
    nom = origine.split(':', 1)[1] if ':' in origine else ancien.name
    # Garde-fou : sans `cible`, un candidat « âge seul » porte le nom du modèle EXISTANT, et la
    # séquence retirerait puis re-tirerait le même modèle — churn pur, avec la fenêtre de risque
    # d'une restauration. On ne remplace que si la cible est réellement un AUTRE modèle.
    if nom == cand.name:
        return None, 0.0
    return nom, float(ancien.disk_gb or 0)


#: Marge laissée libre sur le volume APRÈS une installation (Go). Déménagée de
#: `views.MARGE_DISQUE_GO` le 2026-09-19 : la garde d'espace est désormais partagée par la
#: vue (bouton « Installer ») et l'outil de l'AI-Assistant — un seuil ne vit qu'à UN endroit.
DISK_MARGIN_GB = 10.0


def disk_space_guard(ref: str, *, reclaim_gb: float = 0.0, force: bool = False,
                     needed_gb: float | None = None):
    """
    Refuse une installation qui saturerait le volume. Retourne None si l'installation peut
    passer, sinon le dict d'erreur à renvoyer tel quel.

    `reclaim_gb` : espace que la DÉSINSTALLATION préalable de l'ancien modèle rendra. Sans ce
    paramètre, le garde refusait un REMPLACEMENT pourtant légitime — cas réel mesuré :
    qwen3.5:35b-a3b (22,2 Go) → qwen3.6:35b (22,3 Go) sur 23,7 Go libres. Le calcul naïf
    (23,7 − 22,3 = 1,4 Go) refuse ; le calcul juste (23,7 + 22,2 − 22,3 = 23,6 Go) accepte.

    Réutilise `SystemMonitor.get_disk_info()` (brique existante, WSL-aware : elle interroge
    l'hôte Windows) — aucune mesure de stockage n'est réécrite ici. `AI-models` et
    `D:\\.ollama\\models` sont sur le MÊME volume, un seul contrôle suffit donc.

    Taille INDÉTERMINABLE = refus, pas passage en force : sur un volume déjà à 96 %, supposer
    une taille optimiste revient à remplir le disque.

    POURQUOI cette garde existe : `ollama pull` n'en a AUCUNE — il télécharge jusqu'à saturer
    le volume. Mesuré le 2026-08-04 : D: était à 96 % (23,7 Go libres) alors que `qwen3.6:35b`
    pèse 22,3 Go ; l'installation aurait laissé ~1,4 Go. Et rien n'est libéré par ailleurs —
    l'ancien modèle n'est pas supprimé et les modèles Ollama ne sont pas sauvegardés (décision
    2026-08-04, PROSPECTION_PIPELINE.md). Un disque plein ne casse pas que le téléchargement :
    il casse les journaux, les fichiers temporaires de conversion et Postgres.

    (Corps repris tel quel de `views._garde_espace_disque` le 2026-09-19 — seuls les
    identifiants passent à l'anglais : `besoin_gb` → `needed_gb`, clé `raison` → `reason`.
    Aucun consommateur JS ne lisait `raison` : le 507 ne lit que `error` et `force_possible`.)
    """
    from wama.common.services.system_monitor import SystemMonitor

    from .ollama_registry import size_gb

    # `needed_gb` fourni (candidat HF : poids `usedStorage` relevé à la prospection) →
    # pas d'interrogation du registre Ollama, qui ne connaît pas ces modèles.
    # ⚠ `is not None`, pas la vérité du nombre (mesuré le 2026-09-30, relevé par une autre
    # instance) : un dépôt de PIPELINE léger (pyannote community-1, ~27 Mo) pèse 0,0 Go une fois
    # arrondi — une taille CONNUE. `if needed_gb:` la prenait pour une absence, interrogeait le
    # registre Ollama sur une référence HuggingFace, et refusait l'installation pour « taille
    # indéterminable ». L'inconnu, lui, reste `None` (`weight_for_spec`) et reste refusé.
    if needed_gb is not None:
        needed = float(needed_gb)
    else:
        nom, _, tag = ref.partition(':')
        needed = size_gb(nom, tag or 'latest')
    disque = SystemMonitor.get_disk_info()
    if disque is None:
        return None if force else {
            'success': False, 'error': "Espace disque non mesurable — installation refusée.",
            'reason': 'disque_inconnu', 'force_possible': True}

    libre = float(disque.get('free_gb') or 0)
    if needed is None:
        return None if force else {
            'success': False,
            'error': (f"Taille de « {ref} » indéterminable (manifeste illisible) ; "
                      f"{libre:.1f} Go libres. Installation refusée par précaution."),
            'reason': 'taille_inconnue', 'free_gb': libre, 'force_possible': True}

    reste = libre + float(reclaim_gb or 0) - needed
    if reste < DISK_MARGIN_GB and not force:
        detail = (f" (après libération de {reclaim_gb:.1f} Go par l'ancien modèle)"
                  if reclaim_gb else "")
        return {
            'success': False,
            'error': (f"Espace insuffisant : « {ref} » pèse {needed:.1f} Go, il reste "
                      f"{libre:.1f} Go sur {disque.get('drive', 'le volume')}{detail} — après "
                      f"installation il ne resterait que {reste:.1f} Go "
                      f"(marge requise : {DISK_MARGIN_GB:.0f} Go)."),
            'reason': 'espace_insuffisant',
            'needed_gb': needed, 'free_gb': libre, 'reclaim_gb': round(float(reclaim_gb or 0), 1),
            'after_gb': round(reste, 1),
            'margin_gb': DISK_MARGIN_GB, 'force_possible': True}
    return None


def _persist_variant_choice(cand, variant_ref: str, variant_file: str):
    """
    Persiste le choix de variante VALIDÉ dans le spec du candidat et rend le poids de CE
    choix en Go (None = inconnu → la garde refusera, forçable). Rend `False` si le choix
    est inconnu du candidat.

    Le choix est PERSISTÉ parce que la tâche Celery relit le candidat en base : c'est ce qui
    fait respecter la sélection de l'utilisateur de bout en bout (2026-08-27 — le juge évalue
    la faisabilité VRAM sur les variantes quantisées, mais l'installation tirait TOUJOURS les
    poids pleins du dépôt canonique ; vécu MiniMax-Music3, 54 Go inexploitables sur 24 Go).
    """
    from .prospector import spec_for_choice

    spec = spec_for_choice(cand, variant_ref, variant_file)
    if spec is None:
        return False
    info = dict(cand.extra_info or {})
    prospect = dict(info.get('prospect') or {})
    prospect['spec'] = spec
    prospect['chosen_variant'] = {'ref': variant_ref, 'file': variant_file}
    info['prospect'] = prospect
    cand.extra_info = info
    cand.save(update_fields=['extra_info'])

    # La garde d'espace se calcule sur le POIDS DU CHOIX, pas sur les poids pleins.
    variantes = {v['hf_id']: v for v in (prospect.get('quant_variants') or [])}
    if variant_file:
        # Un fichier du dépôt du candidat lui-même (dépôt GGUF) ou d'une variante.
        chosen_files = (prospect.get('own_gguf') if variant_ref == cand.hf_id
                        else variantes.get(variant_ref, {}).get('files'))
        tailles = {f['file']: f['gb'] for f in (chosen_files or [])}
        return tailles.get(variant_file) or None
    if variant_ref != cand.hf_id:
        return (variantes.get(variant_ref) or {}).get('disk_gb') or None
    return cand.disk_gb or None


def similar_model_keys(key: str, limit: int = 3) -> list[str]:
    """Les clés du catalogue (propositions comprises) qui désignent le MÊME dépôt ou le même nom
    qu'une clé introuvable : la partie après le dernier `:` (`org/dépôt`, ou un nom), comparée au
    `hf_id`, à la fin de la clé et au nom. Vide quand rien ne correspond."""
    from ..models import AIModel
    tail = (key or '').rsplit(':', 1)[-1].strip()
    if not tail:
        return []
    from django.db.models import Q
    match = Q(hf_id__iexact=tail) | Q(model_key__iendswith=f':{tail}') | Q(name__iexact=tail)
    near = list(AIModel.objects.filter(match).exclude(model_key=key)
                .order_by('-is_proposed', 'model_key')
                .values_list('model_key', flat=True)[:limit])
    return near or variant_owner_keys(tail)[:limit]


def variant_owner_keys(repo: str) -> list[str]:
    """Les propositions dont `repo` est une VARIANTE quantisée (`prospect.quant_variants`) — la clé
    à installer, `repo` passant en `variant_ref`. Fil n° 41 (2026-10-11) : Albert a lu une variante
    dans les options, puis l'a demandée comme une clé (`proposed:hf:<variante>`), refusée sans
    dire laquelle la portait."""
    from ..models import AIModel
    if '/' not in (repo or ''):
        return []
    rows = AIModel.objects.filter(is_proposed=True,
                                  extra_info__prospect__quant_variants__contains=[{'hf_id': repo}])
    return list(rows.order_by('model_key').values_list('model_key', flat=True))


def request_install(model_key: str, *, force: bool = False, variant_ref: str = '',
                    variant_file: str = '', user=None, via: str = '') -> dict:
    """
    DEMANDE d'installation par CLÉ — corps unique du geste « Installer » : choix de variante,
    garde d'espace disque, idempotence, puis dispatch de la séquence longue en Celery.

    UNE SEULE ROUTE d'installation depuis l'extérieur (2026-09-19, alignement des routes) :
    la vue HTTP (bouton du model_manager) et l'outil de l'AI-Assistant appellent CE corps.
    Avant, la garde d'espace vivait dans la vue — un second appelant l'aurait donc sautée —
    et l'endpoint acceptait en plus un `spec` NU : une installation sans candidat, sans
    garde d'espace et en SYNCHRONE. `install_from_spec` reste le pilote INTERNE (appelé par
    les deux tâches Celery), il n'est plus une entrée publique.

    `model_key` : candidat de prospection (`proposed:*`) ou ligne de catalogue non téléchargée
    — c'est la même clé que porte la card, dans les deux cas. Retourne, sans jamais lever :
      {'ok': True,  'started': True,        'model_key', 'task_id'}
      {'ok': True,  'already_running': True,'model_key', 'progress'}   # un re-clic REJOINT
      {'ok': False, 'reason': 'insufficient_storage', 'blocked': {…, 'replaces': …}}
      {'ok': False, 'reason': 'not_found'|'already_downloaded'|'not_installable'
                              |'unknown_variant'|'variant_required'|'no_install_location',
       'error': …}   # variant_required : aucun choix par défaut (dépôt GGUF servi par Ollama)
    """
    from wama.common.utils.task_progress import progression_en_cours

    from ..models import AIModel
    from ..tasks import INSTALL_CACHE_PREFIX, install_catalog_task, install_proposed_task

    key = (model_key or '').strip()
    if not key:
        return {'ok': False, 'reason': 'not_found', 'error': 'model_key requis'}
    cand = AIModel.objects.filter(model_key=key, is_proposed=True).first()
    row = None if cand else AIModel.objects.filter(model_key=key, is_proposed=False).first()
    if cand is None and row is None:
        # Les clés VOISINES voyagent avec le refus : un modèle de l'assistant qui recompose la clé
        # (`reader:hf:org/dépôt` au lieu de `proposed:hf:org/dépôt`, rejeu du 2026-10-10) n'avait
        # aucun moyen de retrouver la bonne — le refus seul le laissait inventer la suivante.
        near = similar_model_keys(key)
        repo = key.rsplit(':', 1)[-1]
        owners = set(variant_owner_keys(repo)) & set(near)
        hint = (f" « {repo} » est une variante de {', '.join(sorted(owners))} : passer cette clé "
                f"en model_key, avec variant_ref={repo} et variant_file=<fichier>." if owners
                else f" Clés existantes proches : {', '.join(near)}." if near else '')
        return {'ok': False, 'reason': 'not_found',
                'error': f"Ni candidat de prospection ni modèle de catalogue : « {key} »." + hint,
                **({'similar_keys': near} if near else {})}

    replaces, reclaim_gb = None, 0.0
    if cand is not None:
        cand_spec = ((cand.extra_info or {}).get('prospect') or {}).get('spec')
        if cand.source != 'ollama' and not cand_spec:
            return {'ok': False, 'reason': 'not_installable',
                    'error': f"Candidat sans spec d'installation (source {cand.source}) "
                             "— non installable."}
        needed_gb = cand.disk_gb or None
        if not variant_ref and cand.source != 'ollama':
            # Un candidat SANS choix par défaut (dépôt GGUF servi par Ollama, 2026-10-11) : une
            # seule option la prend d'office, plusieurs se choisissent — installer « tel quel »
            # tirait le dépôt entier par le Hub, vers un dossier que rien ne lit.
            from .prospector import install_options, needs_variant_choice
            if needs_variant_choice(cand):
                options = install_options(cand)['options']
                if not options:
                    return {'ok': False, 'reason': 'not_installable',
                            'error': f"« {cand.name} » n'a aucun fichier exécutable par Ollama : "
                                     "son dépôt ne porte pas le projecteur de vision (mmproj) "
                                     "qu'exige sa tâche — installer une autre proposition."}
                if len(options) > 1:
                    return {'ok': False, 'reason': 'variant_required',
                            'error': f"« {cand.name} » se choisit ({len(options)} options : "
                                     "poids pleins par le Hub, ou fichiers exécutés par Ollama) : "
                                     "lire les options (get_install_options) et passer "
                                     "variant_ref (+ variant_file pour un fichier)."}
                variant_ref, variant_file = options[0]['ref'], options[0]['file']
        if variant_ref and cand.source != 'ollama':
            choisi = _persist_variant_choice(cand, variant_ref, variant_file)
            if choisi is False:
                return {'ok': False, 'reason': 'unknown_variant',
                        'error': f"Choix inconnu ({variant_ref}"
                                 f"{' / ' + variant_file if variant_file else ''}) "
                                 "— recharger les options."}
            needed_gb = choisi
        # REMPLACEMENT : l'espace du nouveau n'est disponible qu'APRÈS retrait de l'ancien —
        # on le compte donc dans la garde ; la séquence désinstallation → installation vit
        # dans `install_candidate` (décision 2026-08-04, PROSPECTION_PIPELINE.md).
        replaces, reclaim_gb = replaced_model(cand)
        # Le poids se demande au DESCRIPTEUR (2026-09-19, remarque de Fabien) : `weight_for_spec`
        # dispatche par `kind` comme `identity_for_spec`, au lieu que chaque appelant sache quelle
        # fonction de poids interroger pour SA source. Le relevé de la prospection (`disk_gb`) ou
        # le choix de variante priment quand ils existent — ils sont déjà mesurés, et pour une
        # variante quantisée c'est LE poids du choix, que le descripteur canonique ignore.
        ref = cand.name
        needed = needed_gb or weight_for_spec(cand_spec or {'kind': 'ollama', 'ref': cand.name})
        task, target = install_proposed_task, cand
    else:
        # LIGNE DE CATALOGUE non téléchargée (2026-08-27) : l'app déclare l'emplacement
        # (`extra_info.install_dir`, posé par sa découverte) et le spec se dérive côté serveur.
        # Cas d'origine : musicgen-melody affichait « Not downloaded » sans qu'aucun geste ne
        # permette de le télécharger.
        if row.is_downloaded:
            return {'ok': False, 'reason': 'already_downloaded',
                    'error': f"« {row.name} » est déjà téléchargé."}
        if spec_for_catalog_row(row) is None and row.source == 'ollama':
            # Une ligne Ollama DÉSINSTALLÉE ne se télécharge pas « au premier usage » : ce refus le
            # disait, et l'assistant l'a répété comme une installation faite (fil n° 41, 2026-10-11).
            # Un modèle Ollama revient par sa PROPOSITION (`pull_model` y passe aussi, 1A du 11/10).
            return {'ok': False, 'reason': 'no_install_location',
                    'error': f"« {row.name} » est un modèle Ollama retiré : il ne se réinstalle "
                             "pas tel quel ni au premier usage. Le réinstaller par une "
                             "PROPOSITION (search_models, puis install_model sur sa clé "
                             "proposed:…)."}
        if spec_for_catalog_row(row) is None:
            return {'ok': False, 'reason': 'no_install_location',
                    'error': "Ce modèle ne déclare pas d'emplacement d'installation "
                             "(hf_id/install_dir) — il se téléchargera au premier usage."}
        ref = row.hf_id or row.name
        needed = row.disk_gb or weight_for_spec(spec_for_catalog_row(row))
        task, target = install_catalog_task, row

    garde = disk_space_guard(ref, reclaim_gb=reclaim_gb, force=force, needed_gb=needed)
    if garde is not None:
        return {'ok': False, 'reason': 'insufficient_storage',
                'blocked': dict(garde, replaces=replaces)}

    # ── SÉQUENCE LONGUE → TÂCHE CELERY (2026-08-18) ─────────────────────
    # Un pull de 18 Go dans la requête dépassait le timeout du proxy Apache : le navigateur
    # recevait une page HTML d'erreur pendant que le worker continuait en aveugle, et un
    # re-clic ouvrait une requête CONCURRENTE. Désormais : réponse immédiate + avancement
    # pollable ; un re-clic REJOINT l'installation en cours (motif de `_mirror_job_start`).
    en_cours = progression_en_cours(INSTALL_CACHE_PREFIX + target.model_key)
    if en_cours:
        return {'ok': True, 'already_running': True, 'model_key': target.model_key,
                'progress': en_cours}
    # `user_id` : le téléchargement se fera avec le jeton de CETTE personne (2026-09-27,
    # `accounts.api_keys.download_token`) — la tâche relit la clé, qui ne transite jamais.
    started = dispatch_install(task, target, user_id=getattr(user, 'pk', None), via=via)
    return {'ok': True, 'started': True, 'model_key': target.model_key,
            'task_id': started.id}


def dispatch_install(task, row, *, user_id=None, via=''):
    """SEUL point de dispatch des deux tâches d'installation : ouvre l'événement DATÉ du journal,
    avec sa VOIE (`install_history.queued`), puis envoie le message — SANS argument nouveau.

    ⚠ `via` ne passe jamais dans le message Celery (mesuré le 2026-09-30) : un worker resté sur
    l'ancien code le refusait (`TypeError: unexpected keyword argument`) et l'installation
    échouait. La tâche reprend l'événement par sa clé (`install_history.resumed`)."""
    from .install_history import queued
    queued('model', row.model_key, name=row.name, via=via)
    return task.delay(row.model_key, user_id=user_id)


def install_candidate(cand, progress=None, token=None, owner=None) -> dict:
    """
    Séquence d'installation d'un CANDIDAT de prospection Ollama — corps unique, appelé par
    la tâche Celery (`install_proposed_task`, chemin normal depuis le 2026-08-18) et
    réutilisable en synchrone. La GARDE D'ESPACE DISQUE reste chez l'appelant (`request_install`,
    partagé par la vue et l'assistant) : elle doit répondre AVANT d'engager quoi que ce soit,
    parce que le 507/forçage est un dialogue utilisateur.

    Retourne {'ok': True, 'installed': nom} ou {'ok': False, 'error': …[, 'restored',
    'replaced']}. `progress(status:str)` : avancement du pull (avec pourcentage).
    `owner` : l'auteur du modèle qui naît (`install_owner`), `None` = système.
    """
    from ..models import AIModel

    # ── Candidat porteur d'un SPEC non-Ollama (génération HF…) : le driver est
    # `install_from_spec` (pull au bon dossier + sync + provenance — RÉUTILISÉ, pas
    # réécrit). Pas de séquence de remplacement ici : un SUCCESSEUR HF (`kind='update'`,
    # `seed_hf_successors`, 2026-10-10) s'installe à côté de l'ancien, qui reste en place.
    spec = (cand.extra_info or {}).get('prospect', {}).get('spec')
    if spec and spec.get('kind') and spec['kind'] != 'ollama':
        if progress:
            origin = {'github': 'GitHub', 'yolo': 'GitHub',
                      'files': 'sources déclarées'}.get(spec['kind'], 'HuggingFace')
            progress(f"téléchargement {spec.get('ref')} ({origin})…")
        res = install_from_spec(spec, token=token, owner=owner)
        if not res.get('ok'):
            return {'ok': False, 'error': res.get('error', 'installation échouée')}
        installed_name = cand.name
        cand.delete()
        return {'ok': True, 'installed': installed_name, 'path': res.get('path')}

    rollback = None
    remplace, _ = replaced_model(cand)
    origine_key = (cand.extra_info or {}).get('prospect', {}).get('origin_key')
    if remplace:
        # REMPLACEMENT : l'espace du nouveau n'est disponible qu'APRÈS retrait de l'ancien —
        # séquence désinstallation → installation (décision 2026-08-04, PROSPECTION_PIPELINE.md).
        if progress:
            progress(f"retrait de {remplace}…")
        sup = delete_ollama_model(remplace)
        if not sup.get('ok'):
            return {'ok': False,
                    'error': f"Retrait de « {remplace} » impossible : {sup.get('error')}. "
                             f"Installation annulée (l'espace n'aurait pas suffi)."}
        rollback = remplace      # à re-tirer si l'installation échoue

    # Le NOM tiré : celui du descripteur quand il en porte un (variante GGUF du Hub choisie sur un
    # candidat Hugging Face, `hf.co/<dépôt>:<quantification>` — `prospector.spec_for_choice`,
    # 2026-10-10), sinon celui du candidat Ollama, comme avant.
    pull_name = ((spec or {}).get('ref') if (spec or {}).get('kind') == 'ollama' else '') or cand.name
    res = pull_ollama_model(pull_name, progress=progress)
    if not res.get('ok') and rollback:
        # L'ancien a été retiré et le nouveau n'est pas venu : on restaure. C'est possible
        # sans sauvegarde précisément parce que `ollama pull` EST le chemin de restauration
        # (décision 2026-08-04, PROSPECTION_PIPELINE.md).
        reprise = pull_ollama_model(rollback)
        return {'ok': False,
                'error': (f"Installation de « {cand.name} » échouée : {res.get('error')}. "
                          + (f"« {rollback} » a été restauré." if reprise.get('ok')
                             else f"⚠ ÉCHEC DE LA RESTAURATION de « {rollback} » : "
                                  f"{reprise.get('error')} — à réinstaller à la main.")),
                'restored': bool(reprise.get('ok')), 'replaced': rollback}
    if not res.get('ok'):
        return {'ok': False, 'error': res.get('error', 'pull échoué')}

    # Re-synchronise pour que le modèle réel apparaisse, pose sa provenance (manifeste au
    # corpus — cette branche l'oubliait jusqu'au 2026-09-18 : aucune ligne `ollama:*` n'avait
    # de manifeste), puis retire le candidat.
    if progress:
        progress("enregistrement au catalogue…")
    # La TÂCHE du candidat voyage avec le descripteur (2026-09-19) : c'est `record_after_install`
    # qui la pose, avec ce qu'elle implique (modalités, entrées par défaut). Le candidat Ollama
    # la porte depuis sa découverte par RÔLE (`prospect_ollama`, `capabilities={'task': …}`) ;
    # sans ce transport, seule la branche HF (`spec.task`) en bénéficiait, et un modèle Ollama
    # installé repartait de ce que la découverte générique sait deviner de son nom.
    # `base_hf_id` (le modèle canonique d'un GGUF du Hub) n'entre que s'il est connu : un
    # candidat de la bibliothèque Ollama garde exactement son descripteur d'avant.
    base_hf_id = (spec or {}).get('base_hf_id') or ''
    record_provenance({'kind': 'ollama', 'ref': pull_name,
                       **({'base_hf_id': base_hf_id} if base_hf_id else {}),
                       'task': ((spec or {}).get('task')
                                or (cand.capabilities or {}).get('task') or '')}, {},
                      owner=owner)

    # RÉCONCILIER LE REMPLACÉ. `register_after_install()` → `full_sync()` n'enlève rien :
    # c'est voulu (une indisponibilité passagère ne doit pas purger le catalogue), mais ici
    # la suppression était DÉLIBÉRÉE — sans ce recalage, l'ancien modèle restait
    # `is_downloaded=True, is_available=True` alors qu'Ollama ne l'avait plus, et
    # `select_model()` pouvait désigner un modèle inexistant (constaté au test réel du
    # 2026-08-04 : `ollama:qwen3.5:35b-a3b` fantôme après son remplacement par qwen3.6:35b).
    # On MARQUE au lieu de supprimer : la ligne porte l'historique (statistiques de runtime,
    # ETA appris) qu'un `delete()` détruirait. `downloaded_only=True` suffit à l'écarter
    # de la sélection.
    if remplace and origine_key:
        maj = AIModel.objects.filter(model_key=origine_key).update(
            is_downloaded=False, is_available=False, is_loaded=False)
        logger.info("[prospect_install] %s remplacé par %s — %d ligne(s) recalée(s)",
                    origine_key, cand.name, maj)

    installed_name = pull_name
    cand.delete()
    return {'ok': True, 'installed': installed_name}


def weights_dir_of(model, index: dict | None = None) -> Path | None:
    """
    Dossier des POIDS d'une ligne de catalogue installée, ou None s'il ne se désigne pas.

    Même lien que `model_sync.persist_weights` — aucune règle de plus : `local_path` (ou
    `extra_info['path']`) s'il nomme un dépôt `models--*`, sinon l'index des snapshots
    installés par `hf_id` (`model_locations.installed_snapshots`). C'est ce qui rend
    désinstallables les modèles d'APP, qui ne portent pas leur chemin (l'imager retrouve le
    sien dans sa propre découverte : `local_path` vide).

    Dernier recours, pour une disposition hors HuggingFace (bark : `speech/bark/suno/bark_v0`) :
    le dossier DÉCLARÉ lui-même, à condition d'être au moins un cran SOUS une famille
    (`<catégorie>/<famille>/<x>`). ⚠ Jamais une racine de catégorie ou de famille : elle porte
    d'autres modèles (`speech/qwen_asr` est déclaré par les DEUX tailles de Qwen3-ASR).

    Un chemin déclaré hors de `models_root()` est rendu tel quel : c'est la garde de
    l'appelant qui le refuse, pas ce résolveur qui le masque.
    """
    from wama.common.utils.model_locations import installed_snapshots, models_root

    declared = model.local_path or (model.extra_info or {}).get('path') or ''
    path = Path(declared) if declared else None
    if path is not None and path.name.startswith('models--'):
        return path
    hf_id = (model.hf_id or '').strip().lower()
    if hf_id:
        index = installed_snapshots() if index is None else index
        if hf_id in index:
            return index[hf_id]
    if path is not None:
        try:
            relative = path.resolve().relative_to(models_root().resolve())
        except (ValueError, OSError):
            return path
        # Un DOSSIER seulement : un poids-fichier (les `.pt` YOLO de l'anonymizer) se retire par
        # son app, pas par un rm de dossier.
        if len(relative.parts) >= 3 and path.is_dir():
            return path
    return None


def _same_or_nested(a: Path, b: Path) -> bool:
    """Deux dossiers désignent-ils les mêmes fichiers (égaux, ou l'un dans l'autre) ?"""
    try:
        a, b = a.resolve(), b.resolve()
    except OSError:
        return False
    return a == b or a in b.parents or b in a.parents


def rows_depending_on(model, target: Path, index: dict | None = None) -> tuple[list, list]:
    """
    Les AUTRES lignes installées que retirer `target` toucherait — `(sharing, dependents)`.

    - `sharing` : leurs poids SONT ces fichiers. Deux lignes de catalogue sur un seul jeu de
      poids existent déjà (`ltx-…-distilled` et `…-distilled-fp8`, même dépôt : c'est la
      quantification qui les sépare). Retirer l'une retire l'autre — elles seront marquées ensemble.
    - `dependents` : leurs poids sont ailleurs, mais elles chargent CE modèle comme dorsale
      (`extra_info['base_model']` : la LoRA logo sur FLUX.1-dev). Elles restent installées,
      et deviennent inutilisables.
    """
    from wama.common.utils.model_locations import installed_snapshots

    from ..models import AIModel, EXECUTION_LOCAL

    index = installed_snapshots() if index is None else index
    hf_id = (model.hf_id or '').strip().lower()
    sharing, dependents = [], []
    others = (AIModel.objects.filter(is_downloaded=True, is_proposed=False,
                                     execution=EXECUTION_LOCAL)
              .exclude(pk=model.pk).exclude(source='ollama'))
    for other in others:
        other_dir = weights_dir_of(other, index)
        if other_dir is not None and _same_or_nested(other_dir, target):
            sharing.append(other)
        elif hf_id and str((other.extra_info or {}).get('base_model') or '').strip().lower() == hf_id:
            dependents.append(other)
    return sharing, dependents


def uninstall_model(model_key: str, include_shared: bool = False, via: str = '') -> dict:
    """
    DÉSINSTALLE un modèle du catalogue : retrait des POIDS uniquement, jamais du backend
    (léger et réutilisable — décision Fabien 2026-08-27), et recalage du catalogue dans le
    même geste. Miroir de `install_from_spec` : dispatch par nature du stockage.

      • ollama   → `DELETE /api/delete` (driver existant `delete_ollama_model`) ;
      • fichiers DÉCLARÉS (pilote `files`, 2026-10-12) → `remove_declared_files` : ces fichiers-là
                   seulement, leur dossier est partagé (enhancer) ou en porte d'autres (MuseTalk) ;
      • fichiers → suppression du dossier résolu par `weights_dir_of` (+ ses verrous `.locks`).
                   Couvre depuis le 2026-09-28 les modèles d'APP (imager, synthesizer,
                   transcriber…), qui étaient refusés faute de porter leur chemin — décision
                   de Fabien : désinstaller depuis le model_manager, comme on y installe.

    POIDS PARTAGÉS (2026-09-28) : si d'autres lignes installées vivent sur ces mêmes fichiers
    ou s'en servent de dorsale (`rows_depending_on`), le retrait est REFUSÉ en les nommant
    (`needs_confirmation`) tant que `include_shared` n'est pas donné. Une fois confirmé, les
    lignes qui partagent les fichiers sont marquées avec celle-ci ; les dépendantes, non (leurs
    poids restent), mais elles sont citées dans le résultat.

    La ligne de catalogue est MARQUÉE (`is_downloaded=False`), jamais supprimée : elle porte
    l'historique (statistiques de runtime, ETA appris, identité/licence) — même doctrine que
    le remplacement de `install_candidate`. Un modèle déclaré par une app revient d'ailleurs
    au prochain sync (non téléchargé) ; un snapshot générique reste en mémoire de catalogue.
    Son MANIFESTE, lui, quitte le corpus (`forget_in_corpus`, 2026-10-11) : l'archive est
    l'historique git, pas un dossier qui se figerait dans une forme périmée.

    Retourne {'ok': True, 'freed_gb': X, 'kind': …, 'also_marked': […], 'affected': […]}
    ou {'ok': False, 'error': …} (+ `needs_confirmation`, `sharing`, `dependents`).
    """
    import shutil

    from django.utils import timezone

    from ..models import AIModel

    model = AIModel.objects.filter(model_key=model_key).first()
    if model is None:
        return {'ok': False, 'error': f"modèle inconnu du catalogue : {model_key!r}"}
    if model.is_proposed:
        return {'ok': False, 'error': "un candidat de prospection ne se désinstalle pas — "
                                      "il se rejette (bouton Rejeter)."}
    if model.execution == 'cloud':
        return {'ok': False, 'error': "un modèle distant n'a aucun poids sur cette machine — il "
                                      "disparaît de vos choix en retirant la clé d'API du profil."}
    if model.is_loaded:
        return {'ok': False, 'error': f"« {model.name} » est chargé en mémoire — "
                                      "le décharger avant de le désinstaller."}
    if not model.is_downloaded:
        return {'ok': False, 'error': f"« {model.name} » n'a pas de poids sur cette machine."}

    freed_gb = float(model.disk_gb or 0)
    marked = [model]
    dependents = []

    if model.source == 'ollama':
        name = model.model_key.split(':', 1)[1] if ':' in model.model_key else model.name
        res = delete_ollama_model(name)
        if not res.get('ok'):
            return {'ok': False, 'error': f"retrait Ollama impossible : {res.get('error')}"}
        kind = 'ollama'
    elif (model.extra_info or {}).get('declared_files'):
        # Les fichiers que l'app DÉCLARE (pilote `files`) : retirés un à un, jamais leur dossier.
        res = remove_declared_files(model, include_shared=include_shared)
        if not res.get('ok'):
            return res
        freed_gb = res['freed_gb']
        marked += res['sharing']
        kind = 'declared_files'
    else:
        # GARDE-FOUS avant tout rm -rf : le dossier doit être SOUS la racine canonique —
        # jamais de suppression hors de `AI-models/models/`, quoi que dise la base. Le cache HF
        # PARTAGÉ (`AI-models/cache/…`, sous-dépendances de plusieurs modèles) est donc hors
        # d'atteinte même quand l'index y résout un `hf_id`.
        from wama.common.utils.model_locations import installed_snapshots, models_root
        index = installed_snapshots()
        declared = weights_dir_of(model, index)
        if declared is None:
            return {'ok': False,
                    'error': f"aucun dossier de poids désinstallable pour « {model.name} » : ni "
                             "snapshot HuggingFace installé, ni dossier déclaré sous une famille "
                             "(un poids-fichier se retire par son app)."}
        try:
            root = models_root().resolve()
            target = declared.resolve()
            target.relative_to(root)           # ValueError si hors racine
        except (ValueError, OSError):
            return {'ok': False, 'error': f"chemin hors de la racine des modèles : {declared}"}
        if not target.is_dir():
            # Les poids sont DÉJÀ partis : seule la ligne dit encore « téléchargé ». On la recale
            # sans rien supprimer ni annoncer d'espace rendu (2026-10-11 : deux lignes remises
            # « téléchargées » par une synchro périmée, fichiers absents, refusaient le retrait
            # par « dossier de poids introuvable » — plus rien ne pouvait les corriger).
            freed_gb, kind = 0.0, 'already_absent'
        else:
            sharing, dependents = rows_depending_on(model, target, index)
            if (sharing or dependents) and not include_shared:
                names = [m.name for m in sharing]
                users = [m.name for m in dependents]
                parts = []
                if names:
                    parts.append("ces poids sont AUSSI ceux de : " + ', '.join(names)
                                 + " — ils seront désinstallés ensemble")
                if users:
                    parts.append("s'en servent comme modèle de base : " + ', '.join(users)
                                 + " — ils resteront installés mais ne pourront plus tourner")
                return {'ok': False, 'needs_confirmation': True, 'sharing': names,
                        'dependents': users, 'error': ' ; '.join(parts) + '.'}
            loaded = [m.name for m in sharing if m.is_loaded]
            if loaded:
                return {'ok': False, 'error': f"« {', '.join(loaded)} » partage ces poids et est "
                                              "chargé en mémoire — le décharger d'abord."}
            marked += sharing

            # ⚠ `not f.is_symlink()` — sans lui, l'espace annoncé est le DOUBLE du réel
            # (2026-09-04) : dans un cache HF, chaque poids existe une fois dans `blobs/` et une
            # fois comme LIEN dans `snapshots/`, et `rglob` + `is_file()` suit les liens. Mesuré
            # sur le dossier plutôt que lu dans `disk_gb`, que les modèles d'app laissent à 0.
            try:
                measured = sum(f.stat().st_size for f in target.rglob('*')
                               if f.is_file() and not f.is_symlink()) / (1024 ** 3)
                freed_gb = measured or freed_gb
            except OSError:
                pass
            shutil.rmtree(target)
            locks = target.parent / '.locks' / target.name
            if locks.is_dir():
                shutil.rmtree(locks, ignore_errors=True)
            kind = 'hf_snapshot' if target.name.startswith('models--') else 'weights_dir'
            # Le dossier de cache qu'une installation du Hub a créé POUR CE SEUL modèle (un
            # candidat : `models/llm/Qwen2.5-7B-Instruct/`) restait vide, son `.locks` aussi
            # (mesuré le 2026-10-23). Retirés s'ils sont VIDES — `rmdir`, jamais la catégorie : une
            # famille partagée garde ses autres modèles. Un dossier de poids DÉCLARÉ (bark) laisse
            # son parent tel quel : c'est l'app qui a posé ce rangement.
            if kind == 'hf_snapshot':
                family = target.parent
                for folder in (family / '.locks', family):
                    try:
                        where = folder.resolve()
                        if where != root and where.parent != root:
                            folder.rmdir()
                    except OSError:
                        pass                   # non vide, ou déjà absent : on le laisse

    # Recalage IMMÉDIAT du catalogue (le sync ne re-mesure ces lignes qu'à sa prochaine
    # passe, et un snapshot générique disparu n'est simplement plus re-découvert).
    stamp = timezone.now().isoformat()
    for row in marked:
        info = dict(row.extra_info or {})
        info['uninstalled_at'] = stamp
        AIModel.objects.filter(pk=row.pk).update(
            is_downloaded=False, is_loaded=False, extra_info=info)
    logger.info("[uninstall] %s (%s) — %.1f Go rendus%s", model_key, kind, freed_gb,
                f" ; aussi marqués : {[m.model_key for m in marked[1:]]}" if len(marked) > 1 else '')
    result = {'ok': True, 'freed_gb': round(freed_gb, 1), 'kind': kind, 'name': model.name,
              'also_marked': [m.name for m in marked[1:]],
              'affected': [m.name for m in dependents]}
    # Journal DATÉ (calendrier, couche « Installations ») — seul un retrait EFFECTUÉ s'y inscrit.
    from .install_history import record
    record('model', model_key, name=model.name, action='uninstall', via=via, result=result)
    forget_in_corpus([m.model_key for m in marked])
    return result


def forget_in_corpus(model_keys) -> None:
    """Le corpus de manifestes SUIT la désinstallation, comme il suit l'installation
    (`provenance` y écrit le manifeste) : le même `manifest_export` à la clé retire le fichier
    d'un modèle désinstallé (`_gone_model_keys`, 2026-10-11). Jamais bloquant : le retrait des
    poids est fait, un corpus en retard se rattrape au prochain export complet.

    Par la porte commune du corpus (`common/manifests/corpus.follow`), que le runner de tests
    coupe : une base de test désinstalle des clés qui existent au vrai corpus
    (`synthesizer:bark`), et ce geste effacerait un fichier versionné."""
    from wama.common.manifests.corpus import follow
    for key in model_keys:
        try:
            follow(key, kind='model')
        except Exception as e:
            logger.warning("[uninstall] corpus non suivi pour %s : %s", key, e)


def spec_for_catalog_row(model) -> dict | None:
    """
    Spec d'installation DÉRIVÉ d'une ligne de catalogue non téléchargée — le geste « Installer »
    des modèles d'app (2026-08-27, cas musicgen-melody : affiché « Not downloaded » sans aucun
    bouton ; l'affichage est voulu — découvrabilité —, le geste manquait).

    Conditions : un `hf_id` (la référence à tirer) ET un `extra_info['install_dir']` déclaré
    par la DÉCOUVERTE de l'app (le registre ne connaît pas ses producteurs : c'est l'app qui
    dit où ses poids vivent). `category`/`family` se dérivent du chemin relatif à la racine
    canonique. La `composition` déclarée voyage dans le spec (jeu cohérent). None si la ligne
    n'est pas installable ainsi — l'appelant le DIT, il n'invente pas d'emplacement.
    """
    from wama.common.utils.model_locations import models_root

    hf_id = (model.hf_id or '').strip()
    install_dir = ((model.extra_info or {}).get('install_dir') or '').strip()
    # Les fichiers que l'app DÉCLARE, chacun avec son origine (pilote `files`, 2026-10-11 ;
    # CodeFormer depuis le 10/10) : ils priment sur le `hf_id`, qui peut nommer un dépôt sans
    # rapport avec les poids réellement lus — ou n'en nommer qu'un parmi plusieurs (MuseTalk).
    declared = (model.extra_info or {}).get('declared_files')
    if declared and install_dir:
        try:
            Path(install_dir).resolve().relative_to(models_root().resolve())
        except (ValueError, OSError):
            return None                  # hors racine canonique : pas installable d'ici
        return {'kind': 'files', 'ref': model.model_key, 'files': list(declared),
                'target_dir': install_dir,
                'note': f"installation explicite depuis le catalogue ({model.model_key})"}
    if not hf_id or not install_dir:
        return None
    try:
        rel = Path(install_dir).resolve().relative_to(models_root().resolve())
    except (ValueError, OSError):
        return None                      # hors racine canonique : pas installable d'ici
    parts = rel.parts
    if not parts:
        return None
    spec = {
        'kind': 'hf', 'ref': hf_id,
        'category': parts[0],
        **({'family': parts[1]} if len(parts) > 1 else {}),
        'note': f"installation explicite depuis le catalogue ({model.model_key})",
    }
    if getattr(model, 'composition', None):
        spec['composition'] = model.composition
    return spec


#: Fichiers de bord tirés avec tout jeu de composants (config/tokenizer/licence — légers).
_PATTERNS_DE_BORD = ['*.json', '*.txt', 'tokenizer*', '*.md']


def patterns_from_composition(composition) -> list | None:
    """
    `allow_patterns` DÉRIVÉS d'une `composition` déclarée (manifeste `model`,
    `body.composition.components`), ou None si rien n'est déclaré (→ dépôt entier, cas
    général mono-modèle). C'est la moitié « installation » du contrat : le manifeste déclare
    l'anatomie UNE fois, l'installation tire le jeu COHÉRENT — jamais le dépôt entier d'un
    repack multi-quantisations, jamais un composant isolé qui ne serait pas un modèle.
    """
    comps = (composition or {}).get('components') or []
    patterns = [c['pattern'] for c in comps if isinstance(c, dict) and c.get('pattern')]
    return patterns + _PATTERNS_DE_BORD if patterns else None


def install_owner(user_id):
    """À qui revient un modèle que l'installation fait NAÎTRE (`ROADMAP §29` étape 3, décision de
    Fabien du 2026-10-18) — `None` = système.

    Un administrateur qui installe fait déjà le geste de promotion (c'est lui qui valide) : son
    modèle est système, comme celui d'une installation sans compte (ligne de commande, prérequis
    d'une app). Un autre compte — un développeur, seul autre profil autorisé à installer
    (`can_manage_registries`) — garde le modèle qu'il fait naître : privé, jusqu'à sa promotion.
    ⚠ Une ligne qui existait déjà (modèle déclaré par une app, réinstallation) ne change jamais
    de main : seule une ligne APPARUE prend un auteur (`provenance.record_after_install`)."""
    if not user_id:
        return None
    from django.contrib.auth import get_user_model
    from wama.accounts.permissions import is_admin_tier
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None or is_admin_tier(user):
        return None
    return user


def install_from_spec(spec: dict, token=None, owner=None) -> dict:
    """
    Point d'entrée UNIQUE d'installation — DESCRIPTEUR déclaratif au lieu de mécanismes
    hardcodés par type. Le spec peut être construit par l'UI, par la prospection, ou par
    l'ASSISTANT IA (pipeline cible : besoin utilisateur → modèle → librairie → app →
    install ; voir PROSPECTION_PIPELINE.md). Les `pull_*` existants deviennent les
    drivers derrière ce dispatcher.

    spec = {
      'kind': 'ollama' | 'hf' | 'yolo' | 'github' | 'files',   # driver d'installation
      'ref':  'bge-m3' | 'org/model' | 'yolo26s-seg' | 'owner/repo:tag' | '<clé d'app>',
      'asset': 'x.onnx', 'sha256': '…',        # github : fichier de la version + empreinte
                                               #   épinglée (`github_spec_error`)
      'files': [{path, size, sha256, origin}],  # files : fichiers déclarés par l'app, chacun
      'target_dir': '…',                       #   avec son origine (`declared_files_error`)
      'category': 'diffusion' | 'speech' | …,  # hf : catégorie de dossier (model_locations)
      'family': 'qwen-image',                  # hf : sous-dossier famille (optionnel)
      'allow_patterns': ['*.safetensors'],     # hf : restreindre les fichiers (optionnel)
      'composition': {'components': […]},      # hf : anatomie déclarée (manifeste model) —
                                               #   allow_patterns DÉRIVÉS des patterns de
                                               #   composants si non fournis explicitement
      'pip_dependencies': ['lib>=x'],          # optionnel — VALIDATION HUMAINE OBLIGATOIRE
      'human_validated': True,                 # requis si pip_dependencies non vide
      'note': 'pourquoi ce modèle',            # traçabilité (journalisée)
    }
    Retourne {'ok': bool, …} (mêmes clés que les drivers, + 'pip' si dépendances).
    `token` : jeton du téléchargement HF (`accounts.api_keys.download_token`), hors du spec À
    DESSEIN — un spec est déclaratif et circule (prospection, assistant) ; un secret, jamais.
    `owner` : l'auteur des lignes que l'installation fait naître (`install_owner`), hors du spec
    pour la même raison — `None` = système.
    """
    spec = spec or {}
    kind = spec.get('kind')
    ref = (spec.get('ref') or '').strip()
    if not ref:
        return {'ok': False, 'error': 'spec.ref requis'}
    deps = [d for d in (spec.get('pip_dependencies') or []) if d]
    # ⚠ Installer des paquets = surface de risque (cf. pip_install_packages) : le spec
    # doit porter la preuve d'une validation humaine explicite, jamais d'auto.
    if deps and not spec.get('human_validated'):
        return {'ok': False,
                'error': "pip_dependencies exige une validation humaine explicite "
                         "(spec.human_validated=true)"}
    if spec.get('note'):
        logger.info("install_from_spec %s:%s — %s", kind, ref, spec['note'])

    if kind == 'ollama':
        res = pull_ollama_model(ref)
    elif kind == 'yolo':
        res = pull_yolo_weights(ref)
    elif kind == 'github':
        res = pull_github_asset(spec)
    elif kind == 'files':
        res = pull_declared_files(spec, token=token)
    elif kind == 'hf':
        if not spec.get('category'):
            return {'ok': False, 'error': "spec.category requis pour kind='hf'"}
        res = pull_hf_model(ref, spec['category'], spec.get('family'),
                            allow_patterns=(spec.get('allow_patterns')
                                            or patterns_from_composition(spec.get('composition'))),
                            token=token)
    else:
        return {'ok': False,
                'error': f"spec.kind inconnu: {kind!r} (ollama|hf|yolo|github|files)"}

    if res.get('ok') and deps:
        res['pip'] = pip_install_packages(deps)
        if not res['pip'].get('ok'):
            res['ok'] = False
            res['error'] = "modèle téléchargé mais dépendances pip en échec (voir 'pip')"
    if res.get('ok'):
        record_provenance(spec, res, owner=owner)
    return res


def record_provenance(spec: dict, res: dict, owner=None) -> dict:
    """Après un téléchargement réussi : sync du catalogue, puis provenance des lignes apparues.

    Le sync ne pose QUE les faits de découverte (chemin, format, classes, taille) : il ne sait
    rien de la licence ni de l'auteur. Sans la provenance, un modèle ajouté par URL depuis
    l'assistant arrivait au catalogue aussi anonyme que ceux trouvés par scan disque — et le
    corpus déclaratif n'en portait aucune trace. `added_keys` vient du sync lui-même : c'est
    LUI qui sait ce qu'il vient de créer.

    Corps UNIQUE des deux chemins d'installation (`install_from_spec` et la branche Ollama de
    `install_candidate`, 2026-09-18). Best-effort des deux côtés : une provenance manquée
    (réseau, dépôt privé) ne doit jamais faire échouer une installation qui, elle, a réussi.
    Écrit `res['provenance']` et le rend. `owner` : l'auteur des lignes apparues (`install_owner`).
    """
    sync = None
    try:
        sync = register_after_install()
    except Exception:
        logger.warning("register_after_install a échoué (le sync périodique rattrapera)",
                       exc_info=True)
    if sync is None:
        return res
    try:
        from .provenance import record_after_install
        res['provenance'] = record_after_install(spec, getattr(sync, 'added_keys', None) or [],
                                                 owner=owner)
    except Exception as e:
        logger.warning("provenance non enregistrée après installation : %s", e, exc_info=True)
        res['provenance'] = {'erreur': f"{type(e).__name__}: {e}"}
    queue_benchmarks(res, getattr(sync, 'added_keys', None) or [])
    return res


def queue_benchmarks(res: dict, appeared_keys) -> None:
    """Met en file le BANC TIERS des modèles qu'on vient d'installer (2026-10-10).

    Avant, un modèle installé n'avait de banc qu'à la synchro COMPLÈTE suivante — au bouton
    « Mesurer la performance », ou après une prospection —, donc souvent jamais : son a priori
    restait vide et le tirage le classait mal. Les lignes visées sont celles qui ont reçu leur
    identité (c'est d'elle que dépend l'appariement : `hf_id`, `platform_ref`), sinon ce que le
    sync a créé. Asynchrone (file `default`, purement réseau) et lu sur le cache des sources
    (`cache='read'`) : une installation n'attend pas les leaderboards, et ne vide pas un quota.
    Best-effort, comme la provenance : un banc manqué ne fait jamais échouer une installation."""
    provenance = res.get('provenance') if isinstance(res.get('provenance'), dict) else {}
    keys = [p['model'] for p in (provenance.get('models') or [])
            if isinstance(p, dict) and p.get('model')] or list(appeared_keys or ())
    if not keys:
        return
    try:
        from ..tasks import sync_benchmarks_task
        sync_benchmarks_task.delay(keys=keys, cache='read')
        res['benchmarks_queued'] = keys
    except Exception as e:
        logger.warning("banc tiers non mis en file après installation : %s", e, exc_info=True)


#: Verrous d'installation pip (ROADMAP §16.7, transposés d'Hermes — câblés le 2026-08-31,
#: ils n'étaient jusque-là que doctrine) : PyPI par NOM seul (extras tolérés), PIN EXACT
#: `==` obligatoire — URL, `git+`, `file:`, options (`--index-url`, `-e`), chemins et
#: contraintes lâches (`>=`) sont refusés AVANT de toucher pip. L'allowlist par librairie
#: est `Library.is_allowed` (décision humaine, jamais posée par une projection) ; le kill
#: switch coupe tout sans redéploiement.
_PIP_SPEC_RE = re.compile(
    r'^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?'   # nom de distribution (PEP 508)
    r'(\[[A-Za-z0-9._,-]+\])?'                      # extras optionnels
    r'==[A-Za-z0-9.!+]+$'                           # pin exact (PEP 440)
)
PIP_KILL_SWITCH_ENV = 'WAMA_PIP_KILL_SWITCH'


def pip_spec_error(spec: str):
    """Motif de refus d'un spécificateur pip, ou None s'il passe les verrous syntaxiques."""
    s = (spec or '').strip()
    if not s:
        return "spécificateur vide"
    if not _PIP_SPEC_RE.match(s):
        return (f"spécificateur refusé : {s!r} — forme exigée « nom==version » "
                "(PyPI par nom seul, pin exact ; pas d'URL, git+, option ni contrainte lâche)")
    return None


# ── CONTRAINTES d'installation : ce que l'installation ne doit PAS déplacer ──────────────
#
# POURQUOI (2026-09-15, installation du SDK `mcp`) : la simulation de `mcp==1.30.0` voulait
# monter `starlette` 0.46.2 → 1.6.0 (via `sse-starlette`), alors que `fastapi` 0.115 exige
# `starlette<0.47` — et `fastapi` porte `gradio`, `vibevoice`, `inference`, `imaginAIry`.
# Épingler `starlette==0.46.2` suffit : pip retient alors `sse-starlette` 3.0.3, sans autre
# effet. Mais ce pin n'avait AUCUN chemin : la route n'acceptait qu'UN spécificateur, et le
# champ `constraints` du manifeste — projeté au registre — n'était lu par personne.
#
# Les contraintes passent les MÊMES verrous qu'un spécificateur (nom PyPI, pin exact) et sont
# données à pip par `-c` : une contrainte n'INSTALLE rien, elle borne ce que la résolution a
# le droit de choisir. C'est la forme exacte de « le venv est la référence ».

def pip_constraint_errors(constraints) -> list:
    """Motifs de refus des contraintes pip — mêmes verrous qu'un spécificateur."""
    return [e for e in (pip_spec_error(c) for c in (constraints or [])) if e]


def _write_constraints_file(constraints):
    """Chemin d'un fichier de contraintes temporaire pour `pip -c`, ou None sans contrainte.
    L'appelant le supprime (`_remove_file`)."""
    pins = [c.strip() for c in (constraints or []) if c and c.strip()]
    if not pins:
        return None
    import tempfile
    fd, path = tempfile.mkstemp(prefix='wama-pip-constraints-', suffix='.txt')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write('\n'.join(pins) + '\n')
    return path


def _remove_file(path) -> None:
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def pip_install_packages(packages, timeout: int = 1800, no_deps: bool = False,
                         constraints=None) -> dict:
    """
    Installe des paquets pip dans le venv courant — pour rendre un backend disponible quand un
    nouveau modèle exige de nouvelles libs (jonction avec le contrat BaseModelBackend).

    ⚠️ Installer des paquets arbitraires est une surface de risque → à déclencher sur VALIDATION
    HUMAINE uniquement, jamais en auto — et depuis le 2026-08-31 les verrous syntaxiques
    (`pip_spec_error` : pin exact, PyPI par nom) + kill switch s'appliquent à TOUS les
    appelants, y compris `ensure_backend_deps`. Retourne {ok, installed, error}.
    """
    import subprocess
    import sys

    pkgs = [p for p in (packages or []) if p]
    if not pkgs:
        return {'ok': True, 'installed': []}
    if os.environ.get(PIP_KILL_SWITCH_ENV):
        return {'ok': False, 'installed': [],
                'error': f"installations pip désactivées ({PIP_KILL_SWITCH_ENV} posé)"}
    refus = [e for e in (pip_spec_error(p) for p in pkgs) if e] + pip_constraint_errors(constraints)
    if refus:
        return {'ok': False, 'installed': [], 'error': ' ; '.join(refus)}
    constraints_path = None
    try:
        # `--no-deps` (2026-09-03) : un pin AMONT trop serré ne doit pas rétrograder une
        # dépendance PARTAGÉE du venv. Cas d'école mesuré — `qwen-tts==0.1.1` épingle
        # `transformers==4.57.3` quand WAMA tourne en 4.57.6 (et 10 autres modèles avec) :
        # honorer ce pin casserait potentiellement ailleurs pour un écart de patch, alors
        # que le paquet s'importe et tourne SANS rétrogradation (vérifié par import réel,
        # hors venv). Le prix est explicite : en `--no-deps`, le backend déclare ses
        # paquets EXHAUSTIVEMENT (`PIP_PACKAGES`), pip ne comble plus les oublis.
        options = ['--no-deps'] if no_deps else []
        constraints_path = _write_constraints_file(constraints)
        if constraints_path:
            options += ['-c', constraints_path]
        proc = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', *options, *pkgs],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            # Le verdict d'importabilité des backends est mémoïsé une minute (perf des pages
            # qui listent le catalogue, 05/09) : une install fraîche doit ré-autoriser TOUT DE
            # SUITE, pas à l'expiration — c'est le contrat « un backend qui apparaît
            # ré-autorise seul » (03/09), tenu ici pour l'installeur.
            try:
                from wama.common.backends.manager import invalidate_engine_cache
                invalidate_engine_cache()
            except Exception:
                pass
            return {'ok': True, 'installed': pkgs}
        return {'ok': False, 'installed': [], 'error': (proc.stderr or '')[-2000:]}
    except Exception as e:
        return {'ok': False, 'installed': [], 'error': f"{type(e).__name__}: {e}"}
    finally:
        _remove_file(constraints_path)


def ensure_backend_deps(backend_cls, timeout: int = 1800) -> dict:
    """
    Installe les paquets manquants d'un backend (classe `BaseModelBackend`) si nécessaire.
    Lit `missing_packages()` (import) et `pip_install_spec()` (noms pip). No-op si déjà dispo.
    À appeler sur validation humaine (cf. pip_install_packages). Retourne {ok, installed, already}.
    """
    missing = backend_cls.missing_packages()
    if not missing:
        return {'ok': True, 'installed': [], 'already': True}
    res = pip_install_packages(backend_cls.pip_install_spec(), timeout=timeout,
                               no_deps=bool(getattr(backend_cls, 'PIP_NO_DEPS', False)))
    res['already'] = False
    # ⚠ REJEU DES PATCHES — post-étape OBLIGATOIRE de TOUT pip install (contrat
    # `WAMA_MANIFEST_ARCHITECTURE §7` + règle AGENTS.md « patches de compatibilité venv »).
    # Il manquait ICI (trouvé le 2026-09-03 en vérifiant la route « modèle → tire une
    # librairie ») : le chemin LIBRAIRIE le rejouait, le chemin BACKEND non — or c'est le
    # même venv et les mêmes patches (Higgs/transformers, df/torchaudio, xformers…), qu'un
    # pip écrase EN SILENCE. Une garde se pose avec ses jumeaux.
    if res.get('ok') and res.get('installed'):
        res['patches'] = _replay_patches()
    return res


def _replay_patches() -> dict:
    """
    Rejoue `patches/apply_patches.py` — post-étape OBLIGATOIRE après tout pip install
    (contrat `WAMA_MANIFEST_ARCHITECTURE §7`) : pip écrase les patches venv en silence,
    et un patch perdu ne se signale pas (règle « ce qui ne plante pas ne se signale pas »).
    """
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[3] / 'patches' / 'apply_patches.py'
    if not script.exists():
        return {'ok': False, 'error': f"script introuvable : {script}"}
    try:
        proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                              text=True, timeout=600, cwd=str(script.parents[1]))
        return {'ok': proc.returncode == 0,
                'tail': (proc.stdout or proc.stderr or '').strip()[-500:]}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def simuler_installation(spec: str, timeout: int = 300, constraints=None,
                         no_deps: bool = False) -> dict:
    """Ce qu'une installation ENTRAÎNERAIT — `pip install --dry-run`, LECTURE SEULE.

    POURQUOI (2026-09-07, recadrage Fabien : « l'intérêt est de vérifier si une librairie peut
    s'installer dans le venv global ») : le plan d'`install_library` comparait la version
    INSTALLÉE à la version CIBLE. C'est vrai mais insuffisant — ça ne dit rien de ce que
    l'installation TRAÎNE AVEC ELLE. Deux cas mesurés le même jour, invisibles à cette
    comparaison :
      • `tf-keras` non borné → retenait la 2.20.1, qui exige `tensorflow<2.21` : TF 2.21 → 2.20 ;
      • `fer` → `facenet-pytorch` → `torchvision` : **torch 2.9.1 → 2.2.2**, numpy 2.3.5 → 1.26.4
        et toute une pile CUDA 12.1 — parce que nos torch viennent de `download.pytorch.org` en
        versions LOCALES (`+cu128`), absentes de PyPI, donc pip re-résout contre PyPI.
    Aucun des deux ne se voit sans simuler. *Comparer deux numéros de version ne dit rien du
    graphe qu'on va déplacer.*

    ⚠ N'INSTALLE RIEN : `--dry-run` n'écrit pas. C'est ce qui en fait un critère utilisable
    AVANT décision, là où `pip check` (46 conflits sur un venv qui tourne, tous des pins figés
    d'amont) ne sert à rien.

    Retourne {ok, would_install: [...], retrogradations: [...], sortie}.
    `retrogradations` ne liste que ce qui est DÉJÀ installé dans une version DIFFÉRENTE — c'est
    la seule partie réellement dangereuse, et la seule qui mérite un refus.
    """
    import subprocess
    import sys

    import importlib.metadata as im

    err = pip_spec_error(spec) or ' ; '.join(pip_constraint_errors(constraints))
    if err:
        return {'ok': False, 'error': err}
    # La simulation porte les MÊMES contraintes que l'installation : simuler sans elles
    # annoncerait une montée que l'installation, elle, ne ferait pas — un plan qui ment.
    constraints_path = _write_constraints_file(constraints)
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--dry-run', spec,
             *(['--no-deps'] if no_deps else []),
             *(['-c', constraints_path] if constraints_path else [])],
            capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return {'ok': False, 'error': f'simulation impossible : {e}'}
    finally:
        _remove_file(constraints_path)
    if proc.returncode != 0:
        return {'ok': False, 'error': (proc.stderr or proc.stdout or '').strip()[:800]}

    prevus = []
    for ligne in (proc.stdout or '').splitlines():
        if ligne.startswith('Would install '):
            prevus = ligne[len('Would install '):].split()
    retro = []
    for item in prevus:
        nom, _, version = item.rpartition('-')
        if not nom:
            continue
        try:
            actuelle = im.version(nom.replace('_', '-'))
        except Exception:
            continue                      # absent du venv : c'est un AJOUT, pas un recul
        if actuelle != version:
            retro.append({'paquet': nom, 'installee': actuelle, 'deviendrait': version})
    return {'ok': True, 'would_install': prevus, 'retrogradations': retro,
            'sortie': (proc.stdout or '').strip()[-400:]}


def install_library(key: str, apply: bool = False, via: str = '') -> dict:
    """
    Installe UNE librairie depuis son registre (`common.models.Library`) — la JONCTION
    manifeste→pip qui manquait (2026-08-31) : le kind `library` projetait le registre
    (`write_back_library`), mais rien ne reliait `pip_spec`/`is_allowed` aux exécuteurs.

    Contrat (WAMA_MANIFEST_ARCHITECTURE §7 + ROADMAP §16.7) :
      • `apply=False` (défaut) = PLAN sans aucun effet ;
      • `is_allowed` (décision humaine, jamais posée par une projection) obligatoire ;
      • verrous syntaxiques (`pip_spec_error` : nom PyPI + pin exact) + kill switch ;
      • post-étape : `patches/apply_patches.py` rejoué après toute installation réelle ;
      • version CONSTATÉE après coup (importlib.metadata) — un « pip ok » ne suffit pas ;
      • installe dans le venv COURANT = `venv_linux`, le venv de RÉFÉRENCE (runtime).
        `venv_win` est historique/temporaire (prod cible full-Linux, décision Fabien
        2026-08-31) : non traité, signalé dans le plan tant qu'il existe.
    """
    import importlib.metadata as im
    import sys

    from wama.common.models import Library

    lib = Library.objects.filter(key=key).first()
    if lib is None:
        return {'ok': False, 'library': key,
                'error': "librairie absente du registre — ingérer son manifeste d'abord "
                         "(write_back_library)"}
    if lib.vendor:
        # Librairie que pip ne sait pas installer (ROADMAP D-a) : même contrat, autre exécuteur.
        from .vendor_installer import install_vendor
        return install_vendor(lib, apply=apply, via=via)
    spec = (lib.pip_spec or '').strip()
    # `constraints.pip` : versions du venv que CETTE installation ne doit pas déplacer
    # (cf. `pip_constraint_errors`). Déclarées au manifeste, projetées au registre, et enfin LUES.
    constraints = list((lib.constraints or {}).get('pip') or [])
    # `constraints.no_deps` : installer SANS les dépendances (cf. validate_library_body).
    no_deps = bool((lib.constraints or {}).get('no_deps'))
    err = pip_spec_error(spec) or ' ; '.join(pip_constraint_errors(constraints))
    if err:
        return {'ok': False, 'library': key, 'error': err}

    nom_dist, _, version_cible = spec.partition('==')
    nom_dist = nom_dist.split('[', 1)[0]
    try:
        constat = im.version(nom_dist)
    except im.PackageNotFoundError:
        constat = None
    plan = {'library': key, 'spec': spec, 'installed_version': constat,
            'already_satisfied': constat == version_cible,
            'constraints': constraints,
            'no_deps': no_deps,
            'allowed': lib.is_allowed,
            'venv': sys.executable,
            'venv_win': "non traité (venv historique/temporaire — prod cible full-Linux)",
            'post_step': "patches/apply_patches.py rejoué après installation réelle"}

    if not apply:
        # Le PLAN est visible sans allowlist — le verrou ne gate que l'EXÉCUTION.
        # ⚠ Depuis le 2026-09-07 il SIMULE au lieu de seulement comparer deux numéros : c'est
        # la seule façon de voir ce que l'installation traînerait avec elle (cf.
        # `simuler_installation`). Une simulation qui échoue ne condamne pas le plan — elle
        # est REPORTÉE telle quelle, l'appelant décide.
        plan['simulation'] = simuler_installation(spec, constraints=constraints, no_deps=no_deps)
        return {'ok': True, 'plan': plan, 'would_install': constat != version_cible}

    if not lib.is_allowed:
        return {'ok': False, 'library': key, 'plan': plan,
                'error': "is_allowed=False — l'installation exige une décision humaine "
                         "explicite (allowlist, ROADMAP §16.7) : manage.py install_library "
                         f"{key} --allow --apply"}

    patches = None
    if constat != version_cible:
        # Journal DATÉ (calendrier, couche « Installations ») : seul un appel RÉEL à pip s'y
        # inscrit — un plan, ou une version déjà satisfaite, n'installe rien.
        from .install_history import opened
        with opened('library', key, name=lib.name or key, via=via) as outcome:
            res = pip_install_packages([spec], constraints=constraints, no_deps=no_deps)
            if not res.get('ok'):
                outcome.update({'ok': False, 'error': res.get('error')})
                return {'ok': False, 'library': key, 'error': res.get('error'), 'plan': plan}
            patches = _replay_patches()
            try:
                constat = im.version(nom_dist)
            except im.PackageNotFoundError:
                constat = None
            if constat != version_cible:
                error = (f"pip a répondu ok mais la version constatée est {constat!r} "
                         f"(attendu {version_cible!r})")
                outcome.update({'ok': False, 'error': error})
                return {'ok': False, 'library': key, 'plan': plan, 'patches': patches,
                        'error': error}
            outcome.update({'ok': True, 'version': version_cible})

    lib.is_installed = True
    lib.installed_version = version_cible
    lib.save(update_fields=['is_installed', 'installed_version'])
    return {'ok': True, 'library': key, 'installed': patches is not None,
            'version': version_cible, 'patches': patches, 'plan': plan}


def library_requirers(key: str, dist_name: str = '') -> dict:
    """Qui a encore BESOIN de la librairie `key` (distribution `dist_name`, la clé par défaut) :
    `{'packages': [...], 'manifests': [...]}` — les distributions INSTALLÉES du venv qui la
    déclarent dans leurs dépendances, et les manifestes du corpus qui la REQUIÈRENT
    (`requires` : `{kind: library, key}`). Vide : la retirer ne casse rien de déclaré."""
    import importlib.metadata as im

    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name

    wanted = canonicalize_name(dist_name or key)
    packages = set()
    for dist in im.distributions():
        own = canonicalize_name(dist.metadata.get('Name') or '')
        if not own or own == wanted:
            continue
        for line in dist.requires or []:
            try:
                req = Requirement(line)
            except InvalidRequirement:
                continue
            # Une dépendance d'« extra » (`; extra == "…"`) n'est pas tirée par défaut.
            if canonicalize_name(req.name) == wanted and 'extra' not in str(req.marker or ''):
                packages.add(dist.metadata.get('Name'))
    manifests = []
    corpus = Path(__file__).resolve().parents[3] / 'manifests'
    for path in sorted(corpus.rglob('*.json')):
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        refs = manifest.get('requires') if isinstance(manifest, dict) else None
        if any(isinstance(r, dict) and r.get('kind') == 'library' and r.get('key') == key
               for r in refs or []):
            manifests.append(str(path.relative_to(corpus)).replace('\\', '/'))
    return {'packages': sorted(packages), 'manifests': manifests}


def uninstall_library(key: str, apply: bool = False, via: str = '') -> dict:
    """
    DÉSINSTALLE une librairie du registre — le pendant d'`install_library` (2026-10-23, demande de
    Fabien : retirer AirLLM « proprement, par les mécanismes de WAMA » ; rien ne le permettait,
    et `un_write_back_library` refuse justement de retirer du registre une librairie installée).

    Même contrat qu'à l'installation : `apply=False` = PLAN sans effet ; kill switch ; journal
    daté (`opened`, action `uninstall`) ; état CONSTATÉ après coup. Un seul paquet retiré, le sien
    — jamais ses dépendances, partagées par le venv. REFUSÉ tant qu'un paquet installé ou un
    manifeste du corpus en a besoin (`library_requirers`) : on ne casse pas en silence ce qui
    l'importe. Le registre garde sa ligne (`is_installed=False`) et perd son autorisation
    (`is_allowed=False`) : la réinstaller redemande une décision. Une librairie VENDORISÉE (clone
    au commit) n'est pas couverte ici — le dire plutôt que retirer à moitié.
    """
    import importlib.metadata as im
    import subprocess
    import sys

    from wama.common.models import Library

    lib = Library.objects.filter(key=key).first()
    if lib is None:
        return {'ok': False, 'library': key, 'error': "librairie absente du registre"}
    if lib.vendor:
        return {'ok': False, 'library': key,
                'error': "librairie vendorisée : sa désinstallation n'est pas encore une route"}
    dist = (lib.pip_spec or key).partition('==')[0].split('[', 1)[0].strip() or key
    try:
        constat = im.version(dist)
    except im.PackageNotFoundError:
        constat = None
    requirers = library_requirers(key, dist)
    plan = {'library': key, 'distribution': dist, 'installed_version': constat,
            'requirers': requirers, 'venv': sys.executable,
            'post_step': "patches/apply_patches.py rejoué après le retrait"}
    if requirers['packages'] or requirers['manifests']:
        return {'ok': False, 'library': key, 'plan': plan,
                'error': "encore requise : " + ', '.join(requirers['packages']
                                                        + requirers['manifests'])}
    if not apply:
        return {'ok': True, 'plan': plan, 'would_uninstall': constat is not None}
    if os.environ.get(PIP_KILL_SWITCH_ENV):
        return {'ok': False, 'library': key, 'plan': plan,
                'error': f"opérations pip désactivées ({PIP_KILL_SWITCH_ENV} posé)"}

    patches = None
    if constat is not None:
        from .install_history import opened
        with opened('library', key, name=lib.name or key, action='uninstall', via=via) as outcome:
            proc = subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y', dist],
                                  capture_output=True, text=True, timeout=600)
            if proc.returncode != 0:
                error = (proc.stderr or proc.stdout or '').strip()[-500:]
                outcome.update({'ok': False, 'error': error})
                return {'ok': False, 'library': key, 'plan': plan, 'error': error}
            patches = _replay_patches()
            try:
                still = im.version(dist)
            except im.PackageNotFoundError:
                still = None
            if still is not None:
                error = f"pip a répondu ok mais {dist} {still} est toujours installé"
                outcome.update({'ok': False, 'error': error})
                return {'ok': False, 'library': key, 'plan': plan, 'error': error}
            outcome.update({'ok': True, 'version': constat})

    lib.is_installed = False
    lib.installed_version = ''
    lib.is_allowed = False
    lib.save(update_fields=['is_installed', 'installed_version', 'is_allowed'])
    return {'ok': True, 'library': key, 'uninstalled': patches is not None,
            'version': constat, 'patches': patches, 'plan': plan}


def install_requirements(app_key: str, apply: bool = False) -> dict:
    """
    Le MARCHEUR d'app (« application = modèles + librairies », reste ③ de la route
    PROSPECTION_PIPELINE — câblé le 2026-08-31) : lit les `requires` du manifeste d'app AU
    CORPUS (`manifests/apps/<app>.json` — la déclaration validée, qui porte les jambes
    `library` semées) et DISPATCHE chaque référence vers son driver EXISTANT :

      • kind=library → `install_library` (plan/apply — allowlist `is_allowed` par lib) ;
      • kind=model   → état du catalogue (plan) ; à l'exécution, la DEMANDE du bouton
        (`request_install`, voie `app_requirements`) : garde d'espace disque, idempotence,
        tâche Celery. Sans spec dérivable, le modèle reste au « téléchargement au premier
        usage » — signalé, jamais silencieux.

    Le marcheur n'invente RIEN : il n'installe que ce que les drivers savent installer,
    sous leurs propres gardes. `apply=False` (défaut) = plan complet sans effet.

    ⚠ Jusqu'au 2026-10-10, l'exécution enfilait la tâche ELLE-MÊME (`install_catalog_task`,
    puis `dispatch_install`) : la garde d'espace disque, qui vivait alors dans la vue du bouton
    puis dans `request_install` (route unique du 19/09), ne l'a jamais couverte.
    """
    from wama.model_manager.models import AIModel

    chemin = Path(__file__).resolve().parents[3] / 'manifests' / 'apps' / f'{app_key}.json'
    if not chemin.exists():
        return {'ok': False, 'app': app_key,
                'error': f"manifeste d'app absent du corpus : {chemin.name} "
                         "(manifest_export --kind app d'abord)"}
    try:
        manifeste = json.loads(chemin.read_text(encoding='utf-8'))
    except Exception as e:
        return {'ok': False, 'app': app_key, 'error': f"manifeste illisible : {e}"}

    libraries, models, autres = [], [], []
    for ref in (manifeste.get('requires') or []):
        kind, key = ref.get('kind'), ref.get('key')
        if kind == 'library':
            libraries.append({'key': key, **install_library(key, apply=apply,
                                                             via='app_requirements')})
        elif kind == 'model':
            row = AIModel.objects.filter(model_key=key, is_proposed=False).first()
            if row is None:
                models.append({'key': key, 'state': 'ABSENT du catalogue — sync_models ?'})
            elif row.is_downloaded:
                models.append({'key': key, 'state': 'téléchargé'})
            else:
                spec = spec_for_catalog_row(row)
                if spec is None:
                    models.append({'key': key,
                                   'state': "non téléchargé — pas de spec dérivable "
                                            "(téléchargement au premier usage)"})
                elif not apply:
                    models.append({'key': key, 'state': 'non téléchargé',
                                   'would_install': spec.get('ref')})
                else:
                    res = request_install(key, via='app_requirements')
                    if res.get('started'):
                        models.append({'key': key, 'state': 'installation enfilée (Celery)',
                                       'task_id': res['task_id']})
                    elif res.get('already_running'):
                        models.append({'key': key, 'state': 'installation déjà en cours'})
                    else:
                        blocked = res.get('blocked') or {}
                        models.append({'key': key, 'ok': False,
                                       'state': f"REFUSÉ ({res.get('reason')})",
                                       'error': blocked.get('error') or res.get('error')})
        else:
            autres.append(ref)   # function/dataset… : hors périmètre du marcheur, signalés

    ok = all(r.get('ok', True) for r in libraries + models)
    return {'ok': ok, 'app': app_key, 'apply': apply,
            'libraries': libraries, 'models': models,
            **({'ignored': autres} if autres else {})}
