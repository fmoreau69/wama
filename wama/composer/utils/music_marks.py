"""La STRUCTURE d'un morceau — ses parties, ses mesures, sa tonalité, ses accords — rangée au FICHIER.

`WAMA_APP_GENERATION_ROUTE.md §10.7.14 ㉑` (2026-11-25, décisions de Fabien : l'analyse appartient au
fichier ; « garder ce qui est jeté »). Le modèle de la tâche `audio-to-score` (SheetSage2) décode
ces quatre pistes à CHAQUE partition réduite, et seule la partition était gardée. Deux portes, un
seul rangement (`common/utils/media_marks`, les pistes automatiques d'un média) :

  • `keep` — un process de card vient de faire passer le modèle sur un audio : ce qu'il a décodé se
    DÉPOSE aux pistes de ce fichier, sans rien recalculer ;
  • `analyse` — le fichier n'est jamais passé par là : l'analyse est demandée pour elle-même (un
    nœud du Studio, l'assistant), sur la file de l'app (`tasks.music_marks_task`).

Les pistes sont déclarées dans `functions.py` ; leurs clés et ce que leurs marques portent sont le
contrat du moteur (`common/backends/score_extraction_base.MUSIC_TRACKS`).
"""
import logging
import os

logger = logging.getLogger(__name__)

#: Le nom de l'ANALYSE que partagent les quatre pistes : une passe du modèle les remplit toutes.
ANALYSIS = 'music'


def keep(backend, audio_abs: str) -> bool:
    """Dépose aux pistes de l'audio `audio_abs` ce que `backend` vient de décoder en plus de sa
    partition (`backend.marks`). Rend True si quelque chose est rangé. Un audio hors des médias de
    WAMA, un moteur qui ne décode rien de plus : rien, sans bruit — un dépôt ne fait jamais échouer
    le process qui l'offre."""
    from wama.common.utils import media_marks
    found = getattr(backend, 'marks', None)
    if not found or not audio_abs:
        return False
    return media_marks.deposit(audio_abs, ANALYSIS, found)


def analyse(path: str) -> dict:
    """L'analyse DEMANDÉE d'un audio (`detect` des quatre producteurs) : `{clé de piste: lignes}`.
    Le modèle est celui de la tâche `audio-to-score`, chargé pour cette passe et DÉCHARGÉ aussitôt
    — la règle du process `extract_score`. En mélodie seule : la notation la plus sûre, et la
    structure ne dépend pas d'elle ; une partition impossible n'empêche pas de rendre ce qui a été
    décodé. Lève quand aucun modèle n'est installé ou que rien n'a été décodé.

    ⚠ Appelée par la tâche de l'app (`tasks.music_marks_task`), qui a déjà demandé le modèle à la
    route : elle ne télécharge rien."""
    import tempfile

    from wama.common.backends.manager import backend_for_key
    from wama.common.utils.model_keys import model_id
    from .model_choice import score_extractor

    extractor_key = score_extractor()
    backend_class = backend_for_key(extractor_key) if extractor_key else None
    if backend_class is None:
        raise RuntimeError("Aucun modèle d'extraction de partition n'est installé "
                           "(tâche « audio-to-score ») : la structure d'un morceau vient de lui.")
    backend = backend_class()
    try:
        with tempfile.TemporaryDirectory() as annexes:      # MIDI, annotations : non gardés
            try:
                backend.extract_score(model_id=model_id(extractor_key), audio_path=path,
                                      output_dir=annexes, melody_only=True)
            except RuntimeError as error:
                if not getattr(backend, 'marks', None):
                    raise
                logger.info("[composer] structure de %s gardée sans partition (%s)",
                            os.path.basename(path), error)
        found = getattr(backend, 'marks', None)
    finally:
        try:
            backend.unload()
        except Exception:
            logger.warning("[composer] modèle d'extraction non déchargé", exc_info=True)
    if not found:
        raise RuntimeError("Le modèle n'a décodé ni partie, ni mesure, ni tonalité.")
    return found
