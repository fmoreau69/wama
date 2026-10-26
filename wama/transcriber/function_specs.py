"""Le PIPELINE du transcriber — ses process internes, déclarés au catalogue commun.

`WAMA_APP_GENERATION_ROUTE.md §10.6` (marche P4, 2ᵉ pilote après le composer) : décision n°11 —
un registre de process en code, chaque process un `FunctionSpec binding: app`, le registre
exporté en manifeste `pipeline`. `load_all()` importe ce module ; `workers.py` en lit `PIPELINE`.

HUIT process (point 3.2 de la route : « une app Médias = `required` + `optional` ») :
  • `level`      — l'audio → la parole nivelée, GARDÉE sur la card (`leveled_audio`). OPTIONNEL :
    quand la card le demande, ou demande le débruitage (qui n'écoute jamais un audio non nivelé).
  • `denoise`    — l'audio nivelé → débruité (DeepFilterNet), GARDÉ (`denoised_audio`). OPTIONNEL,
    interrupteur `preprocess_audio`. Ces deux-là se faisaient DANS `transcribe` jusqu'au
    2026-10-21, dans un fichier temporaire (`split_from`, `ROUTE §10.6` 4.6).
  • `transcribe` — l'audio préparé par ses amonts → le texte et ses segments horodatés (filtre de
    parole et langue compris). REQUIS pour une card sans document.
  • `import`     — le document posé sur la card (port `work_result` : SRT, VTT, Sonal, texte)
    TIENT LIEU de transcription : relu, ancré sur les mots d'une sortie ASR s'il n'a pas
    d'heures, jamais retranscrit. REQUIS pour une card qui porte un document. `transcribe` et
    `import` s'excluent : une card joue l'un OU l'autre, et les trois process suivants
    s'appuient sur celui qui a lieu (demande de Fabien, 2026-10-03).
  • `diarize`    — les segments → les mêmes, attribués à leurs locuteurs (pyannote). OPTIONNEL,
    interrupteur `enable_diarization` ; sans objet quand le moteur diarise lui-même (VibeVoice).
  • `summarize`  — le texte → résumé structuré ou compte-rendu de réunion (LLM). OPTIONNEL,
    interrupteur `generate_summary`.
  • `coherence`  — le texte → score, remarques, version proposée, et cohérence par segment
    (LLM). OPTIONNEL, interrupteur `verify_coherence`.

Ce que la séparation apporte, et que la tâche unique ne savait pas faire :
  - changer le type de résumé ne rejoue QUE le résumé ; la transcription reste valide ;
  - relancer la diarisation périme résumé et cohérence, en aval, sans retranscrire ;
  - un résumé qui échoue (Ollama absent) se VOIT sur la card — sa ligne est en échec, la card
    « reste à compléter », ▶ ne rejoue que lui. Avant : un avertissement en console, une card
    « terminée » sans résumé, et rien pour le dire ;
  - le résumé « à la demande » (`enrich_transcript`, hors contrat du squelette jusqu'ici, point
    4.7) est le ▶ du process `summarize`.

  • `align`      — l'aligneur acoustique du catalogue recale les mots d'un document SANS heures,
    que l'import n'a pu qu'estimer (étage B). OPTIONNEL (son échec garde les heures estimées),
    sans interrupteur ; sans objet pour un document horodaté (SRT, VTT). Placé avant les
    locuteurs et la cohérence, qui travaillent sur les heures et les segments qu'il réécrit. Il
    ne part qu'au lancement de la card, jamais au dépôt du document (décision de Fabien,
    2026-10-03).
"""
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  PortSpec, register)
from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline
from wama.common.services.process_runs import OPTIONAL

_APP = 'transcriber'
_IMPL = 'transcriber.workers:transcribe'


