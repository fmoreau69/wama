"""
Memory Manager - GPU/RAM memory utilities for model management.

Provides centralized VRAM management and CPU offload strategies for all WAMA applications.
"""

import gc
import logging
import re
from typing import Dict, Optional, Literal
from enum import Enum

logger = logging.getLogger(__name__)


# Marge minimale de VRAM libre à préserver pendant un chargement FULL_GPU (activations
# + fragmentation). En dessous, on abandonne FULL_GPU et on retombe sur MODEL_OFFLOAD.
FULL_GPU_MIN_FREE_GB = 1.5

def peaks_from_weights(weights: dict) -> dict:
    """Les DEUX pics d'un modèle, dérivés du poids par composant — `{}` si on ne sait pas.

    Traduction directe de la décision A (`PROJECT_STATUS §④A`, 16/09) : un modèle composé a deux
    empreintes et non une.
      * `full` — SOMME des composants : tout coexiste sur la carte ;
      * `offload` — PLUS GROS composant : en déchargement, un composant descend quand le suivant
        monte, et c'est lui qui fixe le plafond.

    `weights` est le relevé de `extra_info['weights']` (`{components, total_gb, largest_gb}`),
    produit par `model_sync.persist_weights` depuis les fichiers du snapshot.

    🔴 AUCUNE MARGE AJOUTÉE ICI, et c'est une correction (2026-09-20, recadrage de Fabien). Ma
    première version ajoutait 4 Go d'« activations » à chaque pic, en s'appuyant sur le crash
    hôte du 29/07. DEUX erreurs dans ce raisonnement :
      1. le crash hôte n'est pas un argument : le dépôt porte les deux hypothèses (28/08 — « la
         puissance n'est pas le facteur, la montée VRAM l'est » ; puis rails instrumentés qui
         n'innocentent pas le bloc, onduleur pseudo-sinusoïde, alimentation 1000 W commandée), et
         **aucune des deux ne justifie d'ajouter une constante au poids d'un modèle** ;
      2. surtout, la marge n'appartient pas au MODÈLE. Un pic de poids est un FAIT du modèle ; ce
         qu'il faut garder libre est une politique de la MACHINE, donc du gouverneur. Il en existe
         déjà quatre dans ce dépôt — `full_gpu_budget_gb(headroom_gb=4.0)`,
         `fits_full_gpu(headroom_gb=4.0)`, `get_memory_strategy(headroom_gb=2.0)`,
         `FULL_GPU_MIN_FREE_GB = 1.5` / `ensure_free_vram(headroom_gb=1.5)`. En ajouter une
         cinquième, cachée dans le calcul du pic, aurait rendu la marge invisible ET irréconciliable.
    *Cette fonction rend des faits ; ce qu'on garde libre se décide ailleurs, une seule fois.*

    ⚠ POURQUOI ELLE EXISTE : `get_memory_strategy` ne recevait qu'UN nombre et APPROXIMAIT le
    second avec des pourcentages (« la VRAM peut tenir 60 % du modèle → offload »). Ces 60 % et
    30 % étaient un substitut de « le plus gros composant tient ». Mesuré le 2026-09-19 :
    CogVideoX pèse 20,2 Go de somme pour 10,5 de plus gros composant (52 %), FastWan 22,5 pour
    10,6 (47 %), Hunyuan 49,5 pour 32,5 (66 %). Aucun pourcentage fixe ne pouvait le représenter.
    """
    total = (weights or {}).get('total_gb')
    largest = (weights or {}).get('largest_gb')
    if not total or not largest:
        return {}
    return {'full': round(float(total), 2), 'offload': round(float(largest), 2)}


def _cap_cuda_allocator() -> None:
    """
    Plafond de l'allocateur CUDA — DÉLÉGUÉ au gouverneur de ressources.

    L'implémentation vit dans `wama/common/services/resource_governor.py`, seul
    domicile des mécanismes d'allocation (GPU/CPU/RAM). Elle est désormais posée
    UNE FOIS PAR PROCESS (signal Celery `worker_process_init` + `AppConfig.ready`),
    et plus par chemin de chargement : la version d'origine, posée ici, ne couvrait
    que la voie diffusers de l'imager alors que transcriber, reader, describer,
    avatarizer et le service TTS font `.to('cuda')` en direct.

    Cet appel reste comme FILET pour les process qui n'auraient pas été initialisés
    (l'opération est idempotente).
    """
    try:
        from wama.common.services.resource_governor import configure_cuda_process
        configure_cuda_process()
    except Exception as exc:
        logger.debug(f"[MemoryManager] plafond CUDA délégué non appliqué : {exc}")


def _component_size_gb(component) -> float:
    """
    Empreinte réelle d'un composant de pipeline (paramètres + buffers), en Go.

    Complémentaire de ``MemoryManager.estimate_model_size(path)``, qui estime depuis
    un CHEMIN (presets + taille de fichier) : ici on mesure un module DÉJÀ instancié,
    seul moyen de connaître l'empreinte vraie quand le preset est faux.
    """
    try:
        n = sum(p.numel() * p.element_size() for p in component.parameters())
        n += sum(b.numel() * b.element_size() for b in component.buffers())
        return n / (1024 ** 3)
    except Exception:
        return 0.0


class MemoryStrategy(Enum):
    """Memory loading strategies for AI models."""
    FULL_GPU = "full_gpu"              # Load entirely on GPU (fastest)
    MODEL_OFFLOAD = "model_offload"    # Move model components to GPU as needed (moderate)
    SEQUENTIAL_OFFLOAD = "sequential"  # Move layers to GPU one at a time (slowest, least VRAM)
    CPU_ONLY = "cpu"                   # Run entirely on CPU (no GPU)


