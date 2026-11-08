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

from wama.common.utils.param_schema import sampling_options

from .models import ComposerGeneration

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def compose_task(self, generation_id: int, process: str | None = None):
    """Generate music or SFX for a ComposerGeneration instance.

    `process` (P5, ▶ par process) : lancement BORNÉ à ce process — lui, précédé des seuls amonts
    périmés (`AppPipeline.steps_to_run(only=)`) ; son aval se périmera de lui-même. ⚠ Argument
    de tâche NOUVEAU : les workers doivent être relancés pour le connaître."""
    from wama.common.services.output_process import forget_lost_generation
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    # La sortie repart du fichier que le rendu a laissé : s'il n'est plus là, le rendu rejoue.
    known = ComposerGeneration.objects.filter(pk=generation_id).first()
    if known is not None:
        forget_lost_generation(known, 'audio_output', 'render')
    try:
        run_item_task(self, app_id='composer', model=ComposerGeneration, item_id=generation_id,
                      pipeline=PIPELINE,
                      processes={'extract_score': _extract_score, 'extract_lyrics': _extract_lyrics,
                                 'write_lyrics': _write_lyrics,
                                 'plan': _plan, 'render': _render, 'output': _output, 'parts': _parts,
                                 'rendered_parts': _rendered_parts,
                                 'rendered_lyrics': _rendered_lyrics},
                      model_key=_model_key, notify_label='Composer',
                      only=process)
    finally:
        _release_backend(generation_id)


# ── La carte graphique : ATTENDRE sa place, puis la RENDRE ───────────────────────────────────
# Les deux manques que la 1ʳᵉ génération YuE2 réelle a montrés (2026-10-02, élément #281) :
#   • le composer ne déclarait AUCUN besoin au squelette : parti sur une carte pleine (modèles de
#     transcription résidents dans le même worker), il a échoué faute de mémoire au lieu
#     d'attendre (`AWAITING_RESOURCES`, ou la libération accordée par l'utilisateur). Depuis le
#     2026-10-14 le squelette tire ce besoin du modèle de CE lancement (`_model_key`), avant
#     chaque process GPU — la copie `_vram_needed` est retirée (`REMOVAL_LEDGER R129`) ;
#   • le moteur n'était jamais RELÂCHÉ : après l'échec, ses poids sont restés dans le worker —
#     avec le plafond mémoire que YuE2 pose au process — et la tâche SUIVANTE (une transcription
#     d'une autre file) a manqué de mémoire à son tour.

def composer_eta_key_size(gen, model: str = None, duration=None) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA d'une génération audio — temps ∝ durée produite, clé par
    modèle (clé de catalogue). UN lieu, partagé par la glu (modèle TIRÉ, durée réelle) et la vue
    de progression (le réglage : « auto » y est sa propre famille, l'a-priori du catalogue prend
    le relais tant qu'elle n'a rien appris) — ROUTE §11 #37."""
    if model is None:
        from .utils.model_choice import normalize
        model = normalize(gen.model)
    return model, float((gen.duration if duration is None else duration) or 0), 'audio_sec'


def render_eta(gen):
    """ETA déclarée du process `render` (`ProcessSpec.eta`) : le triplet que la glu apprend,
    modèle réputé NON chargé, et l'a priori du catalogue de l'app (`model_config.estimate_seconds`
    : durée × `gen_factor` + surcoût) tant que rien n'est appris."""
    from wama.common.utils.model_keys import model_id
    from .utils.model_config import estimate_seconds
    key, size, unit = composer_eta_key_size(gen)
    return key, size, unit, False, estimate_seconds(model_id(key), size)


