"""Le PIPELINE du converter — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6`, décision n°11 (patron du transcriber, du describer et du
reader) : un registre de process en code, chaque process un `FunctionSpec binding: app`, le
registre exporté en manifeste `pipeline`. `load_all()` importe ce module ; `tasks.py` en lit
`PIPELINE`.

Jusqu'au 2026-10-13 le converter passait pour une app « à un seul process » : sa tâche convertissait
PUIS appliquait le post-traitement IA (agrandissement, débruitage, amélioration audio — des
modèles GPU, un coût et un échec propres) sur le fichier converti, réécrit en place. Décision de
Fabien : « toutes les applications doivent fonctionner en pipeline ». DEUX process :
  • `convert` — le fichier → sa conversion (ffmpeg, Pillow, pandoc… selon la nature). Toute card.
  • `enhance` — la conversion → le post-traitement IA demandé. Seulement quand un post-traitement
    est DEMANDÉ et que le compte y a droit (un visiteur sans compte n'en a pas : décision du
    2026-08-30, aucune ressource GPU). Son échec fait échouer la card, comme avant : il a été
    demandé, un résultat non traité serait un mensonge — mais la conversion reste.
La conversion BRUTE est gardée quand le post-traitement a lieu (`converted_file`, option 1 de
Fabien) : `enhance` se rejoue seul (×2 → ×4) sans reconvertir ni retraiter un fichier traité.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'converter'
_IMPL = 'converter.tasks:convert_media_task'


def enhances(job, model_key=None) -> bool:
    """Le post-traitement IA a-t-il lieu pour ce job ? Demandé, et le compte y a droit."""
    if not getattr(job, 'ai_postprocess_requested', False):
        return False
    from wama.accounts.permissions import is_guest_account
    return not is_guest_account(job.user)


def conversion_model(job) -> str:
    """Le converter ne choisit pas de modèle pour CONVERTIR (ffmpeg, Pillow, pandoc) : rien à
    tirer, les process se montrent tels quels."""
    return 'auto'


#: Les natures qu'il convertit (le port `work` de l'app), et celles qu'un post-traitement IA sert
#: (`format_router.CROSS_APP_OPTIONS`). Un port par nature : un port nomme UN type.
CONVERTED = ('image', 'video', 'audio', 'document', 'archive')
ENHANCED = ('image', 'video', 'audio')

register(FunctionSpec(
    key='converter.convert', name='Converter — convertir',
    description="Convertit le fichier au format demandé (vidéo, audio, image, document, "
                "archive), avec les réglages d'encodage de la card.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['ffmpeg', 'conversion'],
    inputs=[PortSpec(f'work_{nature}', nature, optional=True, group='travail',
                     description=f"Le fichier à convertir ({nature}).") for nature in CONVERTED],
    outputs=[PortSpec(f'converted_{nature}', nature, optional=True,
                      description=f"Le fichier converti ({nature}).") for nature in CONVERTED]))

register(FunctionSpec(
    key='converter.enhance', name='Converter — post-traitement IA',
    description="Applique à la conversion le post-traitement IA demandé : agrandissement ou "
                "débruitage d'une image, amélioration de l'audio (ou de la piste son d'une vidéo).",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['gpu', 'upscale', 'audio'],
    inputs=[PortSpec(f'converted_{nature}', nature, optional=True,
                     description=f"La conversion brute ({nature}).") for nature in ENHANCED],
    outputs=[PortSpec(f'enhanced_{nature}', nature, optional=True,
                      description=f"Le fichier post-traité ({nature}).") for nature in ENHANCED]))


#: `watched` : les champs HORS schéma. La conversion surveille son entrée et la DEMANDE d'un
#: post-traitement (elle décide où va la conversion) ; les RÉGLAGES déclarent eux-mêmes ce
#: qu'ils périment (`Param.stales`, params.py).
PIPELINE = register_app_pipeline(_APP, (
    ProcessSpec('convert', label='Conversion', watched=('input_file', 'ai_postprocess_requested'),
                share=3, eta='converter.tasks:convert_eta',
                # La conversion brute quand un post-traitement suit, la sortie sinon.
                outputs=('converted_file', 'output_file')),
    ProcessSpec('enhance', label='Post-traitement IA', depends_on=('convert',), applies=enhances,
                gpu=True, share=2, eta='converter.tasks:enhance_eta', outputs=('output_file',)),
), label='Converter — conversion, post-traitement IA',
   source_ref='converter.function_specs:PIPELINE',
   model_of=conversion_model)