# Model size categories in GB (measured VRAM requirement at runtime, bf16/fp16).
# Used by get_memory_strategy() to decide FULL_GPU vs CPU offload.
# RTX 4090 = 24 GB → headroom_gb=4 → models ≤ 20 GB fit entirely on GPU.
MODEL_SIZE_PRESETS = {
    # ── Image diffusion ──────────────────────────────────────────────────────
    # FLUX transformer alone is ~23 GB bfloat16 (12B params × 2 bytes).
    # Total pipeline (transformer + T5 + CLIP + VAE) ≈ 35 GB.
    # Use 24 GB so MemoryManager never picks FULL_GPU on a 24 GB card.
    'flux': 24.0,
    'flux-dev': 24.0,
    'flux-schnell': 12.0,
    'sdxl': 7.0,
    'sd15': 4.0,
    'sd21': 5.0,
    'hunyuan-image': 16.0,
    'hunyuan-image-2.1': 16.0,

    # Qwen Image (Alibaba) — Diffusers pipelines (not transformers)
    # MESURÉ 29/07/2026 : le transformer seul atteint 38,1 GB au chargement (log worker
    # gpu). L'ancienne valeur de 16.0 faisait choisir FULL_GPU sur une carte de 24 Go →
    # débordement WDDM en RAM hôte → kernel panic WSL2. Ne PAS rabaisser sans mesure.
    'qwen-image': 38.0,       # Qwen-Image-2512

    # ⚠️ BORNE PRUDENTE, NON MESURÉE : Qwen-Image-Edit-2511 partage la dorsale MMDiT 20B de
    # Qwen-Image — les « ~12 Go at bf16 » écrits ici à l'origine sont impossibles (20B en bf16
    # = ~40 Go de poids). Tant que la mesure n'est pas faite, on prend la valeur de la dorsale :
    # sur-estimer coûte de l'offload (lent), sous-estimer fait tenter FULL_GPU et déborde en RAM
    # hôte sous WSL2 — c'est ce qui a produit les kernel panics du 29/07. À MESURER.
    'qwen-image-edit': 38.0,
    # NON MESURÉ : FLUX.2-Klein 4B. Sans cette clé, 'flux' (24 Go, la 12B) matchait par préfixe
    # et envoyait une 4B en offload pour rien. Estimation = poids bf16 (~8 Go) + encodeur texte.
    'flux2-klein': 12.0,

    # ── Video diffusion ──────────────────────────────────────────────────────
    'hunyuan-video': 24.0,
    # CogVideoX-5B mesuré : transformer 10.8 + text_encoder 8.9 + VAE 0.4 = 20.1 GB.
    # ⛔ NE PAS BAISSER pour « récupérer » du FULL_GPU. Preuve au journal
    # (`logs/celery-gpu.log.3`, 2026-03-13 15:58:40) : ce modèle a bien été chargé en plein GPU,
    # « 20.34 GiB allocated by PyTorch », puis **CUDA out of memory** à la génération — il ne
    # restait pas les 570 Mio d'activations demandés. C'est ce run qui justifie la marge de 4 Go.
    # ⚠️ Ce 21 est une SOMME DE COMPOSANTS, pas un pic simultané : le text_encoder T5 (8,9 Go,
    # soit 45 % du total) ne sert QU'UNE FOIS, pour encoder le prompt. En MODEL_OFFLOAD le jeu
    # de travail réel des 50 étapes de débruitage est donc ~11 Go, et l'offload ne coûte ici
    # qu'un transfert du T5 (~1-2 s sur une génération de plusieurs minutes) — c'est le cas
    # IDÉAL pour `enable_model_cpu_offload()`, pas une dégradation subie. Le calcul reste
    # intégralement sur le GPU : « offload » ne veut pas dire « inférence CPU ».
    'cogvideox': 21.0,
    'ltx-video': 18.0,        # LTX-Video 13B bf16 — transformer ~14GB + text_encoder ~4GB
    'ltx-video-fp8': 8.0,    # LTX-Video 13B FP8 quantized (torchao)
    # ⚠️ La clé ci-dessus ne matche AUCUN id réel : le modèle s'appelle
    # `ltx-video-13b-0.9.8-distilled-fp8`, où 'ltx-video-fp8' n'est pas une sous-chaîne. La
    # variante fp8 héritait donc des 18 Go de la version pleine — 10 Go sur-réservés et une
    # stratégie plus prudente que nécessaire. Le garde de cohérence manifeste↔presets
    # (`imager/utils/model_config.py::_check_vram_consistency`) a signalé l'écart 8 vs 18.
    'distilled-fp8': 8.0,
    'mochi': 22.0,        # Mochi-1 Preview bf16 ~22 GB
    'wan-t2v': 14.0,
    'wan-i2v': 28.0,
    # FastWan 2.2 TI2V 5B (DMD 3 pas) — paramètres COMPTÉS sur le périphérique `meta` par
    # `manage.py probe_fastwan` (2026-09-14) : transformer 5,00 Md (~10 Go bf16) + text_encoder
    # UMT5 5,68 Md (~11,4 Go) + VAE 0,70 Md (~1,4 Go) = ~22,8 Go. NON MESURÉ au GPU.
    # ⚠ Comme CogVideoX, c'est une SOMME DE COMPOSANTS : le text_encoder ne sert qu'une fois ;
    # en MODEL_OFFLOAD le jeu de travail du débruitage est le transformer seul. 23 + 4 de marge
    # > 24 Go → MODEL_OFFLOAD sur une 4090 ; ne PAS le faire passer sous le preset `wan-t2v`
    # (14 Go), qui ferait tenter FULL_GPU pour ~23 Go de poids.
    'fastwan': 23.0,

    # ── Vision (detection / segmentation) ───────────────────────────────────
    'yolo-nano': 0.5,
    'yolo-small': 1.0,
    'yolo-medium': 2.0,
    'yolo-large': 4.0,
    'yolo-xlarge': 6.0,
    'sam3-tiny': 1.5,
    'sam3-base': 3.0,
    'sam3-large': 6.0,

    # ── Audio (ASR) ──────────────────────────────────────────────────────────
    'whisper-tiny': 0.5,
    'whisper-base': 0.8,
    'whisper-small': 1.5,
    'whisper-medium': 3.0,
    'whisper-large': 6.0,

    # ── Multimodal / captioning ──────────────────────────────────────────────
    'blip': 2.0,
    'blip2': 4.0,
}


def preset_vram_gb(model_key: str) -> Optional[float]:
    """
    Empreinte VRAM d'exécution d'un modèle, depuis `MODEL_SIZE_PRESETS`.
    Clé la PLUS SPÉCIFIQUE qui matche (les clés se préfixent entre elles). None si inconnu.

    🔴 **SOURCE UNIQUE de ce chiffre.** Ne pas le recopier dans un backend, un `model_config`
    ou un catalogue : c'est précisément ce qui a produit le crash du 29/07/2026 — la mesure
    (38 Go pour Qwen-Image) avait été corrigée ICI, mais deux copies périmées (16 Go)
    subsistaient ailleurs, et c'est une copie qui décidait de tenter FULL_GPU sur 24 Go.
    """
    if not model_key:
        return None
    key_lower = model_key.lower()
    matches = [(len(k), v) for k, v in MODEL_SIZE_PRESETS.items() if k in key_lower]
    return max(matches, key=lambda m: m[0])[1] if matches else None


#: Octets par paramètre, par nom de dtype tel que l'écrit un en-tête safetensors (`prospector.
#: precision_of_files`) ou une étiquette de quantification (imager `'fp8'`, Ollama `'Q4_K_M'`).
#: ⚠ `I64`/`I32` ne sont PAS des poids castables : ce sont des index (positions, tokens). Les
#: compter à la précision cible surestime — d'où la réserve dite dans `peaks_for_precision`.
_DTYPE_BYTES = {
    'F64': 8, 'F32': 4, 'FP32': 4, 'FLOAT32': 4,
    'BF16': 2, 'F16': 2, 'FP16': 2, 'FLOAT16': 2, 'HALF': 2,
    'F8_E4M3': 1, 'F8_E5M2': 1, 'FP8': 1, 'INT8': 1, 'I8': 1, 'U8': 1,
    'INT4': 0.5, 'FP4': 0.5, 'NF4': 0.5,
    'I64': 8, 'I32': 4, 'I16': 2, 'BOOL': 1,
}


def dtype_bytes(label: str):
    """Octets par paramètre d'une précision — None si le nom est inconnu (on ne devine pas).

    Accepte les noms d'en-tête safetensors (`BF16`, `F32`) et les étiquettes de quantification
    (`fp8` de l'imager, `Q8_0` / `Q4_K_M` d'Ollama et des GGUF). Pour un `Q<n>`, le chiffre EST
    le nombre de bits par poids — c'est la convention llama.cpp, pas une interprétation.
    """
    if not label:
        return None
    up = str(label).strip().upper().replace('-', '_')
    if up in _DTYPE_BYTES:
        return _DTYPE_BYTES[up]
    m = re.match(r'^Q(\d+)', up)
    return int(m.group(1)) / 8 if m else None