def plan_eta_key_size(gen, model: str = None) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA du process `plan` : la partition écrite par le moteur du
    modèle, ∝ durée demandée — clé du modèle suffixée du process (`<clé>:plan`)."""
    key, size, unit = composer_eta_key_size(gen, model=model)
    return f'{key}:plan', size, unit


def plan_eta(gen):
    """ETA déclarée du process `plan` : APPRISE seulement (a priori nul) — une clé de PROCESS n'a
    pas d'a priori de domaine, l'estimateur n'en tient que pour des modèles (règle des passes du
    cam_analyzer, `pass_tracking.row_eta_seconds`)."""
    return (*plan_eta_key_size(gen), False, 0.0)


def extract_score_eta_key_size(gen) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA du process `extract_score`, PAR ÉLÉMENT : la durée de l'audio
    du cover n'est pas sur la card, et la sonder (ffprobe) à chaque relevé de progression coûterait
    plus que l'estimation ne rapporte. La relance d'une même card lit sa dernière durée."""
    return 'composer:extract_score', 1.0, 'item'


def extract_score_eta(gen):
    """ETA déclarée du process `extract_score` : apprise seulement (clé de process, cf. `plan_eta`)."""
    return (*extract_score_eta_key_size(gen), False, 0.0)


def parts_eta_key_size(gen) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA du process `parts` : ∝ durée du morceau rendu (mesuré le
    2026-10-16, MuScriptor large : 99 s pour 210 s d'audio) — la durée DEMANDÉE de la card en
    tient lieu, le fichier n'étant pas sondé à chaque relevé de progression."""
    return 'composer:parts', float(gen.duration or 0), 'audio_sec'


def parts_eta(gen):
    """ETA déclarée du process `parts` : apprise seulement (clé de process, cf. `plan_eta`)."""
    return (*parts_eta_key_size(gen), False, 0.0)


def lyrics_eta_key_size(gen) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA des process qui écoutent les paroles : ∝ durée du morceau — la
    durée DEMANDÉE de la card en tient lieu (la règle de `parts_eta_key_size`)."""
    return 'composer:lyrics', float(gen.duration or 0), 'audio_sec'


def lyrics_eta(gen):
    """ETA déclarée des process de paroles : apprise seulement (clé de process, cf. `plan_eta`)."""
    return (*lyrics_eta_key_size(gen), False, 0.0)


#: Moteurs ouverts par les lancements EN COURS dans ce process : {id de génération: instance}.
#: Tenu ici, et non sur le seul élément, pour que la tâche puisse le rendre quoi qu'il arrive.
_OPEN_BACKENDS: dict = {}


def _release_backend(generation_id) -> None:
    """Rend le moteur du lancement (succès, échec, arrêt à la durée max) : `unload()` du contrat
    commun. Ne lève jamais — mais un moteur qui ne se décharge pas se DIT au journal."""
    backend = _OPEN_BACKENDS.pop(generation_id, None)
    if backend is None:
        return
    try:
        backend.unload()
    except Exception:
        logger.warning("[composer] moteur de la génération #%s non déchargé", generation_id,
                       exc_info=True)


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
    lancement : la partition et le rendu lisent la même consigne.

    ⚠ Le modèle passé au pipeline est celui de CE LANCEMENT (`_model_key` : le choix, ou le
    tirage d'un « auto ») — 2026-10-04. Le pipeline lisait le champ `model` de la card : sous
    « auto », `auto:text-to-music` ne désigne aucun modèle, donc ni ses langues (traduction par
    défaut en anglais) ni son CONTRAT de prompt (celui de YuE2 : style + paroles balisées).

    La route de l'imager (2026-10-04) : `effective_prompt` — l'enrichi de l'ingestion
    (`prompt_processed`, éditable dans la modale) prime sur le texte tapé ; déjà enrichi, il n'est
    plus que TRADUIT au besoin (pas de seconde passe LLM). Les mots-clés conservés servent de
    glossaire."""
    if getattr(gen, '_routed_prompt', None) is None:
        from wama.common.utils.app_metadata import effective_prompt, process_prompt_for
        from .utils.vocals import prepare_prompt
        already = bool((getattr(gen, 'prompt_processed', '') or '').strip())
        # La VOIX (2026-10-04) avant la pipeline : paroles retirées (instrumental, modèle qui ne
        # chante pas) ou jointes à la description — la pipeline traite ensuite la description et
        # garde les paroles telles quelles. Les paroles ÉCRITES ne naissent plus ici (2026-11-08) :
        # c'est l'étape `write_lyrics`, avant la partition composée.
        model_key = _model_key(gen)
        text = prepare_prompt(getattr(gen, 'vocals', None), effective_prompt(gen, 'prompt'),
                              model_key, stored_lyrics=getattr(gen, 'lyrics', ''),
                              user=gen.user, console=ctx.console)
        gen._routed_prompt = process_prompt_for(
            ctx.app_id, 'prompt', text,
            instance=gen, user=gen.user, console=ctx.console, model_id=_model_key(gen),
            enrich=False if already else None,
            glossary=list(getattr(gen, 'prompt_keywords', None) or []) or None)
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
        gen._backend = _OPEN_BACKENDS[gen.pk] = backend_class()
    return gen._backend


# ── Glu ──────────────────────────────────────────────────────────────────────────────────────

def _extract_score(gen, ctx):
    """GLU du process `extract_score` (2026-10-03) : l'audio du morceau à reprendre → sa partition
    COMPLÈTE — mélodies et accords, pour être lue et éditée sur la surface « Éditer la partition »
    (décision de Fabien, 2026-10-16 ; jusque-là mélodie seule) —, rangée comme une sortie de la
    card (`extracted_score`). Le rendu n'en reçoit que la mélodie (`_render`). Une notation
    complète impossible (le mode complet de SheetSage2 peut en rendre aucune) retombe sur la
    mélodie seule, en le disant.

    Le modèle n'est PAS celui de la card : c'est celui de la tâche `audio-to-score`, tiré par le
    sélecteur commun. Son backend est propre à ce process et DÉCHARGÉ aussitôt — la carte
    graphique revient entière au rendu (YuE2), qui suit. La ligne d'exécution porte ce modèle
    (`models`)."""
    import tempfile

    from django.conf import settings
    from wama.common.backends.manager import backend_for_key
    from wama.common.utils.model_keys import model_id
    from .utils.model_choice import score_extractor

    extractor_key = score_extractor()
    if not extractor_key:
        raise RuntimeError("Aucun modèle d'extraction de partition n'est installé "
                           "(tâche « audio-to-score ») — l'audio du cover ne peut pas être repris.")
    if not gen.melody_reference:
        raise RuntimeError("Aucun audio à reprendre : le fichier du cover est absent.")
    ctx.ensure_model(extractor_key)        # absent : la route l'installe, la tâche attend
    backend_class = backend_for_key(extractor_key)
    if backend_class is None:
        raise RuntimeError(f"« {extractor_key} » : aucun backend résolu depuis le catalogue.")
    audio_abs = os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name)
    ctx.console(f"[Composer] Partition réduite de l'audio : {extractor_key} — "
                f"{os.path.basename(gen.melody_reference.name)}")
    backend = backend_class()
    try:
        with tempfile.TemporaryDirectory() as annexes:   # MIDI, temps : non gardés
            def extract(melody_only):
                return backend.extract_score(model_id=model_id(extractor_key), audio_path=audio_abs,
                                             output_dir=annexes, melody_only=melody_only,
                                             progress_callback=ctx.progress)
            try:
                text = extract(False)
            except RuntimeError as error:
                ctx.console(f"[Composer] Accords impossibles ({error}) — partition réduite à la "
                            "mélodie seule")
                text = extract(True)
    except Exception:
        ctx.reset_progress()
        raise
    finally:
        try:
            backend.unload()
        except Exception:
            logger.warning("[composer] modèle d'extraction de #%s non déchargé", gen.pk,
                           exc_info=True)
    score_rel, abs_path = ctx.output_place('.abc', nature='score', model=model_id(extractor_key))
    name = os.path.basename(score_rel)
    with open(abs_path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return {
        'fields': {'extracted_score': score_rel},
        'output_ref': score_rel,
        'label': name,
        'console_success': f"✓ Partition réduite : {name}",
        'models': [extractor_key],
        'eta': extract_score_eta_key_size(gen),
    }


def _parts(gen, ctx):
    """GLU du process `parts` : l'audio de l'ENTRÉE — le morceau à reprendre (cover) — → sa
    partition complète, à côté de la partition réduite qu'en tire `extract_score` (sur l'entrée
    depuis le 2026-10-26, décision de Fabien : les deux décrivent le même morceau)."""
    from django.conf import settings
    if not gen.melody_reference:
        raise RuntimeError("Aucun audio à reprendre : la partition complète se lit sur l'entrée.")
    audio_abs = os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name)
    return _full_score(gen, ctx, audio_abs, field='parts_score', nature='score',
                       label='Partition complète')


