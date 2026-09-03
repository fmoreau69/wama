"""Backends du describer — contrat commun + registre `BackendManager` (brique commune)."""
from wama.common.backends.manager import BackendManager

from .blip_backend import BlipBackend

#: ── ROUTAGE nature → backend : LA déclaration que la chaîne de génération COMPOSE ─────────
#: (marche B1 describer, 2026-09-03 — 2ᵉ app routée, 1ʳᵉ à MODÈLES IA ; pilote converter.)
#:
#: CONTRAT COMMUN « texte » (les 4 signatures l'honorent) :
#:     callable(input_path, options=dict, progress_callback=fn, partial_callback=fn,
#:              console=fn) -> str
#: `options` = valeurs EFFECTIVES lues des colonnes (modèle événementiel §23.2quater) ;
#: les callbacks sont optionnels (no-op par défaut). Le texte rendu est le RÉSULTAT — la
#: glu (task_skeleton) le persiste dans la colonne déclarée par `RESULT`.
#:
#: Chemins EN CHAÎNES (pas d'imports) : la déclaration se lit sans rien charger (extracteur
#: de manifeste), et la jumelle qui copie `backends/` résout vers SES copies via son propre
#: chemin de paquet (le composeur remplace le préfixe d'app).
ROUTES = {
    'image':    'backends.image_backend.describe_image',
    'video':    'backends.video_backend.describe_video',
    'audio':    'backends.audio_backend.describe_audio',
    'document': 'backends.text_backend.describe_text',
}

#: Ce que les backends PRODUISENT et où la tâche le range — la déclaration qui distingue
#: les deux SAVEURS de composition (tasks_gen) : 'file' (converter — le backend écrit
#: output_path, la tâche range le chemin) / 'text' (describer — le backend REND le texte,
#: la tâche le persiste dans `field`). Absent = 'file' (contrat historique du pilote).
RESULT = {'kind': 'text', 'field': 'result_text'}

#: Colonne du modèle d'item qui porte la NATURE d'entrée (clé de ROUTES). Le converter
#: utilise `media_type` (défaut historique) ; le describer détecte à l'upload et stocke
#: dans `detected_type` (valeurs historiques 'text'/'pdf' normalisées À LA LECTURE par
#: `content_analyzer.normalize_detected_type` — la glu ET le corps composé normalisent).
NATURE_FIELD = 'detected_type'

#: Registre/singletons — brique commune (remplace le boilerplate de manager par-app).
MANAGER = BackendManager('describer')
MANAGER.register('blip', BlipBackend)


def get_blip() -> BlipBackend:
    """Instance singleton (keep_loaded) du backend BLIP."""
    return MANAGER.get_backend('blip')


__all__ = ['BlipBackend', 'MANAGER', 'get_blip', 'ROUTES', 'RESULT', 'NATURE_FIELD']
