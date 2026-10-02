"""
Composer Celery Tasks — Music and SFX generation.

Squelette (gardes, progression, chrono, statuts, ETA, console, notifications, tâche déclarée
au gouverneur, garde-temps, signal et révision) = brique COMMUNE
`common/utils/task_skeleton.run_item_task`. Ce fichier ne porte que la GLU : tirage du modèle
« auto », plafond de durée, nommage et rangement des sorties, traduction du prompt, appel du
backend résolu par le catalogue, conversion de format.

DEUX PROCESS depuis le 2026-10-02 (pilote du pipeline porté par la card, `ROUTE §10.6` P3) :
`plan` (la consigne → une partition) puis `render` (→ l'audio). Ils sont DÉCLARÉS dans
`function_specs.PIPELINE` ; le squelette joue ceux que le lancement retient et tient une ligne
d'exécution par process. `plan` n'a lieu que pour un modèle dont le moteur écrit sa partition
avant de la jouer (YuE2) — pour tous les autres la card n'a qu'un process, `render`, et se
comporte comme avant.

⚠ RUNNING et `task_id` ne sont plus posés ici : ce sont les gestes des LANCEURS
(`begin_processing` dans les vues `start` / `restart` / `start_all`, la fabrique de lots et
`tool_api`), avant l'envoi de la tâche — la convention du squelette.
"""

import logging
import os

from celery import shared_task

from .models import ComposerGeneration

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def compose_task(self, generation_id: int):
    """Generate music or SFX for a ComposerGeneration instance."""
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    run_item_task(self, app_id='composer', model=ComposerGeneration, item_id=generation_id,
                  pipeline=PIPELINE, processes={'plan': _plan, 'render': _render},
                  model_key=_model_key, notify_label='Composer')


# ── Tirage « auto » AU LANCEMENT ─────────────────────────────────────────────────────────────
# Résolu UNE fois par lancement et mémorisé sur l'instance : le squelette demande la clé du
# modèle (`model_key` : annonce du téléchargement des poids, durée max réglée par modèle) AVANT
# la glu, qui doit parler du même modèle. L'élément GARDE son « auto » : une relance ré-arbitre
# avec la VRAM du moment et le curseur reste visible. Le modèle retenu vit dans la console,
# l'ETA, le résultat (`models`) et la ligne d'exécution de chaque process.
# ⚠ Jusqu'au 2026-10-02 la tâche ÉCRIVAIT le modèle tiré dans le réglage `model` : le choix
# « auto » de l'utilisateur était remplacé à la première génération (relance figée sur ce
# modèle) — le défaut que le contrat du squelette nomme (`fields` : des résultats, jamais un
# réglage).
# ⚠ Une exception au tirage : un rendu qui REPREND une partition déjà écrite emploie le modèle
# qui l'a écrite (lu sur la ligne du process `plan`) — un autre tirage rendrait la partition
# d'un modèle avec un modèle qui ne la suit peut-être pas.

def _model_key(gen) -> str:
    """Clé de catalogue du modèle de CE lancement : le choix explicite tel quel, sinon le modèle
    de la partition reprise, sinon le tirage."""
    if not getattr(gen, '_resolved_model', None):
        from wama.common.utils.auto_model import is_auto
        from .utils.auto_model import resolve_auto_model
        from .utils.model_choice import normalize
        if is_auto(gen.model):
            chosen = _model_of_the_kept_plan(gen) or resolve_auto_model(gen)
        else:
            chosen = gen.model
        gen._resolved_model = normalize(chosen)
    return gen._resolved_model


def _model_of_the_kept_plan(gen) -> str:
    """Le modèle qui a écrit la partition que ce lancement va reprendre — '' s'il n'en reprend
    aucune (rien n'a tourné, la partition est périmée, ou la card entière est rejouée)."""
    from wama.common.services import process_runs
    from .function_specs import PIPELINE
    kept = process_runs.line(gen, 'plan')
    if kept is None or not kept.model_key:
        return ''
    return kept.model_key if PIPELINE.resumes_from(gen, 'plan', kept.model_key) else ''


# ── Ce que les deux process partagent, résolu UNE fois par lancement ─────────────────────────

def _announce_model(gen, ctx, catalog_key) -> None:
    """Dit le modèle tiré — une fois par lancement, quel que soit le premier process joué."""
    from wama.common.utils.auto_model import is_auto, quality_intent_of
    if getattr(gen, '_model_announced', False) or not is_auto(gen.model):
        return
    gen._model_announced = True
    ctx.console(f"[Composer] 🧠 Auto → {catalog_key} (capacités + VRAM libre au lancement, "
                f"curseur qualité {quality_intent_of(gen, ctx.app_id)}/100)")