def _rendered_parts(gen, ctx):
    """GLU du process `rendered_parts` (2026-10-26) : le morceau PRODUIT → sa partition complète,
    pour la comparer à celle de l'entrée. Lit l'audio du RENDU — l'original que la sortie garde
    quand elle l'a converti, sinon le rendu lui-même : le même, que la sortie soit passée ou non."""
    from wama.common.services.output_process import output_sources
    sources = [p for p in output_sources(gen, 'audio_output') if os.path.isfile(p)]
    if not sources:
        raise RuntimeError("Aucun morceau rendu : la partition de sortie se lit sur le rendu.")
    return _full_score(gen, ctx, sources[0], field='rendered_parts_score', nature='render_score',
                       label='Partition de sortie')


def _full_score(gen, ctx, audio_abs: str, *, field: str, nature: str, label: str):
    """Un audio → sa partition complète, une partie par instrument, rangée comme une sortie de la
    card (`field`) — le corps commun des deux process de partition complète (2026-10-16).

    Le modèle est celui que la card désigne (`parts_model`, 2026-10-19), ou sous « auto » celui de
    la tâche `audio-to-midi` tiré par le sélecteur commun ; absent, la ROUTE l'installe et la tâche
    attend (`ctx.ensure_model`) ; DÉCHARGÉ aussitôt (la règle d'`extract_score`). Le moteur rend un
    MIDI ; la notation est la brique commune `midi_score`, qui place les notes sur les temps JOUÉS
    du morceau (`audio_rhythm`) quand le moteur n'a pas trouvé de tempo constant."""
    from wama.common.backends.manager import backend_for_key
    from wama.common.utils.audio_rhythm import beat_grid
    from wama.common.utils.midi_score import midi_to_abc
    from wama.common.utils.model_keys import model_id
    from .utils.model_choice import parts_extractor

    extractor_key = parts_extractor(gen)
    if not extractor_key:
        raise RuntimeError("Aucun modèle de partition complète n'est installé (tâche « audio-to-midi »).")
    ctx.ensure_model(extractor_key)        # absent : la route l'installe, la tâche attend
    backend_class = backend_for_key(extractor_key)
    if backend_class is None:
        raise RuntimeError(f"« {extractor_key} » : aucun backend résolu depuis le catalogue.")
    ctx.console(f"[Composer] {label} : {extractor_key} — {os.path.basename(audio_abs)}")
    backend = backend_class()
    try:
        midi = backend.extract_midi(model_id=model_id(extractor_key), audio_path=audio_abs,
                                    progress_callback=ctx.progress)
    except Exception:
        ctx.reset_progress()
        raise
    finally:
        try:
            backend.unload()
        except Exception:
            logger.warning("[composer] modèle de partition complète de #%s non déchargé", gen.pk,
                           exc_info=True)
    grid = beat_grid(audio_abs) or {}
    text = midi_to_abc(midi, title=f'#{gen.pk}', beat_times=grid.get('beats'))
    score_rel, abs_path = ctx.output_place('.abc', nature=nature, model=model_id(extractor_key))
    name = os.path.basename(score_rel)
    with open(abs_path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return {
        'fields': {field: score_rel},
        'output_ref': score_rel,
        'label': name,
        'console_success': f"✓ {label} : {name}",
        'models': [extractor_key],
        'eta': parts_eta_key_size(gen),
    }


def _extract_lyrics(gen, ctx):
    """GLU du process `extract_lyrics` (2026-11-03) : l'audio du morceau à reprendre → ses paroles
    horodatées (`input_lyrics_timed`, 2026-11-08), et le champ « Paroles » s'il est vide. YuE2 ne
    reçoit ni cet audio ni son texte : « transcribe and correct the words; align section tags and
    lyric order with the score » (`vendor/yue/docs/covers.md`)."""
    from django.conf import settings
    if not gen.melody_reference:
        raise RuntimeError("Aucun audio à reprendre : les paroles se lisent sur l'entrée.")
    return _heard_lyrics(gen, ctx, os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name),
                         score=_name(gen.extracted_score), field='input_lyrics_timed',
                         source_name=gen.melody_reference.name)


