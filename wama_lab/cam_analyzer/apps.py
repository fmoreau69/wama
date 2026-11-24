from django.apps import AppConfig


class CamAnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_lab.cam_analyzer'
    verbose_name = 'Cam Analyzer'

    def ready(self):
        """Initialize the cam analyzer when Django starts."""
        # Déclare les traitements cam_analyzer dans le catalogue WAMA Data (capabilities).
        try:
            from . import function_specs  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                'cam_analyzer function_specs non enregistrées', exc_info=True)
        # L'app se DÉCLARE au substrat : son monde et sa page (menu, `/apps/`, journal, calendrier
        # la lisent — route §10.6 point 6.1). Le substrat ne cite plus le Lab par son nom.
        from wama.common.app_registry import DEFAULT_MEDIA_FOLDERS, register_surface
        register_surface('cam_analyzer', world='lab', label='Cam Analyzer',
                         url_name='wama_lab:cam_analyzer:index', icon='fa-video',
                         color='#ffc107', order=20, media_folders=DEFAULT_MEDIA_FOLDERS,
                         description="Analyse multi-caméras synchronisées pour navette autonome : "
                                     "détection d'objets, timeline de proximité, segmentation "
                                     "temporelle.")
        # Le monde Lab entre au journal et au calendrier (WAMA_MEMORY §9bis.1) : une card du
        # cam_analyzer est une SESSION d'analyse, datée de bout en bout (started/completed_at).
        from wama.common.services.journal import enregistrer_source
        from .models import AnalysisSession
        enregistrer_source('cam_analyzer', AnalysisSession)

        # Les MARQUES d'une session dans le vocabulaire temporel commun (marche 1 de
        # `ROUTE §10.7`, 2026-11-24) : aucun stockage ne change, un lecteur rend `start` / `end`
        # là où la session range `t_enter` / `t_exit`, `t_start` / `t_end`, `start_time` /
        # `end_time`. Un conflit nomme sa fenêtre par son RANG (`intersection_window_idx`,
        # -1 = hors de toute fenêtre) : l'imbrication par référence.
        # Ce que l'écran a à savoir (`ROUTE §10.7.14`, 2026-11-24) : la ligne segmentée de la
        # card est celle des SITUATIONS, colorées par leur type ; un conflit se colore par sa
        # sévérité, ses trois valeurs de la plus bénigne à la plus grave (`tasks.py` : info, warn,
        # critical). Aucun geste : ces marques sont calculées, on les regarde.
        from wama.common.catalog.marks import CATEGORY, SEVERITY, Track, register_tracks
        register_tracks(AnalysisSession, (
            Track('windows', "Fenêtres d'intersection", source='intersection_windows',
                  fields=(('start', 't_enter'), ('end', 't_exit')), attributes=('name',),
                  origin='intersection_windows'),
            Track('conflicts', 'Conflits', source='conflicts',
                  fields=(('start', 't_start'), ('end', 't_end')),
                  attributes=(('type', 'conflict_type'), 'severity', 'track_id'),
                  parent='windows', parent_ref='intersection_window_idx', origin='conflicts',
                  color_by='severity', scale=SEVERITY, steps=('info', 'warn', 'critical')),
            Track('situations', 'Situations', source='segments',
                  fields=(('start', 'start_time'), ('end', 'end_time')),
                  attributes=(('type', 'segment_type'),), origin='temporal_segments',
                  main=True, color_by='type', scale=CATEGORY),
        ))