def _routed_prompt(gen, ctx) -> str:
    """PromptPipeline (§16.6) : MusicGen/AudioCraft est entraîné en anglais → un prompt FR est
    traduit avant génération (métadonnée PROMPT_TARGETS['composer'], KIND generative).
    Résource-safe : passthrough si déjà EN / modèle multilingue. Traduit UNE fois par
    lancement : la partition et le rendu lisent la même consigne."""
    if getattr(gen, '_routed_prompt', None) is None:
        from wama.common.utils.app_metadata import process_prompt_for
        gen._routed_prompt = process_prompt_for(ctx.app_id, 'prompt', gen.prompt,
                                                instance=gen, user=gen.user, console=ctx.console)
    return gen._routed_prompt


def _backend(gen, catalog_key):
    """Le backend de ce lancement — UNE instance pour les deux process : le moteur chargé pour
    la partition sert au rendu.

    Le MODÈLE porte son moteur (catalogue, `composition.runtime.engine`) ; le backend s'en
    DÉRIVE — l'app ne choisit rien et n'importe aucun module par son chemin (ROUTE §10.3).
    ⚠ Aucun repli « par défaut » : un modèle non résolu arrête le job en le DISANT."""
    if getattr(gen, '_backend', None) is None:
        from wama.common.backends.manager import backend_for_key
        backend_class = backend_for_key(catalog_key)
        if backend_class is None:
            raise RuntimeError(
                f"Modèle « {gen.model} » : aucun backend résolu depuis le catalogue "
                f"({catalog_key} absent, ou sans moteur déclaré)")
        gen._backend = backend_class()
    return gen._backend


def _output_place(gen, ctx, catalog_key, ext):
    """(dossier relatif, nom, chemin absolu) d'une sortie de cette card.

    Le dossier vient de la brique (`app_media_dir`) : il décide où le fichier atterrit ET ce que
    la base retient. Composé à la main (`composer/<uid>/output`) jusqu'au 2026-10-02, il aurait
    recréé l'ancien arbre à la première génération après la bascule des médias du 2026-09-12
    (mesuré : aucune génération depuis — les 5 sorties en base ont été migrées) — et la règle de
    propriété n'aurait jamais reconnu ce fichier comme celui de l'app.
    Le nom vient de la brique COMMUNE de nommage (2026-08-25). ⚠ Le rendu a CHANGÉ ce jour-là,
    volontairement (arbitrage Fabien : l'homogénéité prime sur le portage à l'identique) :
    `{modèle}_{uuid8}.wav` → `audio{id}_{modèle}.wav`. L'uuid était unique mais MUET — il ne
    rattachait le fichier à aucune card."""
    from django.conf import settings
    from wama.common.utils.media_paths import app_media_dir
    from wama.common.utils.model_keys import model_id
    from wama.common.utils.output_naming import compose_output_name
    rel_dir = app_media_dir(ctx.app_id, gen.user_id, 'output')
    abs_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    name = compose_output_name(app=ctx.app_id, model=model_id(catalog_key), item_id=gen.id,
                               ext=ext)
    return rel_dir, name, os.path.join(abs_dir, name)


# ── Glu ──────────────────────────────────────────────────────────────────────────────────────