def _rendered_lyrics(gen, ctx):
    """GLU du process `rendered_lyrics` (2026-11-03 ; « Paroles chantées » depuis le 2026-11-08) :
    ce que le modèle a CHANTÉ → ses paroles horodatées (`rendered_lyrics_timed`), que la partition
    jouée montre sous ses notes, et le champ « Paroles » s'il est resté vide (un texte improvisé, à
    relire et rejouer). Lit l'audio du RENDU, comme la partition jouée. Le rendu n'est pas périmé
    par ce qu'il a lui-même chanté (`settle_setting`)."""
    from wama.common.services import process_runs
    from wama.common.services.output_process import output_sources
    from .function_specs import PIPELINE
    sources = [p for p in output_sources(gen, 'audio_output') if os.path.isfile(p)]
    if not sources:
        raise RuntimeError("Aucun morceau rendu : les paroles chantées se lisent sur le rendu.")
    result = _heard_lyrics(gen, ctx, sources[0], score=_score_to_follow(gen, _model_key(gen)),
                           field='rendered_lyrics_timed')
    lyrics = result.get('fields', {}).get('lyrics')
    if lyrics:
        process_runs.safely(process_runs.settle_setting, gen,
                            [s.key for s in PIPELINE.specs if 'lyrics' in PIPELINE.watched_of(s)],
                            'lyrics', lyrics)
    return result


