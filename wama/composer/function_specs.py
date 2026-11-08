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
    séparée dans son code ; la fiche du catalogue le porte, `apply_engine_flags`), et seulement si
    l'utilisateur n'a pas fourni sa propre partition.
  • `extract_score` (2026-10-03) — l'audio du morceau à reprendre → sa partition (SheetSage2,
    tâche `audio-to-score`). N'a lieu que pour un COVER par un modèle qui suit une partition sans
    prendre l'audio lui-même (YuE2) ; il REMPLACE alors `plan` — la partition vient de l'audio,
    pas de la consigne. Jamais « transcribe » : ce verbe est celui du transcriber.
Et deux process OPTIONNELS de lecture (2026-10-26, décision de Fabien), qui ne nourrissent rien :
  • `parts` — la partition COMPLÈTE de l'ENTRÉE (l'audio du cover), à côté de la réduite ;
  • `rendered_parts` — la partition complète du morceau PRODUIT, dérivée du rendu, pour comparer ;
  • `rendered_score` (2026-11-08, la symétrie) — sa partition réduite, le pendant d'`extract_score`.
Et deux process d'ÉCOUTE, optionnels sans interrupteur (2026-11-03, décision de Fabien), qui
remplissent le champ « Paroles » quand il est vide et que le modèle chante :
  • `extract_lyrics` — les paroles du morceau repris, avant ce qui les chante ;
  • `rendered_lyrics` — ce que le modèle a chanté de lui-même, dérivé du rendu.

Ce que la séparation apporte : changer un réglage du rendu (durée, format) ne rejoue pas la
partition ; une partition corrigée à la main se rend sans être replanifiée ; un rendu qui
échoue se relance sans refaire ce qui a réussi.

Depuis le 2026-11-07 (décisions de Fabien : « partition réduite autonome », « rendu facultatif ») :
  • `extract_score` est l'interrupteur de l'utilisateur pour TOUT cover (`extract_reduced_score`),
    IMPOSÉ quand le modèle reprend le cover par sa partition (`required_by=COVERS_BY_SCORE`) ;
  • `render` porte un interrupteur (`generate_audio`) et reste REQUIS activé : coupé, ce qui ne lit
    que lui — sortie, partition et paroles de sortie — n'a plus lieu (`AppPipeline.starved`). Une
    card peut ne demander que les partitions d'un audio ;
  • les partitions de l'ENTRÉE ne dépendent plus du modèle de rendu : une card de musique suffit
    (`MAKES_MUSIC`), un bruitage n'en a pas.
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.output_process import output_spec
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline
from wama.common.services.process_runs import OPTIONAL

_APP = 'composer'
_IMPL = 'composer.tasks:compose_task'


def _extract_applies(gen, model_key) -> bool:
    """Juge l'ÉLÉMENT : un audio de cover est donné (fichier, ou URL qui le remplira au lancement)
    et aucune partition n'est fournie. Depuis le 2026-11-07 (décision de Fabien, « partition
    réduite autonome »), le process est l'interrupteur de l'utilisateur pour TOUT cover, et
    IMPOSÉ quand le modèle de rendu reprend l'audio par sa partition (`required_by=COVERS_BY_SCORE`)
    — il ne dépend plus d'un modèle connu : l'élément seul en juge. Qu'un modèle d'extraction
    soit installé reste la DISPONIBILITÉ du process (`available`)."""
    if getattr(gen, 'reference_score', None):
        return False
    return bool(getattr(gen, 'melody_reference', None) or getattr(gen, 'source_url', ''))


def _extract_available() -> bool:
    from .utils.model_choice import score_extraction_available
    return score_extraction_available()


def _parts_available() -> bool:
    from .utils.model_choice import parts_extraction_available
    return parts_extraction_available()