def _plan(gen, ctx):
    """GLU du process `plan` (contrat `task_skeleton`) : la consigne → une partition ABC, rangée
    comme une sortie de la card (`planned_score`). N'est jouée que pour un modèle dont le moteur
    le déclare (`function_specs._plan_applies`)."""
    from wama.common.utils.model_keys import model_id

    catalog_key = _model_key(gen)
    _announce_model(gen, ctx, catalog_key)
    ctx.console(f"[Composer] Partition : {catalog_key} — {gen.prompt[:60]}…")
    try:
        text = _backend(gen, catalog_key).plan_score(
            model_id=model_id(catalog_key), prompt=_routed_prompt(gen, ctx),
            progress_callback=ctx.progress)
    except Exception:
        ctx.reset_progress()
        raise
    rel_dir, name, abs_path = _output_place(gen, ctx, catalog_key, '.abc')
    with open(abs_path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    score_rel = f'{rel_dir}/{name}'
    return {
        'fields': {'planned_score': score_rel},
        'output_ref': score_rel,
        'label': name,
        'console_success': f"✓ Partition écrite : {name}",
        'models': [catalog_key],
    }


def _render(gen, ctx):
    """GLU du process `render` : une exception = FAILURE (le squelette pose statut, console et
    notification) ; l'aperçu partiel et la progression sont remis à zéro ICI."""
    from django.conf import settings
    from wama.common.utils.auto_model import is_auto
    from wama.common.utils.model_keys import model_id
    from wama.common.utils.preview_utils import clear_partial, emit_streaming_peaks
    from .utils.model_config import clamp_duration

    catalog_key = _model_key(gen)
    auto = is_auto(gen.model)
    _announce_model(gen, ctx, catalog_key)

    # Durée plafonnée par la capacité du modèle FINAL (source unique = clamp_duration : schéma +
    # max_duration du modèle). Seul point où le vrai modèle est connu. Le plafond n'est ÉCRIT
    # dans le réglage que si le modèle a été DÉSIGNÉ : sous « auto », c'est le plafond du modèle
    # tiré cette fois-ci, pas un choix de l'utilisateur — l'écrire figerait la durée du prochain
    # tirage, comme écrire le modèle figeait le tirage lui-même.
    duration = clamp_duration(gen.duration, model_id(catalog_key))
    if duration != gen.duration:
        ctx.console(f"[Composer] Durée {gen.duration:g}s → {duration:g}s "
                    f"(max du modèle {catalog_key})")
        if not auto:
            ComposerGeneration.objects.filter(pk=gen.pk).update(duration=duration)
    ctx.console(f"[Composer] Démarrage : {catalog_key} — {gen.prompt[:60]}…")

    output_rel_dir, output_filename, output_abs_path = _output_place(gen, ctx, catalog_key, '.wav')

    melody_abs = (os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name)
                  if gen.melody_reference else None)
    # Partition à suivre : celle que l'utilisateur FOURNIT (port `reference_score`, 2026-10-01)
    # prime ; sinon celle que le process `plan` a écrite (`planned_score` — à ce lancement, ou à
    # un précédent dont le résultat vaut encore). Passée au contrat de la tâche (`score_path`) —
    # un moteur qui ne la suit pas la refuse en le disant.
    score = _score_to_follow(gen, catalog_key)
    score_abs = os.path.join(settings.MEDIA_ROOT, score) if score else None

    try:
        _backend(gen, catalog_key).generate(
            model_id=model_id(catalog_key),
            prompt=_routed_prompt(gen, ctx),
            duration=duration,
            output_path=output_abs_path,
            melody_path=melody_abs,
            score_path=score_abs,
            progress_callback=ctx.progress,
            # Preview « pendant » (COMMUN) : publie l'audio produit → onde de la face during.
            # Dormant tant que composer ne déclare pas la capacité during_preview.
            on_audio=lambda arr, sr: emit_streaming_peaks(ctx.app_id, gen.id, arr, sr),
        )
    except Exception:
        ctx.reset_progress()
        raise
    finally:
        clear_partial(ctx.app_id, gen.id)   # la face SORTIE prend le relais (ou rien, à l'échec)

    output_rel = f'{output_rel_dir}/{output_filename}'
    # Output-format conversion (Phase 3 élargie)
    wanted = (gen.output_format or 'original').lower()
    if wanted not in ('', 'original', 'wav'):
        try:
            from wama.converter.utils.inline_convert import apply_inline_conversion
            converted = apply_inline_conversion(output_abs_path, wanted,
                                                gen.output_quality or 'balanced')
            output_rel = os.path.relpath(converted, settings.MEDIA_ROOT).replace('\\', '/')
        except Exception as exc:
            ctx.console(f"[Composer] conversion format échouée: {exc}", level='warning')

    return {
        'fields': {'audio_output': output_rel},
        'output_ref': output_rel,
        # Génération audio → temps ∝ durée produite (clé par modèle).
        'eta': (catalog_key, float(duration or 0), 'audio_sec'),
        'label': output_filename,
        'models': [catalog_key],
    }


def _score_to_follow(gen, catalog_key) -> str:
    """Chemin (relatif à MEDIA_ROOT) de la partition que le rendu suit, '' s'il n'y en a pas.

    La partition FOURNIE prime. Celle du process `plan` n'est suivie que par un modèle qui
    planifie : une card passée d'un modèle à partition à un modèle qui n'en prend pas garde son
    ancien `planned_score` en base — le lui donner le ferait refuser le rendu."""
    from .function_specs import plans_a_score
    if gen.reference_score:
        return gen.reference_score.name
    planned = getattr(gen.planned_score, 'name', gen.planned_score) or ''
    return planned if planned and plans_a_score(catalog_key) else ''
