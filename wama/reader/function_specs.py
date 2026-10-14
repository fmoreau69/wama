"""Le PIPELINE du reader — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, décision n°11 (patron du transcriber et du describer) : un
registre de process en code, chaque process un `FunctionSpec binding: app`, le registre exporté en
manifeste `pipeline`. `load_all()` importe ce module ; `tasks.py` en lit `PIPELINE`.

Jusqu'au 2026-10-13 le reader passait pour une app « à un seul process » : sa tâche lisait le
document PUIS le mettait en forme par un LLM, dont l'échec était AVALÉ (le texte brut rendu sous
une card « terminée », sans un mot) ; son analyse LLM vivait dans une tâche à part, que rien dans
l'interface n'appelait. Décision de Fabien : « toutes les applications doivent fonctionner en
pipeline ». TROIS process :
  • `read`    — le document ou l'image → son texte : texte natif d'un PDF numérique, sinon le
    moteur OCR de la card (`backend`, « auto » = le tirage commun). Toute card.
  • `format`  — le texte lu → le même texte en Markdown (LLM). OPTIONNEL, interrupteur
    `format_markdown`, COCHÉ par défaut (il avait toujours lieu) ; le texte natif d'un PDF reste
    tel quel, comme avant.
  • `analyze` — le texte → un résumé, ses points clés et ses actions (LLM). OPTIONNEL,
    interrupteur `generate_analysis`.
Les deux derniers emploient le modèle de langage de la card (`llm_model`, « auto » = leur
comportement d'avant).

Ce que la séparation apporte : changer de modèle de langage ne relit plus le document (olmOCR,
~10 min de chargement) ; une mise en forme en échec se VOIT sur sa ligne, le texte lu reste.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline
from wama.common.services.process_runs import OPTIONAL

_APP = 'reader'
_IMPL = 'reader.tasks:read_document_task'
_SELF = 'reader.function_specs'


def reading_model(item) -> str:
    """Le moteur que la card demande — « auto » compris : les process se montrent AVANT le
    premier lancement."""
    return getattr(item, 'backend', '') or 'auto'


# ── Résultats LISIBLES des process (`ProcessSpec.result`) — ce que l'aperçu commun montre en face
# de chacun. Un optionnel DÉSACTIVÉ ne montre rien : il ne pèse plus sur la card (règle 4.4).

def read_text(item):
    from .tasks import _extract_natural_text
    return (_extract_natural_text(getattr(item, 'raw_result', '') or '') or '').strip() or None


def formatted_text(item):
    if not getattr(item, 'format_markdown', False):
        return None
    return (getattr(item, 'result_text', '') or '').strip() or None


def analysis_text(item):
    if not getattr(item, 'generate_analysis', False):
        return None
    return (getattr(item, 'analysis', '') or '').strip() or None


register(FunctionSpec(
    key='reader.read', name='Reader — lire',
    description="Lit le texte d'un document ou d'une image : texte natif d'un PDF numérique, "
                "sinon le moteur OCR de la card ou le tirage automatique.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['ocr', 'document', 'gpu'],
    inputs=[PortSpec('work_document', 'document', optional=True, group='travail',
                     description="Le document à lire (PDF…)."),
            PortSpec('work_image', 'image', optional=True, group='travail',
                     description="L'image à lire.")],
    outputs=[PortSpec('text', 'document', description="Le texte lu.")]))

register(FunctionSpec(
    key='reader.format', name='Reader — mettre en forme',
    description="Remet le texte lu en Markdown (titres, listes, tableaux) sans rien en retrancher "
                "(LLM) ; le texte natif d'un PDF reste tel quel.",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'llm'],
    inputs=[PortSpec('text', 'document', description="Le texte lu.")],
    outputs=[PortSpec('markdown', 'document', description="Le texte en Markdown.")]))

register(FunctionSpec(
    key='reader.analyze', name='Reader — analyser',
    description="Résume le texte lu, en relève les points clés et les actions (LLM).",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'llm'],
    inputs=[PortSpec('text', 'document', description="Le texte lu, mis en forme s'il l'a été.")],
    outputs=[PortSpec('analysis', 'document', description="Résumé, points clés, actions.")]))


#: `watched` : les champs HORS schéma — le fichier d'entrée. Les RÉGLAGES déclarent eux-mêmes ce
#: qu'ils périment (`Param.stales`, params.py) ; `PIPELINE.watched_of(spec)` réunit les deux.
#: `gpu` : tous — la mise en forme et l'analyse passent par un modèle de langage (Ollama hôte, sur
#: la carte), que la file GPU sérialise (`ProcessSpec.gpu`).
PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('read', label='Lecture', watched=('input_file',), gpu=True, share=8,
                eta='reader.tasks:read_eta', result=f'{_SELF}:read_text'),
    ProcessSpec('format', label='Mise en forme', depends_on=('read',), degree=OPTIONAL,
                toggle='format_markdown', gpu=True, share=1, eta='reader.tasks:format_eta',
                result=f'{_SELF}:formatted_text'),
    ProcessSpec('analyze', label='Analyse', depends_on=('read', 'format'), degree=OPTIONAL,
                toggle='generate_analysis', gpu=True, share=1, eta='reader.tasks:analyze_eta',
                result=f'{_SELF}:analysis_text'),
), label='Reader — lecture, mise en forme, analyse',
   source_ref='reader.function_specs:PIPELINE',
   model_of=reading_model)