def _parts_applies(gen, model_key) -> bool:
    """La partition complète de l'ENTRÉE (2026-10-26) : il faut un audio repris — fichier, ou URL
    qui le remplira au lancement. Une partition IMPORTÉE est elle-même l'entrée : rien à
    transcrire. Le modèle de rendu n'y entre pas : le rendu ne la suit pas."""
    if getattr(gen, 'reference_score', None):
        return False
    return bool(getattr(gen, 'melody_reference', None) or getattr(gen, 'source_url', ''))


def extracts_score(gen, model_key) -> bool:
    """Le process `extract_score` a-t-il lieu pour cette card ? — la réponse de `takes_place`,
    que posent aussi `plan` (son alternative) et le rendu (quelle partition suivre)."""
    return PIPELINE.takes_place(PIPELINE.spec('extract_score'), gen, model_key)


def _plan_applies(gen, model_key) -> bool:
    """Juge l'ÉLÉMENT : aucune partition fournie, aucune extraite (son alternative). Que le moteur
    écrive sa partition avant de la jouer est une capacité, déclarée en donnée
    (`needs=PLANS_A_SCORE`, 2026-11-06) — d'où, depuis le 2026-11-08, plus de « modèle connu » exigé
    ici : sous « auto » l'élément seul en juge, et la bande ne replie pas à tort une partition que le
    tirage composera (`AppPipeline.step_state`)."""
    return not getattr(gen, 'reference_score', None) and not extracts_score(gen, model_key)


def _lyrics_available() -> bool:
    from .utils.model_choice import lyrics_transcription_available
    return lyrics_transcription_available()


def _lyrics_to_write(gen, model_key) -> bool:
    """« Écrire les paroles » (2026-11-08, décision de Fabien : une ÉTAPE, plus une écriture cachée
    dans la lecture de la consigne) : la voix « Chanson » est demandée et aucune parole n'est là —
    ni sur la card, ni dans le prompt. Des paroles posées ne se réécrivent JAMAIS. Que le modèle
    CHANTE est une capacité (`needs=SINGS`). Celles qu'on écoute dans un morceau repris arrivent
    avant (`extract_lyrics`) : l'étape ne fait alors rien, et le dit."""
    from .utils import vocals
    if vocals.normalize(getattr(gen, 'vocals', None)) != vocals.SONG:
        return False
    return not vocals.has_lyrics(getattr(gen, 'prompt', ''), getattr(gen, 'lyrics', ''))


def _lyrics_extract_applies(gen, model_key) -> bool:
    """Les paroles de l'ENTRÉE : il faut un audio repris — fichier, ou URL qui le remplira au
    lancement (`_parts_applies`, la même entrée). Depuis le 2026-11-08 l'écoute a lieu même quand
    le champ « Paroles » est rempli : elle range les paroles HORODATÉES que la partition montre sous
    ses notes ; le champ, lui, n'est rempli que s'il est vide."""
    return bool(getattr(gen, 'melody_reference', None) or getattr(gen, 'source_url', ''))


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
    key='composer.extract_score', name="Composer — partition réduite de l'entrée",
    description="Extrait la partition (ABC, mélodie seule) de l'audio du morceau à reprendre, pour "
                "un modèle qui reprend un audio PAR SA PARTITION (YuE2). La partition est un "
                "résultat de la card : lisible, corrigeable, rejouable.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', group='travail',
                     description="Audio du morceau à reprendre (cover).")],
    outputs=[PortSpec('score', 'score', description="La partition que le rendu suivra.")]))

register(FunctionSpec(
    key='composer.parts', name="Composer — partition complète de l'entrée",
    description="Écrit la partition COMPLÈTE du morceau à reprendre (cover) : une partie par "
                "instrument entendu (voix, piano, basse, batterie…), par un modèle de la tâche "
                "`audio-to-midi` (MuScriptor) mis en notation par la brique commune — à côté de la "
                "partition réduite, sur le même audio. Optionnelle ; montrée et corrigée sur la "
                "page d'édition, jamais donnée au rendu (YuE2 ne suit que la réduite).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', group='travail',
                     description="Audio du morceau à reprendre (cover).")],
    outputs=[PortSpec('score', 'score', description="La partition, une partie par instrument.")]))

