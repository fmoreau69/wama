"""Le PIPELINE du composer — ses process internes, déclarés au catalogue commun.

Décision n°11 de `WAMA_APP_GENERATION_ROUTE.md §10.6` (Fabien, 2026-10-02) : les process internes
d'une app Médias se déclarent comme les passes du cam_analyzer — un registre de process en code,
chaque process un `FunctionSpec binding: app` (un nœud `function` du catalogue), le registre
exporté en manifeste `pipeline`. `load_all()` importe ce module ; `tasks.py` en lit `PIPELINE`.

TROIS process, et un seul est NORMAL :
  • `render` — la consigne (et une partition, quand il y en a une) → l'audio. C'est le process
    de TOUS les modèles ; pour la plupart, c'est le seul.
  • `plan`   — la consigne → une partition ABC. N'a lieu que pour un modèle dont le moteur
    DÉCLARE `supports_score_planning` (YuE2 : sa chaîne « paroles → partition → audio » est déjà
    séparée dans son code), et seulement si l'utilisateur n'a pas fourni sa propre partition.
  • `extract_score` (2026-10-03) — l'audio du morceau à reprendre → sa partition (SheetSage2,
    tâche `audio-to-score`). N'a lieu que pour un COVER par un modèle qui suit une partition sans
    prendre l'audio lui-même (YuE2) ; il REMPLACE alors `plan` — la partition vient de l'audio,
    pas de la consigne. Jamais « transcribe » : ce verbe est celui du transcriber.

Ce que la séparation apporte : changer un réglage du rendu (durée, format) ne rejoue pas la
partition ; une partition corrigée à la main se rend sans être replanifiée ; un rendu qui
échoue se relance sans refaire ce qui a réussi.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline

_APP = 'composer'
_IMPL = 'composer.tasks:compose_task'


def plans_a_score(model_key) -> bool:
    """Le moteur du modèle sait-il écrire une partition avant de la jouer ? Lu sur la classe du
    backend que le catalogue résout — jamais sur un nom de modèle."""
    if not model_key:
        return False
    from wama.common.backends.manager import backend_for_key
    return bool(getattr(backend_for_key(model_key), 'supports_score_planning', False))


def _extract_applies(gen, model_key) -> bool:
    """Juge l'ÉLÉMENT : un audio de cover est donné (fichier, ou URL qui le remplira au lancement),
    aucune partition n'est fournie, et le modèle de rendu reprend l'audio PAR SA PARTITION.
    Qu'un modèle d'extraction soit installé est la DISPONIBILITÉ du process (`available`), lue
    par `AppPipeline.takes_place` — un seul lieu, jamais redemandé ici."""
    if not model_key or getattr(gen, 'reference_score', None):
        return False
    if not (getattr(gen, 'melody_reference', None) or getattr(gen, 'source_url', '')):
        return False
    from .utils.model_choice import covers_audio_by_score
    return covers_audio_by_score(model_key)


def _extract_available() -> bool:
    from .utils.model_choice import score_extraction_available
    return score_extraction_available()


def extracts_score(gen, model_key) -> bool:
    """Le process `extract_score` a-t-il lieu pour cette card ? — la réponse de `takes_place`,
    que posent aussi `plan` (son alternative) et le rendu (quelle partition suivre)."""
    return PIPELINE.takes_place(PIPELINE.spec('extract_score'), gen, model_key)


def _plan_applies(gen, model_key) -> bool:
    return (plans_a_score(model_key) and not getattr(gen, 'reference_score', None)
            and not extracts_score(gen, model_key))


register(FunctionSpec(
    key='composer.plan', name='Composer — écrire la partition',
    description="Écrit la partition (ABC) d'une chanson depuis sa consigne : style en tête, "
                "paroles en sections. N'existe que pour un modèle qui planifie avant de jouer "
                "(YuE2). La partition est un résultat de la card : lisible, corrigeable, rejouable.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('prompt', 'prompt', description="La consigne : style, puis paroles.")],
    outputs=[PortSpec('score', 'score', description="La partition ABC que le rendu suivra.")]))

register(FunctionSpec(
    key='composer.extract_score', name='Composer — extraire la partition',
    description="Extrait la partition (ABC, mélodie seule) de l'audio du morceau à reprendre, pour "
                "un modèle qui reprend un audio PAR SA PARTITION (YuE2). La partition est un "
                "résultat de la card : lisible, corrigeable, rejouable.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', group='travail',
                     description="Audio du morceau à reprendre (cover).")],
    outputs=[PortSpec('score', 'score', description="La partition que le rendu suivra.")]))

register(FunctionSpec(
    key='composer.render', name='Composer — rendre le son',
    description="Génère l'audio depuis la consigne — en suivant une partition quand le modèle en "
                "prend une (celle que `composer.plan` a écrite, ou celle que l'utilisateur fournit).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('prompt', 'prompt', description="La consigne de génération."),
            # Nommés comme les ENTRÉES de l'app (la card, `compose_music`, le nœud du studio) — un
            # nom pour une même entrée ; `score` / `audio` sont leurs TYPES. Ports de TRAVAIL depuis
            # le 2026-10-03 (décision de Fabien) : dans un COVER, le morceau source est ce que le
            # rendu transforme, pas un guide.
            PortSpec('work_score', 'score', optional=True, group='travail',
                     description="Partition du morceau à reprendre (cover), OPTIONNELLE : sans "
                                 "elle, le modèle compose librement."),
            PortSpec('work_audio', 'audio', optional=True, group='travail',
                     description="Audio du morceau à reprendre (cover, MusicGen Melody) : sa "
                                 "mélodie est rejouée dans le style de la consigne.")],
    outputs=[PortSpec('audio', 'audio', description="Le morceau ou le bruitage généré.")]))


#: Réglages dont le changement périme le rendu : tout ce que la glu lit de l'élément.
_RENDER_WATCHED = ('prompt', 'model', 'quality_intent', 'duration', 'output_format',
                   'output_quality', 'reference_score', 'melody_reference', 'source_url')

PIPELINE = register_app_pipeline(_APP, (
    # La partition EXTRAITE ne dépend que de l'audio (remarque d'ae, 2026-10-03) : changer le
    # modèle de RENDU ne la périme pas — s'il cesse de suivre une partition, c'est `applies` qui
    # écarte le process, pas la péremption. `source_url` remplit l'audio au lancement.
    ProcessSpec('extract_score', label='Partition extraite',
                watched=('melody_reference', 'source_url'),
                gpu=True, share=1, applies=_extract_applies, available=_extract_available,
                outputs=('extracted_score',)),
    # La partition ne dépend que de la consigne et du modèle (le curseur pèse dans le tirage
    # « auto », donc dans le modèle) — ni de la durée ni du format, qui sont au rendu.
    ProcessSpec('plan', label='Partition', watched=('prompt', 'model', 'quality_intent'),
                gpu=True, share=1, applies=_plan_applies, outputs=('planned_score',)),
    # Deux amonts ALTERNATIFS, exclusifs par `applies` : un amont sans objet est ignoré.
    ProcessSpec('render', label='Rendu', depends_on=('extract_score', 'plan'),
                watched=_RENDER_WATCHED, gpu=True, share=3, outputs=('audio_output',)),
), label='Composer — partition puis rendu', source_ref='composer.function_specs:PIPELINE')