def _write_lyrics(gen, ctx):
    """GLU du process `write_lyrics` (2026-11-08, décision de Fabien) : la consigne → les paroles
    de la chanson, à la LONGUEUR du morceau, dans le champ « Paroles » — la fonction commune
    `write_lyrics_for`, celle du bouton du réglage. Écrites AVANT la partition composée : YuE2 bâtit
    sa structure sur leurs sections. Des paroles arrivées depuis le lancement (écoutées dans le
    morceau repris) ne sont jamais réécrites. Rien d'écrit (LLM indisponible) : l'étape échoue en le
    disant, le morceau restera instrumental."""
    from wama.common.backends.music_generation_base import tagged_lyrics
    from wama.common.utils.app_metadata import effective_prompt, lyrics_language, write_lyrics_for
    from .utils.model_config import clamp_duration
    if str(gen.lyrics or '').strip():
        return {'label': 'Paroles déjà là, gardées'}
    catalog_key = _model_key(gen)
    caption = tagged_lyrics(effective_prompt(gen, 'prompt') or '')[0]
    duration = clamp_duration(gen.duration, catalog_key)
    language = lyrics_language(catalog_key, gen.user)
    ctx.console(f"[Composer] ✍️ Écriture des paroles ({language}, ~{int(duration)} s)…")
    written = write_lyrics_for('composer', 'prompt', caption, language=language, user=gen.user,
                               duration=duration)
    if not written:
        raise RuntimeError("Paroles non écrites (LLM local indisponible) : le morceau sera "
                           "instrumental.")
    return {'fields': {'lyrics': written},
            'label': f"{len(written.split())} mots",
            'console_success': f"✓ Paroles écrites en « {language} », gardées sur la card "
                               f"(Paramètres ⚙ → Paroles) :\n{written}"}


def _score_sections(gen, score: str) -> list:
    """Les sections de la partition `score`, lues par le MOTEUR qui la suit (`score_sections`), [] si
    elle n'en dit rien : les paroles restent alors d'un seul tenant. Jamais une raison d'échouer."""
    from django.conf import settings
    from wama.common.backends.manager import backend_for_key
    reader = getattr(backend_for_key(_model_key(gen)), 'score_sections', None)
    if not score or reader is None:
        return []
    try:
        with open(os.path.join(settings.MEDIA_ROOT, score), encoding='utf-8') as handle:
            return reader(handle.read())
    except (OSError, ValueError) as error:
        logger.info("[composer] sections de %s illisibles : %s", score, error)
        return []