def peaks_for_precision(weights: dict, label: str) -> dict:
    """Les deux pics RECALCULÉS pour une précision de chargement — `{}` si on ne peut pas.

    Le poids d'un FICHIER n'est pas le pic de CHARGEMENT : un composant stocké en F32 chargé en
    bf16 occupe la moitié, un composant quantisé en fp8 le quart. C'est `params × octets(cible)`,
    et `params` vient du relevé d'en-têtes safetensors (`weights['precision'][rôle]['params']`,
    posé par `prospector.precision_of_files`) — aucun poids n'est ouvert, seuls les en-têtes.

    Mesuré le 2026-09-20, et ça a réfuté mon propre diagnostic de la veille : j'avais annoncé que
    le transformer de LTX-distilled pesait 24,3 Go « en F32 sur le disque, donc la moitié en
    bf16 ». FAUX — ses 13,04 Md de paramètres sont DÉJÀ en BF16 ; c'est son encodeur de texte T5
    (4,76 Md) qui est en F32. Le recalcul en bf16 ne change donc rien à son pic de déchargement
    (le transformer reste le plus gros à 24,3 Go), et ce modèle exige bel et bien une
    quantification ou un déchargement par COUCHE. *Une hypothèse plausible sur un dtype se vérifie
    en une mesure, et celle-ci disait le contraire.*

    ⚠ RÉSERVE ASSUMÉE tant que le relevé ne sépare pas les dtypes : `params` est le compte TOTAL
    du rôle, index entiers compris (`I64` des positions/tokens). Les caster tous à la précision
    cible SURESTIME légèrement — ce qui est le bon sens de l'erreur. Le relevé `params_by_dtype`
    (annoncé par l'instance qui lit les en-têtes) permettra de ne caster que les flottants ; cette
    fonction le lira alors sans changer de signature.
    """
    per_param = dtype_bytes(label)
    by_role = (weights or {}).get('precision') or {}
    if not per_param or not by_role:
        return {}
    sizes = {}
    for role, entry in by_role.items():
        # `params_by_dtype` quand il existe : on ne caste QUE les flottants, les index restent
        # tels quels. Sinon le compte total, avec la réserve ci-dessus.
        detailed = (entry or {}).get('params_by_dtype') or {}
        if detailed:
            gb = sum(n * (per_param if (dtype_bytes(d) or 0) and not d.upper().startswith(('I', 'B'))
                          else (dtype_bytes(d) or per_param))
                     for d, n in detailed.items())
        else:
            gb = float((entry or {}).get('params') or 0) * per_param
        if gb:
            sizes[role] = gb / 1024 ** 3
    if not sizes:
        return {}
    return {'full': round(sum(sizes.values()), 2),
            'offload': round(max(sizes.values()), 2)}


def backbone_row(row):
    """La ligne de catalogue de la DORSALE d'un adaptateur, ou None si ce n'en est pas un.

    Un adaptateur (LoRA) ne s'exécute pas seul : il se pose SUR un modèle complet, et son fichier
    ne pèse presque rien (la LoRA logo du parc : 0,036 Go pour une dorsale de 22,2). L'app le
    déclare déjà — `model_type: 'lora'` + `base_model: '<hf_id>'` — et ces deux clés atteignent le
    catalogue depuis le 2026-09-21.

    ⚠ `base_model` est un `hf_id`, pas une clé de catalogue : la dorsale se RÉSOUT (elle a sa
    propre ligne, et c'est tout l'intérêt de l'option B retenue par Fabien — pas de duplication du
    poids). Une dorsale absente du catalogue rend None : on ne fabrique pas une empreinte à partir
    d'un modèle qu'on n'a pas.
    ⚠ `flux-1-dev` déclare aussi `base_model`, mais c'est LUI-MÊME : le test exclut ce cas, sinon
    un modèle de base se compterait deux fois.
    """
    info = getattr(row, 'extra_info', None) or {}
    base = (info.get('base_model') or '').strip()
    if not base:
        return None
    own = (getattr(row, 'hf_id', '') or '').strip()
    if base == own and info.get('model_type') != 'lora':
        return None                                      # un modèle de base, pas un adaptateur
    try:
        from wama.model_manager.models import AIModel
        return AIModel.objects.filter(hf_id=base).exclude(
            model_key=getattr(row, 'model_key', '')).first()
    except Exception as e:                               # hors Django / base absente
        logger.debug('[footprint] dorsale %s non résolue : %s', base, e)
        return None


def model_footprint_gb(row, *, offload: bool = True, count_backbone: bool = True) -> tuple:
    """`(Go, provenance)` que ce modèle EXIGE — ou `(None, 'unknown')` si personne ne sait.

    ADAPTATEURS — décision de Fabien (2026-09-21) : **B pour le catalogue, C pour l'exécution.**
      * B (`count_backbone=True`, le défaut) : l'empreinte NOMINALE d'un adaptateur est celle de sa
        dorsale PLUS son propre fichier. C'est ce qu'il faut afficher et ce sur quoi juger une
        installation — sans quoi la LoRA logo annonce 0,04 Go et le tirage la retient alors qu'elle
        exige 22,2 Go de FLUX.1-dev. La dorsale garde sa propre ligne comme source unique : rien
        n'est dupliqué, et deux adaptateurs partageant une dorsale ne la déclarent pas deux fois.
      * C (`count_backbone=False`) : l'empreinte MARGINALE, pour le gouverneur — si la dorsale est
        DÉJÀ résidente, poser l'adaptateur ne coûte que son fichier. Lui seul sait ce qui est
        chargé (`resource_governor.resident_models`), donc lui seul passe False.
    *Les deux ne se contredisent pas : B est le coût nominal, C le coût du moment.*

    LA CASCADE de la décision A (Fabien, 16/09), et sa subtilité, qui est tout l'intérêt :
    (elle s'applique à l'adaptateur comme à tout modèle ; la dorsale s'y AJOUTE ensuite.)
    « mesurée → source → estimée, **sans jamais descendre sous la valeur de la source** ». Ce
    n'est donc PAS une simple priorité, c'est un `max` entre la mesure et la source — parce que
    *la mesure au chargement est celle d'UNE stratégie* : en déchargement elle tombe sous le pic,
    et la prendre pour l'empreinte ferait tenter un plein GPU au chargement suivant.
    Vérifié dans le code qui l'écrit : `base.py:394` relève
    `memory_allocated() - before`, c'est-à-dire la RÉSIDENCE finale, et aucun appel à
    `max_memory_allocated` n'existe dans le dépôt — donc la « mesure » est structurellement un
    PLANCHER, jamais un pic.

    `offload` : la stratégie que le moteur SAIT appliquer. Vrai → on compare le pic de
    déchargement (plus gros composant) ; faux → celui du plein GPU (somme). C'est ce qui réadmet
    au tirage CogVideoX (10,5 au lieu de 20,2), FastWan (10,6 au lieu de 22,5) et Mochi.

    `row` : une ligne `AIModel` (ou tout objet portant `extra_info`, `vram_gb`, `model_key`).
    Provenances rendues, du plus sûr au moins sûr : `measured+source`, `measured`, `source`,
    `declared`, `preset`, `unknown`. Le mot `unknown` compte : un appelant ne doit pas conclure
    « ça tient » d'une absence d'information (même règle que `weight_for_spec` qui rend None).
    """
    info = getattr(row, 'extra_info', None) or {}
    # La DORSALE d'abord (option B) : son pic s'ajoute à celui de l'adaptateur. Récursion d'UN seul
    # cran — `count_backbone=False` sur l'appel interne interdit qu'une chaîne d'adaptateurs
    # s'empile à l'infini si quelqu'un déclarait un jour une dorsale qui est elle-même un
    # adaptateur.
    dorsale = backbone_row(row) if count_backbone else None
    base_gb = 0.0
    if dorsale is not None:
        base_gb = model_footprint_gb(dorsale, offload=offload, count_backbone=False)[0] or 0.0

    weights = info.get('weights') or {}
    # Une ligne qui DÉCLARE sa quantification ne pèse pas ses fichiers : elle pèse ce qu'elle
    # chargera. `imager:ltx-…-distilled-fp8` et `…-distilled` pointent le MÊME dépôt, donc le même
    # relevé de fichiers — sans ce recalcul, la ligne fp8 héritait du pic pleine précision
    # (24,3 Go) et se faisait écarter comme elle, alors que c'est précisément elle qui tient.
    # *Deux lignes de catalogue sur un seul jeu de poids : c'est la quantification qui les sépare.*
    peaks = peaks_for_precision(weights, info.get('quantization') or '') \
        or peaks_from_weights(weights)
    source = peaks.get('offload' if offload else 'full')
    measured = float(((info.get('vram_measured') or {}).get('max_gb')) or 0) or None

    def _rendu(gb, provenance):
        """Ajoute la dorsale au chiffre de l'adaptateur, et le DIT dans la provenance."""
        if gb is None or not base_gb:
            return gb, provenance
        return round(gb + base_gb, 2), f'{provenance}+backbone'

    if measured and source:
        return _rendu(round(max(measured, source), 2),
                      'measured+source' if measured >= source else 'source')
    if measured:
        return _rendu(round(measured, 2), 'measured')
    if source:
        return _rendu(source, 'source')
    declared = float(getattr(row, 'vram_gb', 0) or 0)
    if declared:
        # ⚠ La valeur DÉCLARÉE d'un adaptateur vaut souvent déjà celle de sa dorsale (la LoRA logo
        # déclare 24 Go « c'est la dorsale qui coûte »). Y rajouter la dorsale la compterait deux
        # fois : à ce rang de la cascade, on rend la déclaration telle quelle.
        return round(declared, 2), 'declared'
    preset = preset_vram_gb((getattr(row, 'model_key', '') or '').split(':')[-1])
    if preset:
        return round(float(preset), 2), 'preset'
    return None, 'unknown'