def diarizes_natively(model_key) -> bool:
    """Le moteur de ce modèle attribue-t-il lui-même les locuteurs ? Lu sur la classe du backend
    que le catalogue résout (`supports_diarization`) — jamais sur un nom de moteur. Inconnu
    (clé « auto », nom hors catalogue) : faux, l'interrupteur décide et la glu tranche au
    lancement sur le moteur réellement chargé."""
    if not model_key:
        return False
    try:
        from wama.common.backends.manager import backend_for_key
        from wama.transcriber.backends.manager import catalogue_value
        return bool(getattr(backend_for_key(catalogue_value(model_key)),
                            'supports_diarization', False))
    except Exception:
        return False


def _has_existing_result(transcript, model_key=None) -> bool:
    return bool(getattr(transcript, 'work_result', None))


def _transcribes(transcript, model_key=None) -> bool:
    return not _has_existing_result(transcript)


def _align_applies(transcript, model_key=None) -> bool:
    """Un document repris SANS heures : c'est une propriété du DOCUMENT (son format), stable — pas
    de l'état des segments, qui change quand l'alignement a tourné."""
    import os
    from .utils.transcript_documents import TIMED_EXTENSIONS
    document = getattr(transcript, 'work_result', None)
    return bool(document) and os.path.splitext(document.name)[1].lower() not in TIMED_EXTENSIONS


def _levels(transcript, model_key=None) -> bool:
    """La parole est nivelée quand on la transcrit et que la card le demande — ou qu'elle demande
    le débruitage, qui n'écoute JAMAIS un audio non nivelé (banc du 2026-10-01, `WAMA_QUALITE
    §9bis` : DeepFilterNet efface une parole enregistrée bas)."""
    return _transcribes(transcript) and bool(getattr(transcript, 'level_speech', False)
                                              or getattr(transcript, 'preprocess_audio', False))


def _denoises(transcript, model_key=None) -> bool:
    return _transcribes(transcript)


def _diarize_applies(transcript, model_key) -> bool:
    # Un document repris n'a pas de moteur : l'interrupteur de la card décide seul.
    return _has_existing_result(transcript) or not diarizes_natively(model_key)


register(FunctionSpec(
    key='transcriber.level', name='Transcriber — niveler la parole',
    description="Amène chaque voix au même niveau tout au long de l'audio, sans jamais abaisser "
                "le niveau d'ensemble (brique commune `speech_leveling`). L'audio nivelé est gardé "
                "sur la card : c'est lui que la transcription écoute.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'speech'],
    inputs=[PortSpec('work_audio', 'audio', description="L'audio (ou la vidéo) à niveler.")],
    outputs=[PortSpec('audio', 'audio', description="L'audio nivelé, mono 16 kHz.")]))

register(FunctionSpec(
    key='transcriber.denoise', name='Transcriber — débruiter',
    description="Débruite l'audio nivelé par le modèle du catalogue (DeepFilterNet), pour les fonds "
                "très bruyants. L'audio débruité est gardé sur la card : c'est lui que la "
                "transcription écoute.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'speech', 'gpu'],
    inputs=[PortSpec('audio', 'audio', description="L'audio nivelé.")],
    outputs=[PortSpec('audio', 'audio', description="L'audio débruité, mono 16 kHz.")]))

register(FunctionSpec(
    key='transcriber.transcribe', name='Transcriber — transcrire',
    description="Transcrit la parole d'un audio (ou de la piste son d'une vidéo) en texte "
                "horodaté, avec le modèle de la card ou le tirage automatique — l'audio nivelé ou "
                "débruité quand la card le demande. Filtre de parole et choix de la langue en "
                "font partie.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'speech', 'gpu'],
    inputs=[PortSpec('work_audio', 'audio', description="L'audio (ou la vidéo) à transcrire.")],
    outputs=[PortSpec('transcript', 'document', description="Le texte et ses segments horodatés.")]))

register(FunctionSpec(
    key='transcriber.import', name='Transcriber — reprendre un résultat existant',
    description="Fait d'une transcription produite ailleurs (SRT, VTT, export Sonal, texte) le "
                "résultat de la card, sans moteur de transcription. Un texte sans heures est "
                "ancré sur les mots d'une transcription du même audio.",
    category=FC.TRANSFORM, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'import'],
    inputs=[PortSpec('work_result', 'document', description="La transcription à reprendre.")],
    outputs=[PortSpec('transcript', 'document', description="Le texte et ses segments.")]))