register(FunctionSpec(
    key='composer.rendered_score', name='Composer — partition réduite jouée',
    description="Écrit la partition RÉDUITE (mélodie et accords) du morceau PRODUIT, pour la comparer "
                "à la partition de référence — par le même modèle que la partition réduite de "
                "l'entrée. Optionnelle ; montrée sur la page d'édition, lue seulement.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('audio', 'audio', description="Le morceau rendu.")],
    outputs=[PortSpec('score', 'score', description="La mélodie et les accords joués.")]))

register(FunctionSpec(
    key='composer.rendered_parts', name='Composer — partition complète jouée',
    description="Écrit la partition COMPLÈTE du morceau PRODUIT, une partie par instrument, pour la "
                "comparer à celle de l'entrée — par le même modèle et la même notation que la "
                "partition complète. Optionnelle ; montrée sur la page d'édition, lue seulement.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('audio', 'audio', description="Le morceau rendu.")],
    outputs=[PortSpec('score', 'score', description="La partition de sortie, une partie par "
                                                    "instrument.")]))

register(FunctionSpec(
    key='composer.extract_lyrics', name="Composer — paroles de l'entrée",
    description="Écoute les paroles du morceau à reprendre (cover) et en range les paroles horodatées "
                "au mot, que la partition de référence montre sous ses notes ; remplit le champ "
                "« Paroles », en sections calées sur la partition, s'il est vide : YuE2 ne reçoit ni "
                "l'audio ni son texte, et sa doc prescrit cette transcription. À relire.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', group='travail',
                     description="Audio du morceau à reprendre (cover)."),
            PortSpec('score', 'score', optional=True,
                     description="La partition du morceau, dont les paroles prennent les sections.")],
    # Type `prompt` : les paroles rejoignent la consigne, qu'écrire la partition et le rendu lisent.
    outputs=[PortSpec('lyrics', 'prompt', description="Les paroles entendues, en sections balisées.")]))

register(FunctionSpec(
    key='composer.write_lyrics', name='Composer — écrire les paroles',
    description="Écrit les paroles d'une chanson (voix « Chanson » sans paroles) depuis sa consigne, "
                "à la LONGUEUR du morceau, dans le champ « Paroles » — le même geste que le bouton "
                "« Écrire les paroles » du réglage. Avant la partition composée : YuE2 bâtit la "
                "structure de sa partition sur les sections des paroles.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'music', 'llm'],
    inputs=[PortSpec('prompt', 'prompt', description="La consigne : ce dont la chanson parle.")],
    outputs=[PortSpec('lyrics', 'prompt', description="Les paroles écrites, en sections balisées.")]))

register(FunctionSpec(
    key='composer.rendered_lyrics', name='Composer — paroles chantées',
    description="Écoute ce que le modèle a CHANTÉ et en range les paroles horodatées au mot, que la "
                "partition jouée montre sous ses notes, pour comparer avec ce qui était demandé ; "
                "remplit le champ « Paroles » s'il est resté vide (un texte improvisé).",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'music', 'gpu'],
    inputs=[PortSpec('audio', 'audio', description="Le morceau rendu.")],
    outputs=[PortSpec('lyrics', 'prompt', description="Les paroles entendues, en sections balisées.")]))

register(FunctionSpec(
    key='composer.output', name='Composer — réglages de sortie',
    description="Applique le format et la qualité de sortie de la card au WAV que le modèle a "
                "rendu. Garde ce WAV tant que la sortie le transforme, pour se rejouer sans "
                "regénérer.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'format'],
    inputs=[PortSpec('native', 'audio', description="Le WAV que le modèle a rendu.")],
    outputs=[PortSpec('audio', 'audio', description="Le morceau au format demandé.")]))

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


