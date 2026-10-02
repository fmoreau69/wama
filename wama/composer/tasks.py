"""
Composer Celery Tasks — Music and SFX generation.

Squelette (gardes, progression, chrono, statuts, ETA, console, notifications, tâche déclarée
au gouverneur, garde-temps, signal et révision) = brique COMMUNE
`common/utils/task_skeleton.run_item_task` (portage 2026-10-02, marche A2 — `ROUTE §10.6` :
une app à UN seul process adopte le squelette sans attendre le moteur commun, sa glu
`process(item, ctx)` reste le contrat d'un process). Ce fichier ne porte plus que la GLU :
tirage du modèle « auto », plafond de durée, nommage et rangement de la sortie, traduction du
prompt, appel du backend résolu par le catalogue, conversion de format.

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
    run_item_task(self, app_id='composer', model=ComposerGeneration, item_id=generation_id,
                  process=_compose, model_key=_model_key, notify_label='Composer')


# ── Tirage « auto » AU LANCEMENT ─────────────────────────────────────────────────────────────
# Résolu UNE fois par lancement et mémorisé sur l'instance : le squelette demande la clé du
# modèle (`model_key` : annonce du téléchargement des poids, durée max réglée par modèle) AVANT
# la glu, qui doit parler du même modèle. L'élément GARDE son « auto » : une relance ré-arbitre
# avec la VRAM du moment et le curseur reste visible. Le modèle retenu vit dans la console,
# l'ETA et le résultat (`models`).
# ⚠ Jusqu'au 2026-10-02 la tâche ÉCRIVAIT le modèle tiré dans le réglage `model` : le choix
# « auto » de l'utilisateur était remplacé à la première génération (relance figée sur ce
# modèle) — le défaut que le contrat du squelette nomme (`fields` : des résultats, jamais un
# réglage).

def _model_key(gen) -> str:
    """Clé de catalogue du modèle de CE lancement : le choix explicite tel quel, sinon le tirage."""
    if not getattr(gen, '_resolved_model', None):
        from wama.common.utils.auto_model import is_auto
        from .utils.auto_model import resolve_auto_model
        from .utils.model_choice import normalize
        gen._resolved_model = normalize(resolve_auto_model(gen) if is_auto(gen.model)
                                        else gen.model)
    return gen._resolved_model


# ── Glu ──────────────────────────────────────────────────────────────────────────────────────

def _compose(gen, ctx):
    """GLU (contrat `task_skeleton`) : une exception = FAILURE (le squelette pose statut,
    console et notification) ; l'aperçu partiel et la progression sont remis à zéro ICI."""
    from django.conf import settings
    from wama.common.backends.manager import backend_for_key
    from wama.common.utils.app_metadata import process_prompt_for
    from wama.common.utils.auto_model import is_auto, quality_intent_of
    from wama.common.utils.media_paths import app_media_dir
    from wama.common.utils.model_keys import model_id
    from wama.common.utils.output_naming import compose_output_name
    from wama.common.utils.preview_utils import clear_partial, emit_streaming_peaks
    from .utils.model_config import clamp_duration

    catalog_key = _model_key(gen)
    auto = is_auto(gen.model)
    if auto:
        ctx.console(f"[Composer] 🧠 Auto → {catalog_key} (capacités + VRAM libre au lancement, "
                    f"curseur qualité {quality_intent_of(gen, ctx.app_id)}/100)")

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

    # Le dossier de sortie vient de la brique (`app_media_dir`) : il décide où le fichier
    # atterrit ET ce que la base retient. Composé à la main (`composer/<uid>/output`) jusqu'au
    # 2026-10-02, il aurait recréé l'ancien arbre à la première génération après la bascule des
    # médias du 2026-09-12 (mesuré : aucune génération depuis — les 5 sorties en base ont été
    # migrées) — et la règle de propriété n'aurait jamais reconnu ce fichier comme celui de l'app.
    output_rel_dir = app_media_dir(ctx.app_id, gen.user_id, 'output')
    output_dir = os.path.join(settings.MEDIA_ROOT, output_rel_dir)
    os.makedirs(output_dir, exist_ok=True)
    # Brique COMMUNE de nommage (2026-08-25). ⚠ Le rendu a CHANGÉ ce jour-là, volontairement
    # (arbitrage Fabien : l'homogénéité prime sur le portage à l'identique) :
    # `{modèle}_{uuid8}.wav` → `audio{id}_{modèle}.wav`. L'uuid était unique mais MUET — il ne
    # rattachait le fichier à aucune card.
    output_filename = compose_output_name(app=ctx.app_id, model=model_id(catalog_key),
                                          item_id=gen.id, ext='.wav')
    output_abs_path = os.path.join(output_dir, output_filename)

    melody_abs = (os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name)
                  if gen.melody_reference else None)
    # Partition de référence (port `reference_score`, 2026-10-01) : passée au contrat de la
    # tâche (`score_path`) — un moteur qui ne la suit pas la refuse en le disant.
    score_abs = (os.path.join(settings.MEDIA_ROOT, gen.reference_score.name)
                 if gen.reference_score else None)

    # PromptPipeline (§16.6) : MusicGen/AudioCraft est entraîné en anglais → un prompt FR est
    # traduit avant génération (métadonnée PROMPT_TARGETS['composer'], KIND generative).
    # Résource-safe : passthrough si déjà EN / modèle multilingue.
    routed_prompt = process_prompt_for(ctx.app_id, 'prompt', gen.prompt,
                                       instance=gen, user=gen.user, console=ctx.console)

    # Le MODÈLE porte son moteur (catalogue, `composition.runtime.engine`) ; le backend s'en
    # DÉRIVE — l'app ne choisit rien et n'importe aucun module par son chemin (ROUTE §10.3).
    # ⚠ Aucun repli « par défaut » : un modèle non résolu arrête le job en le DISANT.
    backend_class = backend_for_key(catalog_key)
    if backend_class is None:
        raise RuntimeError(
            f"Modèle « {gen.model} » : aucun backend résolu depuis le catalogue "
            f"({catalog_key} absent, ou sans moteur déclaré)")
    try:
        backend_class().generate(
            model_id=model_id(catalog_key),
            prompt=routed_prompt,
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
        ctx.progress(0)
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
        # Génération audio → temps ∝ durée produite (clé par modèle).
        'eta': (catalog_key, float(duration or 0), 'audio_sec'),
        'label': output_filename,
        'models': [catalog_key],
    }