def fits_full_gpu(model_key: str, total_vram_gb: float, headroom_gb: float = 4.0) -> Optional[bool]:
    """
    Ce modèle peut-il tenir ENTIÈREMENT sur la carte (donc tourner en FULL_GPU, sans offload) ?

    None si l'empreinte est inconnue — un appelant ne doit pas conclure « ça tient » d'une
    absence d'information. Sert à ne proposer/tirer que des modèles qui n'imposeront pas
    d'offload CPU (lent), et à afficher un avertissement honnête sur les autres.
    """
    gb = preset_vram_gb(model_key)
    if gb is None:
        return None
    return (gb + headroom_gb) <= total_vram_gb


# =============================================================================
# VRAM release registry — reusable memory-admission for ALL apps
# =============================================================================
#
# Problème résolu : jusqu'ici, `clear_gpu_memory()` / `unload_model()` codaient
# en dur quelles apps décharger (imager + describer), et les autres apps
# (transcriber, synthesizer, enhancer…) étaient des stubs no-op → invisibles au
# reclaim central. Chaque app charge/décharge ses modèles dans son coin, sans
# coordination : deux gros modèles peuvent cohabiter en VRAM et geler l'hôte.
#
# Ici, chaque app DÉCLARE un « unloader » (nom + callable qui libère sa VRAM).
# `ensure_free_vram()` / `release_vram()` itèrent ces unloaders pour faire de la
# place AVANT de charger un nouveau modèle — brique unique, réutilisable partout,
# sans rien coder en dur par app.
#
# Un unloader est enregistré via `register_vram_unloader(name, fn)` (idempotent :
# ré-enregistrer le même nom remplace). `fn()` renvoie True s'il a libéré qqch.

_VRAM_UNLOADERS: "dict[str, callable]" = {}


def register_vram_unloader(name: str, fn) -> None:
    """Déclare un callable qui libère la VRAM d'une app (idempotent par `name`)."""
    _VRAM_UNLOADERS[name] = fn
    logger.debug(f"[MemoryManager] VRAM unloader registered: {name}")


def unregister_vram_unloader(name: str) -> None:
    _VRAM_UNLOADERS.pop(name, None)