#: Ce que la partition et le rendu surveillent HORS schéma (2026-10-05) : les RÉGLAGES — prompt,
#: modèle, curseur, voix, paroles, durée — déclarent eux-mêmes ce qu'ils périment (`Param.stales`,
#: params.py), et `PIPELINE.watched_of(spec)` réunit les deux. Restent ici les champs que le
#: schéma ne porte pas : l'enrichi (`prompt_processed`, éditable dans la modale) et les fichiers.
# ⚠ Le format et la qualité de sortie sont au process `output` (2026-10-03) : changer de format
# ne rejoue pas le rendu.
_PROMPT_WATCHED = ('prompt_processed',)
_RENDER_WATCHED = _PROMPT_WATCHED + ('reference_score', 'melody_reference', 'source_url')

#: Ce que les process exigent du MODÈLE de la card, en DONNÉE (`ProcessSpec.needs`, 2026-11-05 —
#: décision de Fabien : « quelle capacité du modèle rend ce réglage utile ? ») : le serveur les juge,
#: la page cache la section des réglages d'un process que le modèle choisi ne sert pas. Un bruitage
#: (AudioGen, tâche `text-to-audio`) n'a ni partition de sortie ni paroles.
from .utils.model_choice import MUSIC_TASK  # noqa: E402
from .utils.vocals import CAPABILITY as SINGS  # noqa: E402

MAKES_MUSIC = {'field': 'task', 'in': [MUSIC_TASK]}
# ⚠ `TAKES_A_COVER` (« le modèle de rendu reprend un morceau ») bornait la partition complète de
# l'ENTRÉE au modèle de RENDU (2026-11-05) — retiré le 2026-11-07 : le rendu devient facultatif, et
# la partition d'un audio se demande sans rien rendre (décision de Fabien). Les deux partitions de
# l'entrée exigent seulement une card de MUSIQUE (`MAKES_MUSIC`) : un bruitage n'en a pas — la
# règle du 2026-11-05, gardée.
#: Il reprend un audio PAR SA PARTITION : il suit une partition sans prendre l'audio lui-même (YuE2)
#: — l'audio du cover passe alors par la partition qu'on en extrait.
COVERS_BY_SCORE = {'all': [{'field': 'inputs_optional', 'in': ['work_score']},
                           {'not': {'field': 'inputs_optional', 'in': ['work_audio']}}]}
#: Son moteur écrit la partition AVANT de la jouer (`plan_score`, fait du moteur porté sur la fiche).
PLANS_A_SCORE = 'supports_score_planning'


def _requested_model(gen):
    """Le modèle que la card demande. Sous « auto » il n'est connu qu'au lancement : `None` —
    la bande montre ce qui a tourné, le ▶ d'un process laisse la tâche trancher."""
    from wama.common.utils.auto_model import is_auto
    from wama.composer.utils.model_choice import normalize
    return None if is_auto(gen.model) else normalize(gen.model)


