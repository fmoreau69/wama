"""Créer UNE synthèse — le chemin UNIQUE, quelle que soit la surface (2026-09-30).

POURQUOI. Une synthèse naissait par CINQ chemins écrits chacun à sa façon : la card (fichier
déposé → `upload`, texte saisi → `upload_text`), le lot, l'import depuis le gestionnaire de
fichiers, et l'outil `synthesize_text` que le STUDIO et l'assistant appellent. Ils ne créaient pas
la même chose (un `.docx` d'un côté, un `.txt` de l'autre ; un lot par une fonction, un autre à la
main) et, surtout, **l'outil ne connaissait que le texte** : un document ou une voix de référence
branchés sur le nœud du Studio étaient IGNORÉS en silence. Constat de Fabien, le 30/09 : *« le
studio utilise les apps en tant que card ; si l'app déclare ses capacités, le studio en hérite ;
ça doit être le même chemin »* (règle de `WAMA_APP_GENERATION_ROUTE §10.6` : « jamais de colle
côté studio, on finit le port »).

CE QU'IL REÇOIT — les ENTRÉES PAR PORT (les ids de `app_input_ports` / `app_own_input_ports`) :
  • `prompt`          : le texte saisi ;
  • `work_file`       : un fichier de travail (TXT, MD, PDF, DOCX, CSV) — l'un OU l'autre ;
  • `reference_voice` : un échantillon de voix pour le clonage (optionnel).
  Chaque fichier arrive déjà REÇU (`media_paths.ReceivedInput` : téléversé, ou DÉSIGNÉ puis pointé)
  — la card le reçoit par `received_inputs`, l'outil par `designate` : une seule forme.
et les RÉGLAGES par le SCHÉMA de l'app (`schema_model_kwargs`, coercés et bornés) — plus les trois
réglages Higgs que le schéma ne déclare pas (zone dédiée du gabarit), lus ICI et nulle part ailleurs.
"""
from django.core.files.base import ContentFile

from wama.common.tts.constants import DEFAULT_TTS_MODEL, tts_catalog_key
from wama.common.utils.auto_model import read_quality_intent

#: Ce que le fichier de travail peut être — le validateur du champ `text_file`, lu, pas recopié.
TEXT_FILE_EXTENSIONS = ('txt', 'pdf', 'docx', 'csv', 'md')

#: Réglages Higgs, champs du modèle ABSENTS du schéma (rendus par la zone Higgs du gabarit).
HIGGS_SETTINGS = ('emotion_intensity', 'multi_speaker', 'scene_description')


class SynthesisRefused(ValueError):
    """Création refusée — le message est destiné à l'utilisateur."""


def synthesis_settings(params) -> dict:
    """Les réglages d'une synthèse depuis un dict (POST d'une card, kwargs d'un outil, params d'un
    nœud) : ceux du SCHÉMA, coercés et bornés, puis les réglages Higgs."""
    from wama.common.utils.param_schema import schema_model_kwargs
    params = dict(params or {})
    settings = schema_model_kwargs('synthesizer', params)
    settings['tts_model'] = tts_catalog_key(settings.get('tts_model') or DEFAULT_TTS_MODEL)
    settings['quality_intent'] = read_quality_intent(params.get('quality_intent'))
    if params.get('emotion_intensity') not in (None, ''):
        settings['emotion_intensity'] = max(0.0, min(2.0, float(params['emotion_intensity'])))
    if 'multi_speaker' in params:
        settings['multi_speaker'] = str(params['multi_speaker']).lower() in ('1', 'true', 'on', 'yes')
    if params.get('scene_description'):
        settings['scene_description'] = str(params['scene_description'])
    return settings


def _title_from(text: str, title: str = '') -> str:
    import re
    base = (title or ' '.join(text.split()[:5])).strip()
    return re.sub(r'[^\w\s-]', '', base)[:50].strip() or 'synthesizer'


def create_synthesis(user, *, prompt: str = '', work_file=None, reference_voice=None,
                     title: str = '', params=None, wrap: bool = True):
    """Crée la synthèse (et son lot d'un élément si `wrap`). Rend l'objet ; lève `SynthesisRefused`.

    `work_file` / `reference_voice` : des `ReceivedInput` (ou None). `prompt` sert si aucun
    fichier de travail n'est donné — l'un OU l'autre (décision de Fabien, 2026-09-30).
    """
    from .models import VoiceSynthesis

    text = (prompt or '').strip()
    if work_file is None and not text:
        raise SynthesisRefused('Aucun texte : saisissez-le, ou fournissez un fichier de travail.')
    if work_file is not None:
        ext = work_file.name.rsplit('.', 1)[-1].lower() if '.' in work_file.name else ''
        if ext not in TEXT_FILE_EXTENSIONS:
            raise SynthesisRefused(f"Format non supporté ({ext or 'sans extension'}). "
                                   f"Formats acceptés : {', '.join(TEXT_FILE_EXTENSIONS)}")
        text_file = work_file.value
    else:
        # Le texte saisi devient le fichier de travail de la card — un `.txt` : ce qu'on lit est
        # ce qu'on a écrit, sans mise en forme à deviner (le `.docx` d'avant n'apportait rien).
        text_file = ContentFile(text.encode('utf-8'), name=f'{_title_from(text, title)}.txt')

    synthesis = VoiceSynthesis.objects.create(
        user=user, text_file=text_file,
        voice_reference=reference_voice.value if reference_voice is not None else None,
        **synthesis_settings(params))
    if work_file is not None:
        work_file.record(synthesis, 'text_file')
    if reference_voice is not None:
        reference_voice.record(synthesis, 'voice_reference')

    try:
        from .utils.text_extractor import clean_text_for_tts, extract_text_from_file
        synthesis.text_content = clean_text_for_tts(extract_text_from_file(synthesis.text_file.path))
    except Exception as exc:
        if not text:
            synthesis.status = 'FAILURE'
            synthesis.error_message = f"Erreur d'extraction : {exc}"
            synthesis.save(update_fields=['status', 'error_message'])
            raise SynthesisRefused(f"Impossible d'extraire le texte : {exc}")
        synthesis.text_content = text
    # ⚠ `update_metadata()` n'enregistre QUE ses compteurs : le texte extrait restait en mémoire
    # dans les cinq chemins d'avant (le worker le ré-extrayait au lancement).
    synthesis.save(update_fields=['text_content'])
    synthesis.update_metadata()

    if wrap:
        wrap_in_batch(synthesis)
    return synthesis


def wrap_in_batch(synthesis):
    """Un lot d'UN élément — la file est construite à partir des lots."""
    import os
    from .models import BatchSynthesis, BatchSynthesisItem
    stem = (os.path.splitext(os.path.basename(synthesis.text_file.name))[0]
            if synthesis.text_file else f'synthesis_{synthesis.id}')
    batch = BatchSynthesis.objects.create(user=synthesis.user, total=1)
    BatchSynthesisItem.objects.create(batch=batch, synthesis=synthesis,
                                      output_filename=stem + '.wav', row_index=0)
    return batch