class MemoryManager:
    """Manages GPU and system memory for AI models."""

    # ---- VRAM release registry (voir bloc ci-dessus) ----------------------
    @staticmethod
    def register_unloader(name: str, fn) -> None:
        register_vram_unloader(name, fn)

    @staticmethod
    def release_vram(exclude: "Optional[set]" = None) -> int:
        """
        Décharge les modèles résidents de CE process (sauf `exclude`) pour récupérer la
        VRAM. Renvoie le nombre de libérations effectives.

        `exclude` : SOURCES du catalogue à épargner (`anonymizer`…) — les backends du contrat
        dont une clé porte cette source, et les unloaders nommés `<source>` ou `<source>-…`.

        ⚠ 2026-09-14 : les backends du contrat ne passent plus par `_VRAM_UNLOADERS`. Ils s'y
        inscrivaient sous le nom de leur app déduit du chemin du module — `common` pour tous
        depuis le 08/09, si bien que l'exclusion du propriétaire ne protégeait plus rien. Ils
        sont déchargés par `base.unload_live_backends`, qui résout leur clé catalogue ; le
        registre ne garde que les modèles HORS contrat (pipeline pyannote en variable de module).
        """
        exclude = set(exclude or ())
        freed = 0
        try:
            from wama.common.backends.base import unload_live_backends
            n = unload_live_backends(exclude_sources=exclude)
            if n:
                freed += n
                logger.info(f"[MemoryManager] Released VRAM: {n} backend(s) du contrat")
        except Exception as e:
            logger.warning(f"[MemoryManager] backends du contrat non déchargés : {e}")
        for name, fn in list(_VRAM_UNLOADERS.items()):
            if name in exclude or name.split('-', 1)[0] in exclude:
                continue
            try:
                if fn():
                    freed += 1
                    logger.info(f"[MemoryManager] Released VRAM via unloader: {name}")
            except Exception as e:
                logger.warning(f"[MemoryManager] Unloader '{name}' failed: {e}")
        if freed:
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()
            except Exception:
                pass
        return freed

    @staticmethod
    def ensure_free_vram(needed_gb: float, headroom_gb: float = 1.5,
                         exclude: "Optional[set]" = None) -> bool:
        """
        Garantit ~`needed_gb` + `headroom_gb` de VRAM libre AVANT de charger un
        modèle. Si insuffisant, décharge les modèles enregistrés (`release_vram`)
        puis re-mesure. Renvoie True si l'objectif est atteint (ou pas de GPU :
        rien à garantir), False sinon (l'appelant peut alors dégrader : CPU,
        chunking, refus…).

        Brique réutilisable par TOUTE app avant un `load()` de modèle GPU.
        """
        target = needed_gb + headroom_gb
        info = MemoryManager.get_gpu_memory_info()
        if info is None:
            return True  # pas de GPU → rien à garantir

        # VRAM libre INTER-PROCESS : le pilote ne voit que le présent et ignore
        # qu'un autre process (service TTS, autre worker) a déjà annoncé qu'il
        # allait prendre N Go. Le registre partagé du gouverneur comble ce trou ;
        # sans lui, deux process se croient seuls et débordent ensemble.
        free_gb = MemoryManager._free_vram_gb(info)

        if free_gb >= target:
            return True
        logger.info(
            f"[MemoryManager] ensure_free_vram: {free_gb:.1f}GB libre "
            f"< {target:.1f}GB requis → reclaim…"
        )
        # Le reclaim ne porte QUE sur les modèles de CE process (registre local
        # d'unloaders) : on ne peut pas décharger le modèle d'un autre process.
        MemoryManager.release_vram(exclude=exclude)
        info = MemoryManager.get_gpu_memory_info()
        free_gb = MemoryManager._free_vram_gb(info) if info else 0.0
        ok = free_gb >= target
        logger.info(
            f"[MemoryManager] ensure_free_vram: après reclaim "
            f"{free_gb:.1f}GB libre (objectif {target:.1f}GB) → "
            f"{'OK' if ok else 'INSUFFISANT'}"
        )
        return ok

    @staticmethod
    def reessayer_apres_liberation(operation, *, proprietaire: str = '',
                                   replier_sur_cpu=None):
        """
        Exécute `operation()` ; sur erreur CUDA, LIBÈRE la VRAM et réessaie UNE fois.

        POURQUOI CETTE BRIQUE. Tout ce qui précède dans cette classe est PRÉVENTIF — on garantit
        la VRAM *avant* un `load()`. Rien ne couvrait une erreur CUDA survenant **en cours
        d'inférence**, alors que c'est le cas le plus fréquent sur un poste où plusieurs apps et
        Ollama se partagent le GPU : la place était là au chargement, un autre process l'a prise
        depuis. Constaté en supprimant le second pipeline de l'anonymizer (2026-08-13), qui
        portait le seul repli existant — et le portait mal : il basculait sur CPU sans jamais
        tenter de libérer.

        ORDRE, du moins coûteux au plus coûteux :
          1. rejouer après `release_vram()` — on récupère la VRAM des AUTRES modèles de ce
             process, ce qui traite la contention à sa cause ;
          2. `replier_sur_cpu()` si l'appelant en fournit un — à ne proposer que là où c'est
             BORNÉ. Sur une vidéo, une inférence CPU peut durer des heures : mieux vaut un
             échec net qu'un traitement qui paraît bloqué ;
          3. relever l'exception d'origine.

        `proprietaire` : nom d'app à NE PAS décharger (le nôtre — se décharger soi-même en
        pleine inférence n'aurait aucun sens).
        """
        def _est_cuda(exc) -> bool:
            texte = f"{type(exc).__name__} {exc}".lower()
            return 'cuda' in texte or 'out of memory' in texte

        try:
            return operation()
        except Exception as exc:
            if not _est_cuda(exc):
                raise
            logger.warning(f"[MemoryManager] erreur CUDA pendant l'exécution ({exc}) → "
                           f"libération puis nouvel essai")
            liberes = MemoryManager.release_vram(
                exclude={proprietaire} if proprietaire else None)
            logger.info(f"[MemoryManager] {liberes} modèle(s) déchargé(s) avant le nouvel essai")
            try:
                return operation()
            except Exception as exc2:
                if not _est_cuda(exc2) or replier_sur_cpu is None:
                    raise
                logger.warning(f"[MemoryManager] toujours en échec après libération ({exc2}) → "
                               f"repli CPU")
                return replier_sur_cpu()

    @staticmethod
    def _free_vram_gb(info) -> float:
        """VRAM libre selon la sonde de CE process (`get_gpu_memory_info` : total − alloué ici),
        MOINS ce que cette sonde ne voit pas encore — réservations des autres process, annonces
        de celui-ci.

        ⚠ Corrigé le 2026-09-14 : on retranchait `reserved_gb(exclude='celery-gpu:<pid>')`, une
        clé qu'AUCUN code ne publie (les lignes sont `<Backend>:<pid>#<clé>`). Les résidents de
        ce process étaient donc retranchés alors que `memory_allocated` les avait déjà ôtés du
        libre : chacun comptait deux fois, et `ensure_free_vram` déchargeait pour rien."""
        libre = info['free_gb'] if info else 0.0
        try:
            from wama.common.services.resource_governor import unseen_reserved_gb
            return max(0.0, libre - unseen_reserved_gb('process'))
        except Exception:
            return libre  # gouverneur/Redis indisponible → comportement d'avant

    @staticmethod
    def get_gpu_memory_info() -> Optional[Dict]:
        """Get GPU memory information using PyTorch."""
        try:
            import torch
            if not torch.cuda.is_available():
                return None

            props = torch.cuda.get_device_properties(0)
            allocated = torch.cuda.memory_allocated(0)
            reserved = torch.cuda.memory_reserved(0)
            total = props.total_memory

            return {
                'device_name': props.name,
                'total_gb': round(total / (1024**3), 2),
                'allocated_gb': round(allocated / (1024**3), 2),
                'reserved_gb': round(reserved / (1024**3), 2),
                'free_gb': round((total - allocated) / (1024**3), 2),
                'utilization_percent': round((allocated / total) * 100, 1) if total > 0 else 0,
            }
        except ImportError:
            logger.debug("PyTorch not available")
            return None
        except Exception as e:
            logger.error(f"Error getting GPU memory: {e}")
            return None

    @staticmethod
    def get_system_memory_info() -> Dict:
        """Get system RAM information."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {
                'total_gb': round(mem.total / (1024**3), 2),
                'available_gb': round(mem.available / (1024**3), 2),
                'used_gb': round(mem.used / (1024**3), 2),
                'percent': mem.percent,
            }
        except ImportError:
            return {
                'error': 'psutil not installed',
                'total_gb': 0,
                'available_gb': 0,
                'used_gb': 0,
                'percent': 0,
            }
        except Exception as e:
            logger.error(f"Error getting system memory: {e}")
            return {'error': str(e)}

    @staticmethod
    def clear_gpu_memory() -> bool:
        """Clear all GPU memory."""
        try:
            import torch
            if torch.cuda.is_available():
                # First unload all known backends
                MemoryManager._unload_all_backends()

                # Then clear CUDA cache
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                gc.collect()

                logger.info("GPU memory cleared")
                return True
        except ImportError:
            logger.debug("PyTorch not available")
        except Exception as e:
            logger.error(f"Error clearing GPU memory: {e}")
        return False

    @staticmethod
    def _unload_all_backends():
        """Décharge TOUTES les apps résidentes — via le registre, seul chemin.

        Cette fonction énumérait deux apps EN DUR (imager, describer). C'était le
        mécanisme concurrent du registre `_VRAM_UNLOADERS` : une app adoptant le
        registre n'était pas vue ici, et une app câblée ici échappait à
        `release_vram()`. Deux listes à tenir à jour = deux dérives. Il n'en reste
        qu'une, et elle se remplit toute seule (`common/backends/base.py`
        enregistre l'unloader d'une app à la première résidence réelle).
        """
        MemoryManager.release_vram()
        gc.collect()

    @staticmethod
    def unload_model(model_id: str) -> bool:
        """
        Décharge, dans CE process, le modèle du catalogue `model_id` (`<source>:<modèle>`).

        Routait auparavant vers une méthode `_unload_<app>_model` par app. Trois d'entre
        elles (anonymizer, synthesizer, enhancer) étaient des stubs qui faisaient un
        `gc.collect()` et retournaient **True** : l'appelant croyait la VRAM libérée alors
        que rien ne l'était — pire qu'un échec, puisque indétectable. On interroge
        désormais le registre, et l'absence de libération se dit `False`.

        Granularité : le MODÈLE (2026-09-14) pour les backends du contrat — ses tenseurs se
        libèrent, les autres modèles du process restent chargés ; la SOURCE pour les unloaders
        nommés hors contrat. Cette docstring disait « la granularité reste l'APP » : depuis que
        l'app se déduisait du chemin du module, elle valait `common` pour tous.
        """
        app = (model_id.split(':', 1)[0] or '').strip()
        try:
            if app == 'ollama':
                # Ollama gère sa propre mémoire (service séparé), mais il SAIT décharger à
                # la demande : `keep_alive: 0` sur /api/generate vide le modèle tout de suite.
                # Avant le 2026-08-19 on retournait True sans rien faire — le même mensonge
                # que les anciens unloaders (« l'appelant croit la VRAM libérée alors que rien
                # ne l'est »), resté invisible tant que les modèles Ollama n'apparaissaient
                # pas dans `idle_models()` (cf. `refresh_ollama_residency`).
                nom = model_id.split(':', 1)[1] if ':' in model_id else model_id
                try:
                    import requests
                    from wama.common.utils.ollama_host import ollama_base, ollama_kwargs
                    r = requests.post(f"{ollama_base()}/api/generate",
                                      json={'model': nom, 'keep_alive': 0},
                                      **ollama_kwargs(timeout=30))
                    r.raise_for_status()
                    logger.info(f"[MemoryManager] Ollama a déchargé {nom}")
                    # La ligne de résidence part avec le modèle (2026-09-14) : sans ce
                    # retrait, le gouverneur le croyait résident jusqu'à la synchro suivante.
                    try:
                        from wama.common.services.resource_governor import (
                            ollama_host_owner, release_reservation)
                        release_reservation(ollama_host_owner(nom))
                    except Exception:
                        pass
                    return True
                except Exception as exc:
                    logger.warning(f"[MemoryManager] déchargement Ollama de {nom} échoué : {exc}")
                    return False
            # Backends du CONTRAT : ceux de CE process qui tiennent CE modèle — clé catalogue
            # résolue par la règle partagée (2026-09-14). Avant, tout backend s'inscrivait sous
            # `common` : `unload_model('transcriber:whisper')` n'en trouvait plus aucun, et une
            # ligne inactive `common:…` aurait vidé tout le process.
            freed = False
            try:
                from wama.common.backends.base import unload_live_backends
                freed = unload_live_backends(model_key=model_id) > 0
            except Exception as exc:
                logger.warning(f"[MemoryManager] backends du contrat non déchargés : {exc}")
            # Unloaders NOMMÉS, pour ce qui échappe au contrat (`transcriber-diarizer`, pipeline
            # caché en variable de module) : appelés pour toute clé de leur source — décharger
            # l'ASR sans la diarisation ne libère rien d'utile.
            matched = [(name, fn) for name, fn in list(_VRAM_UNLOADERS.items())
                       if name == app or name.startswith(f'{app}-')]
            for name, fn in matched:
                try:
                    if fn():
                        freed = True
                except Exception as exc:
                    logger.warning(f"[MemoryManager] Unloader '{name}' failed: {exc}")
            if not freed:
                logger.warning(
                    f"Rien à libérer pour {model_id} dans ce process : aucun backend résident ne "
                    "tient ce modèle, aucun unloader nommé ne couvre sa source. ⚠ Le "
                    "déchargement est IN-PROCESS — depuis gunicorn, il n'atteint pas un worker.")
            return freed
        except Exception as e:
            logger.error(f"Error unloading model {model_id}: {e}")
            return False


    # =========================================================================
    # GPU Memory Strategy Management
    # =========================================================================

    @staticmethod
    def get_memory_strategy(
        model_size_gb: float,
        headroom_gb: float = 2.0,
        prefer_speed: bool = True,
        offload_peak_gb: Optional[float] = None,
    ) -> MemoryStrategy:
        """
        Determine the optimal memory strategy based on model size and available VRAM.

        Args:
            model_size_gb: Estimated model size in GB
            headroom_gb: Extra VRAM to keep free for activations/inference (default: 2GB)
            prefer_speed: If True, prefer faster strategies when possible
            offload_peak_gb: pic RÉEL en déchargement (plus gros composant), quand on le connaît

        Returns:
            MemoryStrategy enum indicating the recommended strategy

        ⚠ `offload_peak_gb` REMPLACE UNE DEVINETTE (2026-09-20, décision A de Fabien). Sans lui,
        cette fonction ne reçoit QU'UN nombre et approxime le second par des pourcentages :
        « la VRAM peut tenir 60 % du modèle → MODEL_OFFLOAD », « 30 % → SEQUENTIAL ». Ces 60 % et
        30 % sont un SUBSTITUT de « le plus gros composant tient » — la vraie condition du
        déchargement, puisqu'en déchargement un composant descend quand le suivant monte.
        Mesuré : CogVideoX pèse 20,2 Go de somme pour 10,5 de plus gros composant (52 %), FastWan
        22,5 pour 10,6 (47 %), Hunyuan 49,5 pour 32,5 (66 %). Le ratio varie du simple au
        quart : aucun pourcentage fixe ne pouvait le représenter.
        Le paramètre est OPTIONNEL et le comportement historique est intact sans lui — les trois
        appelants actuels passent une clé de preset, donc un seul nombre.
        """
        gpu_info = MemoryManager.get_gpu_memory_info()

        if gpu_info is None:
            logger.info(f"[MemoryManager] No GPU available, using CPU only")
            return MemoryStrategy.CPU_ONLY

        total_vram = gpu_info['total_gb']
        free_vram = gpu_info['free_gb']
        required_vram = model_size_gb + headroom_gb

        logger.info(f"[MemoryManager] VRAM: {total_vram:.1f}GB total, {free_vram:.1f}GB free")
        logger.info(f"[MemoryManager] Model needs ~{model_size_gb:.1f}GB + {headroom_gb:.1f}GB headroom = {required_vram:.1f}GB")

        # Strategy selection based on available VRAM
        if free_vram >= required_vram:
            # Enough VRAM for full GPU loading
            logger.info(f"[MemoryManager] Strategy: FULL_GPU (sufficient VRAM)")
            return MemoryStrategy.FULL_GPU

        elif total_vram >= required_vram:
            # Total VRAM is enough, but need to free some first
            # Use model offload which loads components as needed
            logger.info(f"[MemoryManager] Strategy: MODEL_OFFLOAD (VRAM sufficient after cleanup)")
            return MemoryStrategy.MODEL_OFFLOAD

        elif offload_peak_gb:
            # Le pic de déchargement est CONNU : plus de pourcentage à deviner. Le plus gros
            # composant tient-il, avec ses activations ? Oui → MODEL_OFFLOAD, c'est exactement
            # la condition de cette stratégie. Non → un composant seul ne rentre même pas, il
            # faut descendre au grain de la COUCHE.
            if total_vram >= offload_peak_gb + headroom_gb:
                logger.info("[MemoryManager] Strategy: MODEL_OFFLOAD (pic de déchargement "
                            f"{offload_peak_gb:.1f} + {headroom_gb:.1f} ≤ {total_vram:.1f} Go)")
                return MemoryStrategy.MODEL_OFFLOAD
            logger.info("[MemoryManager] Strategy: SEQUENTIAL_OFFLOAD (le plus gros composant "
                        f"— {offload_peak_gb:.1f} Go — ne tient pas seul)")
            return MemoryStrategy.SEQUENTIAL_OFFLOAD

        elif total_vram >= model_size_gb * 0.6:
            # VRAM can hold ~60% of model - use model offload
            # ⚠ APPROXIMATION conservée pour les appelants qui ne passent QU'un nombre (clé de
            # preset). Ces 60 % devinent « le plus gros composant tient » ; le ratio réel mesuré
            # sur le parc va de 47 % (FastWan) à 66 % (Hunyuan). Passer `offload_peak_gb` fait
            # disparaître la devinette — cette branche est le repli, pas la règle.
            logger.info(f"[MemoryManager] Strategy: MODEL_OFFLOAD (VRAM can hold partial model)")
            return MemoryStrategy.MODEL_OFFLOAD

        elif total_vram >= model_size_gb * 0.3:
            # VRAM can hold ~30% of model - use sequential offload
            logger.info(f"[MemoryManager] Strategy: SEQUENTIAL_OFFLOAD (limited VRAM)")
            return MemoryStrategy.SEQUENTIAL_OFFLOAD

        else:
            # Very limited VRAM - sequential offload or CPU
            if total_vram >= 4:  # At least 4GB for basic GPU acceleration
                logger.info(f"[MemoryManager] Strategy: SEQUENTIAL_OFFLOAD (minimal VRAM)")
                return MemoryStrategy.SEQUENTIAL_OFFLOAD
            else:
                logger.info(f"[MemoryManager] Strategy: CPU_ONLY (insufficient VRAM)")
                return MemoryStrategy.CPU_ONLY

    @staticmethod
    def get_strategy_for_model(model_type: str, headroom_gb: float = 2.0) -> MemoryStrategy:
        """
        Get memory strategy for a known model type.

        Args:
            model_type: Model type key (e.g., 'flux', 'sdxl', 'whisper-large')
            headroom_gb: Extra VRAM to keep free

        Returns:
            MemoryStrategy for the model
        """
        # `preset_vram_gb` et NON `MODEL_SIZE_PRESETS.get` (2026-09-16) : les deux lectures de la
        # MÊME table divergeaient — ici le nom EXACT, là la clé la plus SPÉCIFIQUE qui matche.
        # Un appelant qui passerait un identifiant de modèle (`ltx-video-13b-0.9.8-distilled`)
        # tombait donc sur le défaut de 4 Go, et faisait tenter FULL_GPU à un modèle de 14 à
        # 23 Go — le débordement WDDM du 29/07. Aujourd'hui tous les appelants passent une clé de
        # preset (`flux`, `cogvideox`, `sdxl`…) : le piège était LATENT, il se ferme avant qu'un
        # appelant n'y tombe. Une seule règle de lecture, celle de `preset_vram_gb`.
        model_size = preset_vram_gb(model_type) or 4.0  # inconnu → 4 Go, comme avant
        return MemoryManager.get_memory_strategy(model_size, headroom_gb)

    @staticmethod
    def apply_memory_strategy(
        pipeline,
        strategy: MemoryStrategy,
        device: str = "cuda"
    ):
        """
        Apply a memory strategy to a Diffusers pipeline.

        Includes automatic fallback chain: FULL_GPU -> MODEL_OFFLOAD -> SEQUENTIAL_OFFLOAD
        This handles CUDA errors gracefully.

        Args:
            pipeline: A Diffusers pipeline object
            strategy: The MemoryStrategy to apply
            device: Target device ('cuda', 'cpu')

        Returns:
            The pipeline with the strategy applied
        """
        import torch

        _cap_cuda_allocator()

        def reset_cuda_state():
            """Reset CUDA state after errors."""
            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                    gc.collect()
                    logger.info("[MemoryManager] CUDA state reset")
                except Exception:
                    pass

        def try_full_gpu():
            """
            Move each pipeline component to GPU one at a time with a CUDA sync
            between each.  This avoids the monolithic pipeline.to("cuda") call
            which, under WSL2/WDDM, iterates thousands of tensors individually
            in Python — each CUDA malloc taking ~8 ms, yielding 10–15 minutes
            total and eventually triggering Windows TDR.
            """
            nonlocal pipeline
            logger.info(f"[MemoryManager] Applying FULL_GPU strategy (per-component)")
            moved_any = False
            for attr in ('transformer', 'unet', 'denoising_unet', 'vae',
                         'text_encoder', 'text_encoder_2', 'image_encoder'):
                component = getattr(pipeline, attr, None)
                if component is None or not hasattr(component, 'parameters'):
                    continue

                # Re-vérifier AVANT chaque déplacement : la stratégie a été décidée une
                # seule fois sur une taille de modèle DÉCLARÉE (presets), qui peut être
                # très sous-estimée. Sans ce contrôle, un composant trop gros ne lève pas
                # d'OOM sous WDDM — il déborde en RAM hôte et fait paniquer le noyau WSL
                # (cf. _cap_cuda_allocator). On échoue net pour tomber sur MODEL_OFFLOAD.
                #
                # On passe par la brique COMMUNE ensure_free_vram (mesure → reclaim des
                # unloaders enregistrés → re-mesure) : un composant qui ne tient pas
                # seulement parce qu'une AUTRE app squatte la VRAM doit d'abord
                # déclencher un reclaim, pas faire échouer FULL_GPU.
                size_gb = _component_size_gb(component)
                if size_gb and not MemoryManager.ensure_free_vram(
                    size_gb, headroom_gb=FULL_GPU_MIN_FREE_GB
                ):
                    info = MemoryManager.get_gpu_memory_info() or {}
                    raise RuntimeError(
                        f"CUDA out of memory (pré-contrôle FULL_GPU) : {attr} pèse "
                        f"{size_gb:.1f} GB, seulement {info.get('free_gb', 0):.1f} GB "
                        f"libres après reclaim (marge requise {FULL_GPU_MIN_FREE_GB:.1f} GB)"
                    )

                logger.info(f"[MemoryManager]   → moving {attr} to {device} ({size_gb:.1f} GB)…")
                setattr(pipeline, attr, component.to(device))
                torch.cuda.synchronize()
                vram = torch.cuda.memory_allocated() / (1024 ** 3)
                logger.info(f"[MemoryManager]   ✓ {attr} on {device} (VRAM used: {vram:.1f} GB)")
                moved_any = True
            if not moved_any:
                # Fallback for pipelines with non-standard component names
                pipeline = pipeline.to(device)
            logger.info(f"[MemoryManager] Pipeline loaded fully on {device}")
            return True

        def try_model_offload():
            """Try model CPU offload."""
            nonlocal pipeline
            logger.info(f"[MemoryManager] Applying MODEL_OFFLOAD strategy")
            pipeline.enable_model_cpu_offload()
            logger.info(f"[MemoryManager] Model CPU offload enabled")
            return True

        def try_sequential_offload():
            """Try sequential CPU offload."""
            nonlocal pipeline
            logger.info(f"[MemoryManager] Applying SEQUENTIAL_OFFLOAD strategy")
            pipeline.enable_sequential_cpu_offload()
            logger.info(f"[MemoryManager] Sequential CPU offload enabled")
            return True

        try:
            if strategy == MemoryStrategy.FULL_GPU:
                try:
                    try_full_gpu()
                except Exception as e:
                    error_str = str(e).lower()
                    if 'cuda' in error_str or 'out of memory' in error_str:
                        logger.warning(f"[MemoryManager] FULL_GPU failed ({e}), falling back to MODEL_OFFLOAD")
                        reset_cuda_state()
                        try:
                            try_model_offload()
                        except Exception as e2:
                            logger.warning(f"[MemoryManager] MODEL_OFFLOAD failed ({e2}), trying SEQUENTIAL_OFFLOAD")
                            reset_cuda_state()
                            try_sequential_offload()
                    else:
                        raise

            elif strategy == MemoryStrategy.MODEL_OFFLOAD:
                try:
                    try_model_offload()
                except Exception as e:
                    logger.warning(f"[MemoryManager] MODEL_OFFLOAD failed ({e}), trying SEQUENTIAL_OFFLOAD")
                    reset_cuda_state()
                    try:
                        try_sequential_offload()
                    except Exception as e2:
                        logger.warning(f"[MemoryManager] SEQUENTIAL_OFFLOAD failed ({e2}), trying FULL_GPU")
                        reset_cuda_state()
                        try_full_gpu()

            elif strategy == MemoryStrategy.SEQUENTIAL_OFFLOAD:
                try:
                    try_sequential_offload()
                except Exception as e:
                    logger.warning(f"[MemoryManager] SEQUENTIAL_OFFLOAD failed ({e}), trying MODEL_OFFLOAD")
                    reset_cuda_state()
                    try:
                        try_model_offload()
                    except Exception as e2:
                        logger.warning(f"[MemoryManager] MODEL_OFFLOAD also failed ({e2})")
                        raise

            elif strategy == MemoryStrategy.CPU_ONLY:
                logger.info(f"[MemoryManager] Applying CPU_ONLY strategy")
                pipeline = pipeline.to("cpu")
                logger.info(f"[MemoryManager] Pipeline loaded on CPU")

            return pipeline

        except Exception as e:
            logger.error(f"[MemoryManager] All strategies failed: {e}")
            # Last resort - try sequential offload (most stable)
            reset_cuda_state()
            try:
                logger.info("[MemoryManager] Last resort: trying sequential CPU offload")
                pipeline.enable_sequential_cpu_offload()
                logger.info("[MemoryManager] Sequential CPU offload enabled as last resort")
            except Exception as e2:
                logger.error(f"[MemoryManager] Last resort also failed: {e2}")
            return pipeline

    # =========================================================================
    # Pipeline Loading (centralized format handling)
    # =========================================================================

    @staticmethod
    def load_pipeline(pipeline_class, model_id: str, **kwargs):
        """
        Load a Diffusers pipeline with automatic safetensors-to-bin fallback.

        Centralizes format handling so backends don't duplicate this logic.
        Tries safetensors first (faster, safer), falls back to .bin if unavailable.

        Args:
            pipeline_class: The Diffusers pipeline class (e.g., StableDiffusionPipeline)
            model_id: HuggingFace model ID or local path
            **kwargs: Additional arguments passed to from_pretrained()

        Returns:
            The loaded pipeline instance
        """
        try:
            return pipeline_class.from_pretrained(model_id, **kwargs)
        except EnvironmentError as e:
            if kwargs.get('use_safetensors', False):
                logger.warning(
                    f"[MemoryManager] No safetensors weights found for {model_id}, "
                    f"falling back to PyTorch .bin format"
                )
                kwargs['use_safetensors'] = False
                return pipeline_class.from_pretrained(model_id, **kwargs)
            raise

    @staticmethod
    def load_single_file_pipeline(pipeline_class, repo_id: str, filename: str, cache_dir: str = None, **kwargs):
        """
        Load a Diffusers pipeline from a single safetensors/ckpt file on HuggingFace.

        Used for models that are distributed as single checkpoint files
        (e.g., XpucT/Deliberate) rather than in diffusers multi-folder format.

        Downloads the file first using hf_hub_download (with progress tracking
        and proper caching), then loads from the local path.

        Args:
            pipeline_class: The Diffusers pipeline class (e.g., StableDiffusionPipeline)
            repo_id: HuggingFace repo ID (e.g., 'XpucT/Deliberate')
            filename: Weight file name (e.g., 'Deliberate_v6.safetensors')
            cache_dir: Optional cache directory for downloaded files
            **kwargs: Additional arguments passed to from_single_file()

        Returns:
            The loaded pipeline instance
        """
        from huggingface_hub import hf_hub_download

        logger.info(f"[MemoryManager] Loading single-file model: {repo_id}/{filename}")

        # Download to cache first (with progress bar and proper caching)
        download_kwargs = {"repo_id": repo_id, "filename": filename}
        if cache_dir:
            download_kwargs["cache_dir"] = cache_dir
        logger.info(f"[MemoryManager] Downloading {filename} from {repo_id} (cache: {cache_dir or 'default'})...")
        local_path = hf_hub_download(**download_kwargs)
        logger.info(f"[MemoryManager] File ready: {local_path}")

        return pipeline_class.from_single_file(local_path, **kwargs)

    @staticmethod
    def apply_strategy_for_model(
        pipeline,
        model_type: str,
        device: str = "cuda",
        headroom_gb: float = 2.0
    ):
        """
        Convenience method: determine and apply the best strategy for a model type.

        Args:
            pipeline: A Diffusers pipeline object
            model_type: Model type key (e.g., 'flux', 'sdxl')
            device: Target device
            headroom_gb: Extra VRAM headroom

        Returns:
            The pipeline with the optimal strategy applied
        """
        strategy = MemoryManager.get_strategy_for_model(model_type, headroom_gb)
        return MemoryManager.apply_memory_strategy(pipeline, strategy, device)

    @staticmethod
    def apply_offload_strategy(
        pipeline,
        model_size_gb: float,
        device: str = "cuda",
        headroom_gb: float = 2.0,
    ) -> tuple:
        """
        Select the optimal memory strategy for the given model size, apply it,
        and return ``(pipeline, is_on_gpu)``.

        ``is_on_gpu`` is True when the pipeline was placed entirely on GPU
        (faster, no Windows TDR risk from long GPU-idle periods).
        It is False when CPU offload is active (MODEL_OFFLOAD / SEQUENTIAL_OFFLOAD),
        in which case callers must use a CPU torch.Generator.

        On RTX 4090 (24 GB), any model ≤ 20 GB with headroom_gb=4 will use
        FULL_GPU automatically.  Callers should pass headroom_gb=4.0 for
        heavy diffusion models.

        Typical usage::

            self._pipe, is_on_gpu = MemoryManager.apply_offload_strategy(
                self._pipe, model_size_gb=16.0, headroom_gb=4.0
            )
            self._cpu_offload = not is_on_gpu
        """
        import torch

        strategy = MemoryManager.get_memory_strategy(model_size_gb, headroom_gb)
        pipeline = MemoryManager.apply_memory_strategy(pipeline, strategy, device)

        # Detect actual placement by probing the main denoising component.
        # After .to("cuda") all parameters are on CUDA.
        # After enable_{model,sequential}_cpu_offload they remain on CPU.
        is_on_gpu = False
        if torch.cuda.is_available():
            for attr in ('transformer', 'unet', 'denoising_unet'):
                component = getattr(pipeline, attr, None)
                if component is not None:
                    try:
                        param = next(component.parameters(), None)
                        if param is not None:
                            is_on_gpu = (param.device.type == 'cuda')
                    except Exception:
                        pass
                    break

        placement = 'CUDA (full GPU)' if is_on_gpu else 'CPU offload'
        logger.info(f"[MemoryManager] Pipeline placement: {placement}")
        return pipeline, is_on_gpu

    @staticmethod
    def estimate_model_size(model_path: str) -> float:
        """
        Estimate model size from file path or known patterns.

        Args:
            model_path: Path or identifier of the model

        Returns:
            Estimated size in GB
        """
        import os

        path_lower = model_path.lower()

        # Presets : la clé la PLUS SPÉCIFIQUE gagne (la plus longue qui matche).
        # ⚠️ NE PAS revenir à un « premier qui matche » : les clés se préfixent entre elles
        # ('qwen-image' ⊂ 'qwen-image-edit', 'flux' ⊂ 'flux-schnell', 'ltx-video' ⊂
        # 'ltx-video-fp8'). En ordre d'insertion, la clé GÉNÉRIQUE gagnait — Qwen-Image-Edit
        # héritait des 38 Go de Qwen-Image, FLUX-schnell et flux2-klein-4b des 24 Go de FLUX :
        # trois modèles qui TIENNENT sur 24 Go étaient envoyés en CPU offload pour rien.
        matches = [(len(key), size) for key, size in MODEL_SIZE_PRESETS.items()
                   if key in path_lower]
        if matches:
            return max(matches, key=lambda m: m[0])[1]

        # Try to get actual file size
        if os.path.isfile(model_path):
            try:
                size_bytes = os.path.getsize(model_path)
                # Model in memory is typically larger than file (decompression, buffers)
                return (size_bytes / (1024**3)) * 1.3
            except Exception:
                pass

        # Default estimate based on common patterns
        if 'xl' in path_lower or 'xlarge' in path_lower:
            return 6.0
        elif 'large' in path_lower or '-l' in path_lower:
            return 4.0
        elif 'medium' in path_lower or '-m' in path_lower:
            return 2.0
        elif 'small' in path_lower or '-s' in path_lower:
            return 1.0
        elif 'nano' in path_lower or 'tiny' in path_lower or '-n' in path_lower:
            return 0.5

        # Conservative default
        return 4.0