PIPELINE = register_app_pipeline(_APP, (
    # La partition EXTRAITE ne dépend que de l'audio (remarque d'ae, 2026-10-03) : changer le
    # modèle de RENDU ne la périme pas — s'il cesse de suivre une partition, c'est `applies` qui
    # écarte le process, pas la péremption. `source_url` remplit l'audio au lancement.
    # Libellés de la bande (2026-10-26, Fabien : « les 2 sont des partitions extraites, l'une est
    # réduite, l'autre complète — ce n'est pas très clair ») : « réduite » / « complète », comme
    # la bascule de la vue partition ; celle du morceau produit, « de sortie ».
    # Autonome depuis le 2026-11-07 (décision de Fabien) : l'interrupteur de l'utilisateur pour
    # tout cover, IMPOSÉ quand le modèle reprend le cover par sa partition (`required_by`).
    ProcessSpec('extract_score', label='Partition réduite',
                watched=('melody_reference', 'source_url'),
                degree=OPTIONAL, toggle='extract_reduced_score', required_by=COVERS_BY_SCORE,
                needs=MAKES_MUSIC, gpu=True, share=1, applies=_extract_applies,
                available=_extract_available,
                outputs=('extracted_score',), eta='composer.tasks:extract_score_eta'),
    # PARTITION COMPLÈTE de l'ENTRÉE (2026-10-16 ; sur l'entrée depuis le 2026-10-26, décision de
    # Fabien : « la partition doit refléter cet audio d'entrée ») : optionnelle (`extract_parts`),
    # à côté de la partition extraite — le même audio, une partie par instrument. Le rendu ne la
    # suit pas (YuE2 ne lit que la réduite) : elle ne le périme pas. Son modèle n'est pas celui de
    # la card : un modèle de la tâche `audio-to-midi` (`parts_model`, ou tiré sous « auto ») ; elle
    # n'a lieu que si un modèle de la tâche est installé (`available`).
    ProcessSpec('parts', label='Partition complète', watched=('melody_reference', 'source_url'),
                degree=OPTIONAL, toggle='extract_parts', gpu=True, share=2, needs=MAKES_MUSIC,
                applies=_parts_applies, available=_parts_available,
                outputs=('parts_score',), eta='composer.tasks:parts_eta'),
    # Les PAROLES de l'entrée (2026-11-03, décision de Fabien) : après la partition, dont elles
    # prennent les sections, avant ce qui les chante. Depuis le 2026-11-08 (« même comportement en
    # entrée et en sortie ») : une case (`extract_input_lyrics`, cochée par défaut — l'écoute était
    # automatique), une card de MUSIQUE suffit (pas un modèle qui chante : on peut ne vouloir que la
    # partition et ses paroles), et elle RANGE ses paroles horodatées (`input_lyrics_timed`). Le
    # champ « Paroles » n'est rempli que s'il est vide (il périme `plan` et `render`).
    # AU NIVEAU DES PARTITIONS depuis le 2026-11-08 (décision de Fabien : « paroles et partition sur
    # un même niveau chronologique, cohérent partout » — en sortie, les paroles chantées sont déjà
    # sœurs des partitions jouées) : elle ne DÉPEND plus de la partition réduite. Elle n'en tirait que
    # ses sections, pour découper le champ « Paroles » ; elle les prend encore quand la partition est
    # là (déclarée avant elle, elle passe d'abord : `topo_order` est STABLE, le patron des recalages
    # du cam_analyzer), sinon les paroles restent d'un seul tenant — ce
    # qui a toujours été le cas sans partition. Corriger la partition ne périme plus les paroles.
    ProcessSpec('extract_lyrics', label="Paroles de l'entrée",
                watched=('melody_reference', 'source_url'), toggle='extract_input_lyrics',
                degree=OPTIONAL, gpu=True, share=1, needs=MAKES_MUSIC, applies=_lyrics_extract_applies,
                available=_lyrics_available, outputs=('input_lyrics_timed',),
                eta='composer.tasks:lyrics_eta'),
    # ÉCRIRE LES PAROLES (2026-11-08, décision de Fabien) : une ÉTAPE, avant la partition composée —
    # YuE2 bâtit la structure de sa partition sur les sections des paroles —, écrites à la LONGUEUR
    # du morceau. C'était une écriture cachée au début du premier process qui lisait la consigne.
    # Le même geste que le bouton du réglage « Paroles » (`write_lyrics_for`).
    # « Paroles écrites » (2026-11-08, décision de Fabien) : nommée par ce qu'elle produit, comme
    # ses voisines ; sa ⚙ montre ce produit, le champ « Paroles » et son bouton ✍️ (`writes`).
    # `gpu=True` : un appel LLM compte comme GPU tant que son modèle n'est connu qu'à l'appel
    # (`ProcessSpec.gpu`) — la fonction est étiquetée `llm` au catalogue (`tests_process_governance`).
    ProcessSpec('write_lyrics', label='Paroles écrites', depends_on=('extract_lyrics',),
                watched=_PROMPT_WATCHED, degree=OPTIONAL, gpu=True, share=1, needs=SINGS,
                applies=_lyrics_to_write, writes=('lyrics',),
                result='composer.tasks:written_lyrics', eta='composer.tasks:write_lyrics_eta'),
    # La partition ne dépend que de la consigne et du modèle (le curseur pèse dans le tirage
    # « auto », donc dans le modèle) — ni de la durée ni du format, qui sont au rendu. « Partition
    # composée » (2026-11-08) : celle que le modèle écrit depuis la consigne, l'alternative de la
    # partition réduite tirée d'un morceau repris.
    ProcessSpec('plan', label='Partition composée', depends_on=('extract_lyrics', 'write_lyrics'),
                watched=_PROMPT_WATCHED,
                gpu=True, share=1, needs=PLANS_A_SCORE, applies=_plan_applies,
                outputs=('planned_score',),
                eta='composer.tasks:plan_eta'),
    # Deux amonts ALTERNATIFS, exclusifs par `applies` : un amont sans objet est ignoré.
    # FACULTATIF depuis le 2026-11-07 (décision de Fabien) : coupé, ce qui ne lit que lui — la
    # sortie, la partition et les paroles de sortie — n'a plus lieu (`AppPipeline.starved`).
    # REQUIS quand il est activé : un rendu en échec fait échouer la card.
    ProcessSpec('render', label='Rendu',
                depends_on=('extract_score', 'extract_lyrics', 'write_lyrics', 'plan'),
                toggle='generate_audio',
                watched=_RENDER_WATCHED, gpu=True, share=3, outputs=('audio_output',),
                eta='composer.tasks:render_eta'),
    # Les réglages de SORTIE (format, qualité) : process COMMUN (`output_process`), toujours joué.
    output_spec(depends_on=('render',)),
    # PARTITION DE SORTIE (2026-10-26, décision de Fabien : « on propose les deux, l'entrée et la
    # sortie ») : optionnelle (`extract_rendered_parts`), une DÉRIVATION du rendu — à côté de la
    # sortie, pas après : elle lit l'audio du RENDU (`output_sources`), changer de format ne la
    # périme pas. Lue seulement, pour comparer ce qui a été demandé et ce qui a été joué.
    # PARTITION RÉDUITE JOUÉE (2026-11-08, décision de Fabien : « ok pour la symétrie ») : le pendant
    # de `extract_score` sur le RENDU — la mélodie réellement chantée, comparable à la référence.
    # Décochée par défaut ; même modèle (`score_extractor`) et même disponibilité que l'entrée.
    ProcessSpec('rendered_score', label='Partition réduite jouée', depends_on=('render',),
                degree=OPTIONAL, toggle='extract_rendered_score', gpu=True, share=1,
                needs=MAKES_MUSIC, available=_extract_available, outputs=('rendered_score',),
                eta='composer.tasks:extract_score_eta'),
    # « Partition complète jouée » (2026-11-08) : nommée comme son pendant de l'entrée.
    ProcessSpec('rendered_parts', label='Partition complète jouée', depends_on=('render',),
                degree=OPTIONAL, toggle='extract_rendered_parts', gpu=True, share=2, needs=MAKES_MUSIC,
                available=_parts_available, outputs=('rendered_parts_score',),
                eta='composer.tasks:parts_eta'),
    # Les PAROLES CHANTÉES (2026-11-03 ; depuis le 2026-11-08, décision de Fabien : « toujours
    # proposées », le MÊME geste qu'en entrée) : une case (`extract_rendered_lyrics`), elles rangent
    # les paroles horodatées que la partition jouée montre sous ses notes — on compare ce qui était
    # demandé et ce qui a été chanté — et remplissent le champ « Paroles » s'il est resté vide. Une
    # DÉRIVATION du rendu ; écrire ce réglage ne le périme pas (`process_runs.settle_setting`).
    ProcessSpec('rendered_lyrics', label='Paroles chantées', depends_on=('render',),
                toggle='extract_rendered_lyrics', degree=OPTIONAL, gpu=True, share=1, needs=SINGS,
                available=_lyrics_available, outputs=('rendered_lyrics_timed',),
                eta='composer.tasks:lyrics_eta'),
), label='Composer — partition, rendu, sortie', source_ref='composer.function_specs:PIPELINE',
   model_of=lambda gen: _requested_model(gen))
