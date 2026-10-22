"""
Backend IMAGE du describer — cascade Ollama vision + repli BLIP local.

CONTRAT COMMUN des backends « texte » (marche B1 describer, 2026-09-03) :
    callable(input_path, options=dict, progress_callback=fn, partial_callback=fn,
             console=fn) -> str
`options` = valeurs EFFECTIVES lues des colonnes (modèle événementiel §23.2quater) ;
les trois callbacks sont OPTIONNELS (no-op par défaut). Le texte rendu est le résultat —
c'est la GLU (task_skeleton) qui le persiste dans la colonne déclarée (`RESULT`).

Traduit de `utils/image_describer.py` (2026-09-03, marche B1) : mêmes moteurs, même
cascade, signature ORM-free — le backend ne connaît plus l'ORM, donc la jumelle du bac à
sable peut copier ce paquet et l'exécuter tel quel.

Cascade vision (ordre de préférence) :
  1. Ollama vision (gemma4:12b > gemma4:e4b) — qualité, hors contrat VRAM (HTTP hôte)
  2. BLIP local (`blip_backend`, contrat BaseModelBackend) — repli sans Ollama
C'est le comportement de « auto ». Un modèle DÉSIGNÉ (`options['vision_model']`, 2026-10-13 —
`model_choice.vision_for`) remplace la cascade : BLIP, ou ce modèle Ollama seul.
"""

import logging
from typing import Optional

from wama.common.utils.param_schema import sampling_of

logger = logging.getLogger(__name__)

# Cached list of available Ollama models (refreshed per worker process start)
_ollama_available_models: Optional[set] = None


def _noop(*_a, **_k):
    return None


# ---------------------------------------------------------------------------
# Ollama vision helpers
# ---------------------------------------------------------------------------

def _gpu_safe_mode() -> bool:
    """Garde GPU (WAMA_GPU_SAFE_MODE) — JUMELLE de la garde du triage VLM du smoke
    (af378453, crashs hôte du 02/09 : la montée VRAM Ollama est le facteur commun).
    Une garde se pose avec ses jumeaux : ce chemin-ci monte Ollama vision de la même
    façon, sans opt-in utilisateur (cascade AUTOMATIQUE). Les usages Ollama DEMANDÉS
    (résumé LLM, cohérence — toggles explicites) restent hors garde."""
    from django.conf import settings
    return bool(getattr(settings, 'WAMA_GPU_SAFE_MODE', False))


def _get_available_ollama_models() -> set:
    """Return the set of model names currently pulled in Ollama."""
    global _ollama_available_models
    if _ollama_available_models is not None:
        return _ollama_available_models
    try:
        import httpx
        from wama.common.utils.ollama_host import ollama_base
        host = ollama_base()
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            resp = client.get(f"{host}/api/tags")
        if resp.status_code == 200:
            models = {m['name'] for m in resp.json().get('models', [])}
            _ollama_available_models = models
            return models
    except Exception as e:
        logger.debug(f"[image_backend] Ollama unavailable: {e}")
    _ollama_available_models = set()
    return set()


#: Longueur maximale d'une description, en jetons.
VISION_NUM_PREDICT = 1024


def _describe_with_ollama_vision(model: str, image_path: str, prompt: str,
                                 sampling: Optional[dict] = None) -> Optional[str]:
    """La description de l'image par le modèle de vision Ollama `model`, ou None s'il ne répond
    pas. Par le client de vision COMMUN (`vision_probe.describe_image_ollama`, 2026-10-20) : ce
    module tenait le sien, du même `/api/chat` à images, plus un repli sur `/api/generate` pour
    les anciens Ollama et moondream — mort sur l'Ollama servi (0.40.6, où `/api/chat` porte les
    images de tout modèle de vision) et pour les seuls modèles qu'il reçoit (catalogue, vision).
    `sampling` : température, graine et top_p de la card (`sampling_of(options, 'vision_')`,
    2026-10-22) ; un None = celui du modèle."""
    from wama.model_manager.services.vision_probe import describe_image_ollama
    result = describe_image_ollama(image_path, model=model, prompt=prompt,
                                   num_predict=VISION_NUM_PREDICT,
                                   temperature=(sampling or {}).get('temperature'),
                                   seed=(sampling or {}).get('seed'),
                                   top_p=(sampling or {}).get('top_p'))
    if result.get('ok') and result.get('description'):
        return result['description']
    logger.debug(f"[image_backend] {model} unavailable: {result.get('error') or 'réponse vide'}")
    return None