def _heard_lyrics(gen, ctx, audio_abs: str, *, score: str = '', field: str,
                  source_name: str = '') -> dict:
    """Un audio → ses paroles : le corps commun des deux écoutes (entrée, sortie — « le même
    comportement », 2026-11-08). Le modèle est celui que la card désigne (`lyrics_model`) ou le
    tirage ; absent, la ROUTE l'installe et la tâche attend ; DÉCHARGÉ aussitôt (la règle
    d'`extract_score`) : la carte revient au rendu. Pas de filtre de parole : mesuré, il écarte le
    CHANT (0 segment sur une chanson entière), et une section muette de la partition s'en charge.

    Deux sorties : les paroles HORODATÉES AU MOT (`field`, un JSON `{words, language, duration,
    aligner, …}`) par la brique commune du transcriber (`acoustic_alignment.timed_words` : les mots
    du modèle d'écoute, recalés par l'aligneur du catalogue — Qwen3-ASR ne date pas ses mots), que
    la partition pose sous ses notes ; et le champ « Paroles », en sections, s'il est VIDE — une
    correction ne se réécrit jamais. Rien d'entendu n'est pas un échec : c'est dit."""
    import json

    from wama.common.services.acoustic_alignment import timed_words
    from wama.common.utils.media_probe import probe_media
    from wama.common.utils.model_keys import model_id
    from wama.common.utils.whisper_utils import transcribe_audio
    from wama.model_manager.services.memory_manager import MemoryManager
    from .utils.lyrics import fit_to_duration, lyrics_from_segments
    from .utils.model_choice import lyrics_transcriber
    from wama.transcriber.backends.manager import DEFAULT_MODEL_KEY

    key = ctx.ensure_model(lyrics_transcriber(gen) or DEFAULT_MODEL_KEY)
    duration = float(probe_media(audio_abs).get('duration') or 0)
    ctx.console(f"[Composer] Écoute des paroles : {key} — {os.path.basename(audio_abs)}")
    try:
        heard = transcribe_audio(audio_abs, model_key=key, user=gen.user, duration=duration,
                                 vad_filter=False)
    except Exception:
        ctx.reset_progress()
        raise
    finally:
        if not MemoryManager.unload_model(key):
            logger.info("[composer] modèle d'écoute de #%s : rien à décharger (%s)", gen.pk, key)
    lyrics = lyrics_from_segments(heard.segments, fit_to_duration(_score_sections(gen, score), duration))
    out = {'models': [key], 'eta': lyrics_eta_key_size(gen), 'fields': {}}
    if not lyrics:
        ctx.console("[Composer] Aucune parole reconnue.")
        return out
    timed = timed_words(heard.segments, audio_abs, heard.language or '', audio_end=duration or None,
                        ctx=ctx)
    if timed['aligner']:
        out['models'].append(timed['aligner'])
    rel, abs_path = ctx.output_place('.json', nature='lyrics', model=model_id(key),
                                     source_name=source_name)
    with open(abs_path, 'w', encoding='utf-8') as handle:
        json.dump({'words': timed['words'], 'language': heard.language or '', 'duration': duration,
                   'aligner': timed['aligner'], 'alignment': timed['report'],
                   'note': timed['reason']}, handle, ensure_ascii=False)
    out['fields'][field] = rel
    out['output_ref'] = rel
    out['label'] = f"{len(timed['words'])} mots" + ('' if timed['aligner'] else ' (heures estimées)')
    said = (f"[Composer] ✓ Paroles entendues ({heard.language or 'langue inconnue'}, "
            f"{len(timed['words'])} mots horodatés"
            + (f", recalés par {timed['aligner']}" if timed['aligner'] else f" — {timed['reason']}")
            + ")")
    if _lyrics_field_open(gen):
        out['fields']['lyrics'] = lyrics
        said += f", posées dans « Paroles », à relire dans ⚙ :\n{lyrics}"
    ctx.console(said)
    return out