register(FunctionSpec(
    key='transcriber.align', name="Transcriber — aligner les mots sur l'audio",
    description="Recale sur l'audio les mots d'une transcription reprise sans heures : l'aligneur "
                "acoustique du catalogue reprend ceux que l'ancrage n'a pu qu'estimer.",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'alignment', 'gpu'],
    inputs=[PortSpec('transcript', 'document', description="La transcription à recaler."),
            PortSpec('work_audio', 'audio', description="L'audio sur lequel recaler.")],
    outputs=[PortSpec('transcript', 'document', description="La transcription, mots recalés.")]))

register(FunctionSpec(
    key='transcriber.diarize', name='Transcriber — attribuer les locuteurs',
    description="Attribue chaque segment de la transcription à son locuteur (pyannote). Sans "
                "objet pour un moteur qui diarise lui-même.",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['audio', 'speech', 'gpu'],
    inputs=[PortSpec('transcript', 'document', description="La transcription à attribuer."),
            PortSpec('work_audio', 'audio', description="L'audio dont les voix sont séparées.")],
    outputs=[PortSpec('transcript', 'document', description="La transcription, par locuteur.")]))

register(FunctionSpec(
    key='transcriber.summarize', name='Transcriber — résumer',
    description="Résume la transcription : résumé structuré (points clés, actions) ou "
                "compte-rendu de réunion, selon le réglage de la card.",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'llm'],
    inputs=[PortSpec('transcript', 'document', description="La transcription à résumer.")],
    outputs=[PortSpec('summary', 'document', description="Le résumé.")]))

register(FunctionSpec(
    key='transcriber.coherence', name='Transcriber — vérifier la cohérence',
    description="Note la cohérence de la transcription, relève ses anomalies, propose une "
                "version corrigée et signale les segments douteux (heatmap de l'éditeur).",
    category=FC.ENRICHER, binding=Binding.APP, app=_APP, impl=_IMPL,
    tags=['text', 'llm'],
    inputs=[PortSpec('transcript', 'document', description="La transcription à vérifier.")],
    outputs=[PortSpec('report', 'document', description="Score, remarques et version proposée.")]))


#: `watched` : les champs HORS schéma (le résultat importé). Les RÉGLAGES déclarent eux-mêmes ce
#: qu'ils périment (`Param.stales`, params.py, 2026-10-05) — transcription : modèle, mots-clés,
#: prétraitement, nivellement, filtre de parole, langues ; locuteurs : modèle de diarisation ;
#: résumé : son type. `PIPELINE.watched_of(spec)` réunit les deux.

#: Le RÉSULTAT LISIBLE de chaque process (`ProcessSpec.result`, 2026-10-12) : la section de
#: l'export TXT enrichi qu'il remplit — ce que l'aperçu commun montre en face du process.
#: L'alignement n'en a pas : il recale des heures, son effet se lirait sur les segments.
_DOCUMENTS = 'transcriber.utils.transcript_documents'


def _requested_model(t):
    """Le modèle que la card demande, « auto » compris : les process se montrent AVANT le
    premier lancement — c'est là que leurs cases à cocher servent."""
    from wama.transcriber.backends.manager import catalogue_value
    return catalogue_value(t.backend) or 'auto'