def _best_ollama_vision_model() -> Optional[str]:
    """
    Return the best available Ollama vision model name, or None.
    Priority: gemma4:12b > gemma4:e4b (12b validé bon describer FR, 256K ; e4b = repli
    plus léger + audio). Liste confrontée au RÉEL à l'appel (fallthrough sur les modèles
    présents) — nettoyée le 2026-08-12 des entrées jamais installées (qwen3-vl:8b,
    moondream…) : un candidat futur passe par la prospection, pas par du vocabulaire
    mort ici. Correctif de fond = capacité `vision` au catalogue (cf. llm_utils).
    """
    available = _get_available_ollama_models()
    priority = ['gemma4:12b', 'gemma4:e4b']
    for model in priority:
        # Match prefix (Ollama can append :latest)
        for avail in available:
            if avail == model or avail.startswith(model + ':'):
                return avail
    return None


# Prompts vision localisés — graine de l'orchestration de traduction (ROADMAP §10.B) :
# si le modèle vision est multilingue, on le prompte DIRECTEMENT dans la langue de sortie
# (évite la chaîne « caption EN → reformatage FR » en aval). Sinon EN.
_VISION_PROMPTS = {  # wama:redondance-ok — prompts vision par style (info nouvelle ; styles manquants → fallback)
    'detailed':      {'en': "Describe this image in detail.",
                      'fr': "Décris cette image en détail."},
    'scientific':    {'en': "Provide a scientific analysis of this image.",
                      'fr': "Fournis une analyse scientifique de cette image."},
    'bullet_points': {'en': "List the key elements visible in this image.",
                      'fr': "Liste les éléments clés visibles dans cette image."},
    'brief':         {'en': "Briefly describe this image.",
                      'fr': "Décris brièvement cette image."},
}


def _is_multilingual_vision(model: Optional[str]) -> bool:
    """Modèles vision Ollama multilingues (décrivent directement en langue cible)."""
    m = (model or '').lower()
    return m.startswith('gemma4') or 'qwen' in m  # moondream = anglophone


def _vision_prompt(output_style: str, output_language: str, model: Optional[str]) -> str:
    """Prompt vision dans output_language si le modèle est multilingue, sinon EN (reformaté en aval)."""
    spec = _VISION_PROMPTS.get(output_style, _VISION_PROMPTS['brief'])
    lang = output_language if (_is_multilingual_vision(model) and output_language in spec) else 'en'
    return spec[lang]


def vision_candidates(options: dict) -> list:
    """Les modèles de vision qu'une image PEUT charger, dans l'ordre où `describe_image` les
    essaie : le modèle désigné seul ; sous « auto », le meilleur modèle Ollama vision installé
    puis BLIP, son repli (BLIP seul sous la garde GPU). La glu les demande à la route AVANT le
    chargement (2026-10-19) — le repli compris : sans cela, BLIP absent se serait téléchargé au
    chargement, à côté du catalogue."""
    from .model_choice import BLIP, vision_for
    chosen = vision_for(options or {})
    if chosen:
        return [chosen]
    best = None if _gpu_safe_mode() else _best_ollama_vision_model()
    return [best, BLIP] if best else [BLIP]


