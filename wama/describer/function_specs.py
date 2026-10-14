"""Le PIPELINE du describer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, décision n°11 (patron du transcriber et de l'avatarizer) :
un registre de process en code, chaque process un `FunctionSpec binding: app`, le registre exporté
en manifeste `pipeline`. `load_all()` importe ce module ; `workers.py` en lit `PIPELINE`.

Jusqu'au 2026-10-13 le describer passait pour une app « à un seul process » : sa tâche enchaînait
pourtant la transcription, les légendes des images-clés, la rédaction, puis le résumé et la
vérification de cohérence — dans une fonction, sans ligne d'exécution, les deux derniers en échec
AVALÉS (un avertissement en console sous une card « terminée »). Décision de Fabien : « toutes les
applications doivent fonctionner en pipeline ». CINQ process, selon la nature de l'entrée :
  • `transcribe` — l'audio, ou la piste son d'une vidéo → le texte parlé. Audio et vidéo seulement.
    Modèle : `asr_model` (le domaine de transcription du transcriber ; « auto » = Whisper d'abord).
  • `frames`     — la vidéo → les légendes de ses images-clés. Vidéo seulement. Modèle :
    `vision_model` (« auto » = BLIP).
  • `describe`   — l'entrée et ce que les amonts ont rendu → la description, au style demandé.
    Toute card. Modèle : `vision_model` pour une image (« auto » = la cascade Ollama vision puis
    BLIP), `llm_model` pour le reste (« auto » = le tier du style, `get_describer_model`).
  • `summarize`  — un résumé (LLM), du TYPE de la card (`summary_type`) : structuré, depuis la
    description ; ou compte-rendu de réunion, depuis la parole entière ou le texte du document.
    OPTIONNEL, interrupteur `generate_summary`. (Jusqu'au 2026-10-13 le compte-rendu était un
    STYLE de description, rédigé par chaque backend à la place de la description : il est un type
    de résumé, comme au transcriber — migration 0016.)
  • `coherence`  — la description → score, remarques, version proposée (LLM). OPTIONNEL,
    interrupteur `verify_coherence`.

Ce que la séparation apporte : changer le style ou le modèle de langage ne réécoute plus l'audio
ni ne relégende la vidéo ; un résumé ou une cohérence en échec se VOIT sur la card et se rejoue
seul (▶ de la bande) ; chaque process dit le modèle qu'il a employé.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline
from wama.common.services.process_runs import OPTIONAL

_APP = 'describer'
_IMPL = 'describer.workers:describe_content'
_SELF = 'describer.function_specs'

#: Natures qui ont une parole à transcrire.
HEARD = ('audio', 'video')


def nature_of(d) -> str:
    """La nature de l'entrée de la card (image, video, audio, document — les valeurs historiques
    normalisées à la lecture) ; 'auto' tant qu'elle n'est pas détectée."""
    from .utils.content_analyzer import normalize_detected_type
    return normalize_detected_type(getattr(d, 'detected_type', '') or getattr(d, 'content_type', ''))


def _hears(d, model_key=None) -> bool:
    return nature_of(d) in HEARD


def _has_frames(d, model_key=None) -> bool:
    return nature_of(d) == 'video'


def describe_model(d) -> str:
    """Le modèle que la card demande pour sa DESCRIPTION — celui de vision pour une image, de
    langage sinon. « auto » compris : les process se montrent AVANT le premier lancement."""
    field = 'vision_model' if nature_of(d) == 'image' else 'llm_model'
    return getattr(d, field, '') or 'auto'


# ── Résultats LISIBLES des process (`ProcessSpec.result`) — ce que l'aperçu commun montre en face
# de chacun. Un optionnel DÉSACTIVÉ ne montre rien : il ne pèse plus sur la card (règle 4.4).

def transcript_text(d):
    return (getattr(d, 'transcript', '') or '').strip() or None


def frames_text(d):
    lines = [f"[{c.get('time', 0)} s] {c.get('description', '')}".strip()
             for c in (getattr(d, 'frame_captions', None) or []) if isinstance(c, dict)]
    return '\n'.join(lines) or None


def description_text(d):
    return (getattr(d, 'result_text', '') or '').strip() or None


def summary_text(d):
    if not getattr(d, 'generate_summary', False):
        return None
    return (getattr(d, 'summary', '') or '').strip() or None


def coherence_report(d):
    """Le rapport de la brique commune, en regard de la DESCRIPTION qu'elle a vérifiée."""
    if not getattr(d, 'verify_coherence', False):
        return None
    from wama.common.utils.llm_utils import build_coherence_report
    return build_coherence_report(getattr(d, 'coherence_score', None), d.coherence_notes,
                                  d.coherence_suggestion, d.result_text)


