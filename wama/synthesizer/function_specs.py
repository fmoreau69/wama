"""Le PIPELINE du synthesizer — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, marche P6 (2026-10-03) : décision n°11 — un registre de
process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en manifeste
`pipeline`. `load_all()` importe ce module ; `workers.py` en lit `PIPELINE`.

DEUX process :
  • `generate` — le texte → la voix, en WAV : extraction du texte, moteur TTS (désigné ou tiré),
    voix de référence, vitesse et hauteur. C'est le process coûteux (service TTS).
  • `output`   — le format et la qualité de sortie (process COMMUN, `output_process`) : le WAV
    est gardé tant que la sortie le transforme.

Ce que la séparation apporte : changer le format ou la qualité ne re-synthétise plus.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.output_process import output_spec
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'synthesizer'
_IMPL = 'synthesizer.workers:synthesize_voice'

register(FunctionSpec(
    key='synthesizer.generate', name='Synthesizer — dire le texte',
    description="Synthétise le texte de la card avec le moteur TTS désigné ou tiré, la voix et "
                "la langue choisies, la vitesse et la hauteur demandées. Rend un WAV.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'speech', 'tts'],
    inputs=[PortSpec('work_text', 'document', description="Le texte à dire."),
            PortSpec('reference_voice', 'audio', optional=True,
                     description="La voix de référence (clonage).")],
    outputs=[PortSpec('native', 'audio', description="La parole synthétisée (WAV).")]))

register(FunctionSpec(
    key='synthesizer.output', name='Synthesizer — réglages de sortie',
    description="Applique le format et la qualité de sortie de la card au WAV synthétisé. Garde "
                "ce WAV tant que la sortie le transforme, pour se rejouer sans re-synthétiser.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'format'],
    inputs=[PortSpec('native', 'audio', description="Le WAV synthétisé.")],
    outputs=[PortSpec('audio', 'audio', description="La parole au format demandé.")]))


#: Ce que la SYNTHÈSE surveille HORS schéma : le fichier texte, la voix de référence jointe, le
#: multi-locuteur et la scène. Les RÉGLAGES (modèle, curseur, voix, langue, vitesse, hauteur)
#: déclarent eux-mêmes ce qu'ils périment (`Param.stales`, params.py, 2026-10-05) ;
#: `PIPELINE.watched_of(spec)` réunit les deux. Le texte extrait (`text_content`) n'y est pas : la
#: glu l'ÉCRIT, depuis `text_file` qui, lui, y est.
GENERATE_WATCHED = ('text_file', 'voice_reference', 'multi_speaker', 'scene_description')

PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('generate', label='Synthèse', watched=GENERATE_WATCHED, gpu=True, share=9,
                eta='synthesizer.workers:synthesizer_eta_key_size'),
    output_spec(depends_on=('generate',)),
), label='Synthesizer — synthèse puis réglages de sortie',
   source_ref='synthesizer.function_specs:PIPELINE',
   model_of=lambda synthesis: synthesis.tts_model or 'auto')