def _lyrics_field_open(gen) -> bool:
    """Le champ « Paroles » attend-il des paroles ENTENDUES ? Vide, sans paroles balisées dans la
    consigne (elles priment : on les doublerait), et la voix n'est pas « Instrumental » (elles ne
    seraient pas chantées). Les paroles horodatées, elles, se rangent toujours — pour la partition."""
    from wama.common.backends.music_generation_base import tagged_lyrics
    from .utils import vocals
    if str(gen.lyrics or '').strip():
        return False
    if vocals.normalize(getattr(gen, 'vocals', None)) == vocals.INSTRUMENTAL:
        return False
    return not tagged_lyrics(getattr(gen, 'prompt', '') or '')[1]


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
            progress_callback=ctx.progress,
            sampling=sampling_options(gen))   # la graine de la card : la même qu'au rendu
    except Exception:
        ctx.reset_progress()
        raise
    score_rel, abs_path = ctx.output_place('.abc', nature='score', model=model_id(catalog_key))
    name = os.path.basename(score_rel)
    with open(abs_path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    return {
        'fields': {'planned_score': score_rel},
        'output_ref': score_rel,
        'label': name,
        'console_success': f"✓ Partition écrite : {name}",
        'models': [catalog_key],
        'eta': plan_eta_key_size(gen, model=catalog_key),
    }


def _render(gen, ctx):
    """GLU du process `render` : une exception = FAILURE (le squelette pose statut, console et
    notification) ; l'aperçu partiel et la progression sont remis à zéro ICI."""
    from django.conf import settings
    from wama.common.utils.auto_model import is_auto
    from wama.common.utils.model_keys import model_id
    from wama.common.utils.preview_utils import PartialFrames
    from .utils.model_config import clamp_duration

    catalog_key = _model_key(gen)
    auto = is_auto(gen.model)
    _announce_model(gen, ctx, catalog_key)

    # Durée plafonnée par la capacité du modèle FINAL (source unique = clamp_duration : schéma +
    # max_duration du modèle). Seul point où le vrai modèle est connu. Le plafond n'est ÉCRIT
    # dans le réglage que si le modèle a été DÉSIGNÉ : sous « auto », c'est le plafond du modèle
    # tiré cette fois-ci, pas un choix de l'utilisateur — l'écrire figerait la durée du prochain
    # tirage, comme écrire le modèle figeait le tirage lui-même.
    duration = clamp_duration(gen.duration, catalog_key)
    if duration != gen.duration:
        ctx.console(f"[Composer] Durée {gen.duration:g}s → {duration:g}s "
                    f"(max du modèle {catalog_key})")
        if not auto:
            ComposerGeneration.objects.filter(pk=gen.pk).update(duration=duration)
            # En mémoire AUSSI : la ligne d'exécution photographie les réglages tels que la glu
            # les laisse — sans cela le rendu serait périmé par son propre plafonnement.
            gen.duration = duration
    ctx.console(f"[Composer] Démarrage : {catalog_key} — {gen.prompt[:60]}…")

    # Un cover porte le nom de son morceau (la règle commune, famille FICHIER, comme les apps dont
    # l'entrée est un fichier) ; sans fichier de travail, la famille PROMPT.
    source = gen.melody_reference or gen.reference_score
    output_rel, output_abs_path = ctx.output_place('.wav', model=model_id(catalog_key),
                                                   source_name=source.name if source else '')
    output_filename = os.path.basename(output_rel)

    # L'audio du cover n'est donné qu'au modèle qui le prend LUI-MÊME (MusicGen Melody) : un modèle
    # qui le reprend par sa partition (YuE2) le refuserait — il reçoit la partition extraite.
    from .utils.model_choice import consumes_melody
    melody_abs = (os.path.join(settings.MEDIA_ROOT, gen.melody_reference.name)
                  if gen.melody_reference and consumes_melody(catalog_key) else None)
    # Partition à suivre : celle que l'utilisateur FOURNIT (port `reference_score`, 2026-10-01)
    # prime ; sinon celle que le process `plan` a écrite (`planned_score` — à ce lancement, ou à
    # un précédent dont le résultat vaut encore). Passée au contrat de la tâche (`score_path`) —
    # un moteur qui ne la suit pas la refuse en le disant.
    score = _score_to_follow(gen, catalog_key)
    score_abs = os.path.join(settings.MEDIA_ROOT, score) if score else None
    # La partition EXTRAITE porte ses accords (pour la page d'édition) ; le cover n'en joue que la
    # mélodie (`cot="melody"`, chaîne prescrite par le moteur) — une copie jetable sans accords.
    melody_copy = _melody_copy(score_abs) if score and score == _name(gen.extracted_score) else None
    # Preview « pendant » (COMMUN) : l'audio déjà produit, à l'écoute et en onde, tant que le
    # moteur calcule — à la cadence de la brique, pas à celle du moteur.
    partial = PartialFrames(ctx.app_id, gen.id, os.path.join(os.path.dirname(output_abs_path), 'partials'),
                            every=3.0)

    try:
        _backend(gen, catalog_key).generate(
            model_id=model_id(catalog_key),
            prompt=_routed_prompt(gen, ctx),
            duration=duration,
            output_path=output_abs_path,
            melody_path=melody_abs,
            score_path=melody_copy or score_abs,
            progress_callback=ctx.progress,
            on_audio=partial.audio_sink(),
            # Température, graine et top_p de la card, sinon ceux du moteur (2026-10-22).
            sampling=sampling_options(gen),
        )
    except Exception:
        ctx.reset_progress()
        raise
    finally:
        partial.close()   # la face SORTIE prend le relais (ou rien, à l'échec)
        if melody_copy:
            try:
                os.remove(melody_copy)
            except OSError:
                pass

    # Le format et la qualité de sortie sont le process suivant, `output` (brique commune) : ici
    # la glu rend le WAV du modèle. Les rendus et l'original gardé de la fois d'avant partent.
    from wama.common.services.output_process import drop_previous_outputs, generated
    drop_previous_outputs(gen, 'audio_output', keep=[output_abs_path])
    return generated(
        [output_abs_path],
        fields={'audio_output': output_rel},
        eta=composer_eta_key_size(gen, model=catalog_key, duration=duration),
        label=output_filename,
        models=[catalog_key])


def _output(gen, ctx):
    """GLU du process `output` : format et qualité de sortie, par la glu COMMUNE
    (`output_process.output_step`) — le WAV du rendu est gardé tant que la sortie le transforme."""
    from wama.common.services.output_process import output_step
    return output_step('audio_output', domain='audio', app_id='composer')(gen, ctx)


def _name(field) -> str:
    return getattr(field, 'name', field) or ''


def _melody_copy(score_abs: str):
    """Une copie JETABLE de la partition sans ses accords (`yue2_3b_backend.melody_only_abc`),
    None si elle n'en porte pas — le rendu lit alors la partition elle-même."""
    import tempfile

    from wama.common.backends.yue2_3b_backend import melody_only_abc
    with open(score_abs, encoding='utf-8') as source:
        text = source.read()
    melody = melody_only_abc(text)
    if melody == text:
        return None
    handle, path = tempfile.mkstemp(suffix='.abc', prefix='melody_')
    with os.fdopen(handle, 'w', encoding='utf-8') as out:
        out.write(melody)
    return path


def _score_to_follow(gen, catalog_key) -> str:
    """Chemin (relatif à MEDIA_ROOT) de la partition que le rendu suit, '' s'il n'y en a pas.

    La partition FOURNIE prime ; puis celle EXTRAITE de l'audio du cover, tant que le process
    `extract_score` vaut pour la card (audio retiré, modèle changé : l'ancienne n'est plus suivie) ;
    puis celle du process `plan`, suivie seulement par un modèle qui planifie : une card passée
    d'un modèle à partition à un modèle qui n'en prend pas garde son ancien `planned_score` en
    base — le lui donner le ferait refuser le rendu. La partition d'un amont se lit par le geste
    COMMUN (`AppPipeline.upstream_output` : la sortie de type `score` de l'amont qui a lieu —
    2026-10-21)."""
    from .function_specs import PIPELINE
    if gen.reference_score:
        return gen.reference_score.name
    return PIPELINE.upstream_output(gen, 'render', 'score', catalog_key)
