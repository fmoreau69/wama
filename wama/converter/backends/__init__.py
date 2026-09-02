
#: ── ROUTAGE nature → backend : LA déclaration que la chaîne de génération COMPOSE ─────────
#: (marche B1, 2026-09-02 — cadrage Fabien ROADMAP §23.5 : « composition DÉCLARÉE des
#: backends EXISTANTS », étage 2 ; un backend N'EST PAS une fonction du catalogue data.)
#:
#: CONTRAT COMMUN (normalisé le même jour — les 5 signatures l'honorent) :
#:     callable(input_path, output_path, output_format, options=dict, progress_callback=fn)
#: `options` = valeurs EFFECTIVES lues des colonnes (modèle événementiel §23.2quater) ;
#: `progress_callback` accepté partout (ignoré par les conversions quasi instantanées).
#:
#: Chemins EN CHAÎNES (pas d'imports) : la déclaration se lit sans rien charger (extracteur
#: de manifeste), et la jumelle qui copie `backends/` résout vers SES copies via son propre
#: chemin de paquet (le composeur remplace le préfixe d'app).
ROUTES = {
    'image':    'backends.image_backend.convert_image',
    'video':    'backends.video_backend.convert_video',
    'audio':    'backends.audio_backend.convert_audio',
    'document': 'backends.document_backend.convert_document',
    'archive':  'backends.archive_backend.convert_archive',
}