#: `card_model` : la transcription emploie LE modèle de la card — tiré distant (Albert), elle ne
#: tient pas la carte (`ProcessSpec.card_model`, 2026-10-14). Les autres process GPU gardent leur
#: modèle local (alignement, locuteurs, résumé et cohérence par l'Ollama hôte).
PIPELINE = register_app_pipeline(_APP, (
    # La PRÉPARATION de l'audio (2026-10-21, décision de Fabien : « rendre le pré-traitement en
    # tant que process déclaré ») : faite jusque-là DANS `transcribe`, dans un fichier temporaire.
    # Deux process, parce qu'ils ne tiennent pas les mêmes ressources : le nivellement est un
    # calcul sur le signal (file par défaut — une transcription distante n'en change pas de file),
    # le débruitage charge un modèle sur la carte. Chacun GARDE son audio (`outputs`) : la
    # transcription et les locuteurs l'écoutent (`upstream_output`), l'aperçu et la page de
    # correction le font entendre. `split_from` : une transcription rendue avant le détachement
    # l'a fait en elle-même — elle vaut pour eux tant que leurs réglages n'ont pas changé.
    ProcessSpec('level', label='Nivellement', degree=OPTIONAL, applies=_levels, share=2,
                outputs=('leveled_audio',), split_from='transcribe',
                eta='transcriber.workers:level_eta'),
    ProcessSpec('denoise', label='Débruitage', depends_on=('level',), degree=OPTIONAL,
                toggle='preprocess_audio', applies=_denoises, gpu=True, share=2,
                outputs=('denoised_audio',), split_from='transcribe',
                eta='transcriber.workers:denoise_eta'),
    # `upstream_switch` (2026-10-22) : « Transcrire l'audio préparé » décoché, la transcription et
    # les locuteurs écoutent l'original ; l'audio préparé reste produit et ÉCOUTABLE (correction).
    # `checks` (même jour, décision de Fabien) : la part de la parole que la transcription couvre
    # — un texte perdu (moteur distant, filtre de parole, débruitage) se voit sur sa ligne.
    ProcessSpec('transcribe', label='Transcription', depends_on=('level', 'denoise'),
                upstream_switch='use_prepared_audio', checks=('speech_coverage',),
                applies=_transcribes, gpu=True, card_model=True, share=17,
                eta='transcriber.workers:transcribe_eta',
                result=f'{_DOCUMENTS}:transcription_text'),
    # L'import relit un document (quelques secondes) : pas d'ETA propre, sa dernière durée suffit.
    ProcessSpec('import', label='Import', watched=('work_result',),
                applies=_has_existing_result, share=1, result=f'{_DOCUMENTS}:transcription_text'),
    ProcessSpec('align', label='Alignement', depends_on=('import',), degree=OPTIONAL,
                applies=_align_applies, gpu=True, share=2, eta='transcriber.workers:align_eta'),
    ProcessSpec('diarize', label='Locuteurs', depends_on=('transcribe', 'import', 'align'),
                degree=OPTIONAL, toggle='enable_diarization', upstream_switch='use_prepared_audio',
                applies=_diarize_applies, gpu=True, share=1, eta='transcriber.workers:diarize_eta',
                result=f'{_DOCUMENTS}:diarization_segments', result_format='segments'),
    # Résumé et cohérence lisent le texte ET ses locuteurs (le compte-rendu de réunion les cite,
    # la cohérence par segment s'écrit sur les segments que la diarisation réécrit). `gpu` : un
    # modèle de langage (Ollama hôte, sur la carte), que la file GPU sérialise (`ProcessSpec.gpu`).
    ProcessSpec('summarize', label='Résumé', depends_on=('transcribe', 'import', 'diarize'),
                degree=OPTIONAL, toggle='generate_summary', gpu=True, share=1,
                eta='transcriber.workers:summarize_eta', result=f'{_DOCUMENTS}:summary_text',
                result_format='markdown'),
    ProcessSpec('coherence', label='Cohérence',
                depends_on=('transcribe', 'import', 'align', 'diarize'),
                degree=OPTIONAL, toggle='verify_coherence', gpu=True, share=1,
                eta='transcriber.workers:coherence_eta', result=f'{_DOCUMENTS}:coherence_report',
                result_format='coherence'),
), label='Transcriber — nivellement, débruitage, transcription ou import, alignement, '
         'locuteurs, résumé, cohérence',
   source_ref='transcriber.function_specs:PIPELINE',
   model_of=lambda t: _requested_model(t))