register(FunctionSpec(
    key='describer.transcribe', name='Describer — transcrire la parole',
    description="Transcrit la parole d'un audio, ou de la piste son d'une vidéo, avec le modèle de "
                "transcription de la card ou le tirage automatique (Whisper d'abord).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'speech', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', optional=True, group='travail',
                     description="L'audio à transcrire."),
            PortSpec('work_video', 'video', optional=True, group='travail',
                     description="La vidéo dont la piste son est transcrite.")],
    outputs=[PortSpec('transcript', 'document', description="Le texte parlé.")]))

register(FunctionSpec(
    key='describer.frames', name='Describer — légender les images-clés',
    description="Extrait les images-clés d'une vidéo (une toutes les 10 s, 18 au plus) et légende "
                "chacune avec le modèle de vision de la card (BLIP en automatique).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['video', 'vision', 'gpu'],
    inputs=[PortSpec('work_video', 'video', description="La vidéo à parcourir.")],
    outputs=[PortSpec('frames', 'events', description="Les légendes, datées, des images-clés.")]))

register(FunctionSpec(
    key='describer.describe', name='Describer — décrire',
    description="Rédige la description de l'entrée au style et dans la langue de la card : une "
                "image par le modèle de vision, un document, un audio ou une vidéo par le modèle "
                "de langage, à partir de ce que la transcription et les légendes ont rendu.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'vision', 'llm'],
    inputs=[PortSpec('transcript', 'document', optional=True,
                     description="Le texte parlé (audio, vidéo)."),
            PortSpec('frames', 'events', optional=True,
                     description="Les légendes des images-clés (vidéo)."),
            PortSpec('work_image', 'image', optional=True, group='travail',
                     description="L'image à décrire."),
            PortSpec('work_document', 'document', optional=True, group='travail',
                     description="Le document à décrire.")],
    outputs=[PortSpec('description', 'document', description="La description.")]))

register(FunctionSpec(
    key='describer.summarize', name='Describer — résumer',
    description="Résume la card (LLM), selon son type de résumé : un résumé structuré de la "
                "description, ou un compte-rendu de réunion de la parole entière (ou du texte du "
                "document).",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'llm'],
    inputs=[PortSpec('description', 'document', description="La description à résumer."),
            PortSpec('transcript', 'document', optional=True,
                     description="La parole entière, source d'un compte-rendu de réunion.")],
    outputs=[PortSpec('summary', 'document', description="Le résumé ou le compte-rendu.")]))

register(FunctionSpec(
    key='describer.coherence', name='Describer — vérifier la cohérence',
    description="Note la cohérence de la description, relève ses anomalies et propose une "
                "version corrigée (LLM).",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'llm'],
    inputs=[PortSpec('description', 'document', description="La description à vérifier.")],
    outputs=[PortSpec('report', 'document', description="Score, remarques et version proposée.")]))


#: `watched` : les champs HORS schéma — le fichier d'entrée. Les RÉGLAGES déclarent eux-mêmes ce
#: qu'ils périment (`Param.stales`, params.py) ; `PIPELINE.watched_of(spec)` réunit les deux.
#: `gpu` : tous — la description, le résumé et la cohérence passent par un modèle de langage
#: (Ollama hôte, sur la carte), que la file GPU sérialise (`ProcessSpec.gpu`).
PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('transcribe', label='Transcription', watched=('input_file',),
                applies=_hears, gpu=True, share=4, eta='describer.workers:transcribe_eta',
                result=f'{_SELF}:transcript_text'),
    ProcessSpec('frames', label='Images-clés', watched=('input_file',),
                applies=_has_frames, gpu=True, share=3, eta='describer.workers:frames_eta',
                result=f'{_SELF}:frames_text'),
    ProcessSpec('describe', label='Description', depends_on=('transcribe', 'frames'),
                watched=('input_file',), gpu=True, share=3, eta='describer.workers:describe_eta',
                result=f'{_SELF}:description_text'),
    ProcessSpec('summarize', label='Résumé', depends_on=('describe',), degree=OPTIONAL,
                toggle='generate_summary', gpu=True, share=1,
                eta='describer.workers:summarize_eta', result=f'{_SELF}:summary_text',
                result_format='markdown'),
    ProcessSpec('coherence', label='Cohérence', depends_on=('describe',), degree=OPTIONAL,
                toggle='verify_coherence', gpu=True, share=1, eta='describer.workers:coherence_eta',
                result=f'{_SELF}:coherence_report', result_format='coherence'),
), label='Describer — transcription, images-clés, description, résumé, cohérence',
   source_ref='describer.function_specs:PIPELINE',
   model_of=describe_model)