def describe_image(input_path: str, options: dict = None,
                   progress_callback=None, partial_callback=None, console=None) -> str:
    """Décrit une image — contrat commun « texte » (voir tête de module)."""
    options = options or {}
    progress = progress_callback or _noop
    partial = partial_callback or _noop
    console = console or _noop

    output_style = options.get('output_style') or 'detailed'
    output_language = options.get('output_language') or 'fr'
    max_length = int(options.get('max_length') or 500)

    console("Chargement de l'image…")
    progress(20)

    try:
        from PIL import Image

        # Load image
        image = Image.open(input_path).convert('RGB')
        console(f"Taille image: {image.width}x{image.height}")

        progress(30)
        partial("Analyse de l'image…")

        # --- Pick the vision model first: its language ability decides the prompt language ---
        # Graine §10.B : prompter direct dans la langue de sortie si le modèle est multilingue
        # (gemma4/qwen), au lieu de la chaîne « caption EN → reformatage FR » en aval.
        # Le modèle DÉSIGNÉ par la card (`vision_model`, 2026-10-13) passe avant la cascade : un
        # usage DEMANDÉ, hors garde GPU (qui ne couvre que la cascade AUTOMATIQUE), jamais
        # remplacé en silence s'il ne répond pas.
        from .model_choice import BLIP, vision_for
        chosen = vision_for(options)
        if chosen == BLIP:
            console("Modèle de vision désigné : BLIP.")
        elif not chosen and _gpu_safe_mode():
            console("Garde GPU active (WAMA_GPU_SAFE_MODE) : cascade Ollama vision sautée — BLIP local.")
        first = vision_candidates(options)[0]
        ollama_model = None if first == BLIP else first
        moondream_prompt = _vision_prompt(output_style, output_language, ollama_model)
        caption = None
        if ollama_model:
            console(f"Essai {ollama_model} (Ollama)…")
            caption = _describe_with_ollama_vision(ollama_model, input_path, moondream_prompt,
                                                   sampling_of(options, 'vision_'))
            if caption:
                console(f"Description générée avec {ollama_model} ✓")
                progress(70)
                partial(caption)
            elif chosen:
                raise RuntimeError(f"Le modèle de vision désigné « {ollama_model} » n'a rendu "
                                   "aucune description (Ollama joignable ? modèle installé ?).")

        if not caption:
            # --- Fallback: BLIP ---
            if not _gpu_safe_mode() and chosen != BLIP:
                msg = "Aucun modèle Ollama vision disponible" if not ollama_model else f"{ollama_model} indisponible"
                console(f"{msg}, utilisation de BLIP…")
            partial("Chargement du modèle BLIP…")

            from . import get_blip
            blip = get_blip()
            blip.load()

            progress(50)
            console("Génération de la description (BLIP)…")
            partial("Analyse BLIP…")

            # Amorce de conditionnement — POLITIQUE de style (le backend BLIP est neutre)
            if output_style == 'detailed':
                blip_text = "a photograph of"
            elif output_style == 'scientific':
                blip_text = "this image shows"
            else:
                blip_text = None

            max_new_tokens = min(200 if output_style in ('detailed', 'scientific') else 100, max_length)
            caption = blip.process(image=image, prefix=blip_text,
                                   max_new_tokens=max_new_tokens,
                                   num_beams=5, repetition_penalty=1.2)
            console("Description générée avec BLIP ✓")
            progress(70)
            partial(caption)

        # Post-process based on format
        result = format_image_result(caption, output_style, output_language)

        progress(85)
        console("Description generated successfully")

        # Translate if needed
        if output_language == 'fr':
            result = translate_to_french(result, console)
            progress(90)

        return result

    except Exception as e:
        logger.exception(f"Error describing image: {e}")
        raise


def format_image_result(caption: str, output_style: str, language: str) -> str:
    """Format the caption based on output format."""
    caption = caption.strip()

    # Capitalize first letter
    if caption and caption[0].islower():
        caption = caption[0].upper() + caption[1:]

    # Add period if missing
    if caption and not caption.endswith('.'):
        caption += '.'

    if output_style == 'bullet_points':
        # Convert to bullet points
        sentences = caption.replace('. ', '.\n').split('\n')
        return '\n'.join(f"- {s.strip()}" for s in sentences if s.strip())

    elif output_style == 'scientific':
        return f"Image Analysis:\n\n{caption}\n\nNote: This description was generated automatically using computer vision."

    elif output_style == 'summary':
        # Keep it short
        if len(caption) > 200:
            caption = caption[:197] + '...'
        return caption

    else:  # detailed
        return caption


# Traduction : DOMICILE UNIQUE dans text_backend (l'ancienne copie locale de
# `image_describer.translate_to_french` doublonnait celle de text_describer — résorbée
# par le portage, zéro duplication).
from .text_backend import translate_to_french  # noqa: E402
