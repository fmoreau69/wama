"""
URL patterns for Cam Analyzer.
"""
from django.urls import path
from . import views

app_name = 'cam_analyzer'

urlpatterns = [
    # Main view
    path('', views.index, name='index'),

    # Sessions API
    path('api/sessions/', views.list_sessions, name='list_sessions'),
    path('api/sessions/create/', views.create_session, name='create_session'),
    path('api/sessions/<uuid:session_id>/', views.get_session, name='get_session'),
    path('api/sessions/<uuid:session_id>/delete/', views.delete_session, name='delete_session'),
    path('api/sessions/<uuid:session_id>/duplicate/', views.duplicate_session, name='duplicate_session'),
    path('api/sessions/<uuid:session_id>/update/', views.update_session, name='update_session'),
    path('api/sessions/<uuid:session_id>/gps-offset/', views.set_gps_offset, name='set_gps_offset'),
    path('api/sessions/<uuid:session_id>/camera-yaw/', views.set_camera_yaw, name='set_camera_yaw'),
    path('api/sessions/<uuid:session_id>/features/', views.set_features, name='set_features'),
    path('api/sessions/<uuid:session_id>/complete-analysis/', views.complete_analysis, name='complete_analysis'),
    path('api/sessions/<uuid:session_id>/live-cursor/', views.live_cursor, name='live_cursor'),
    path('api/sessions/<uuid:session_id>/sync-rec/', views.sync_from_rec, name='sync_from_rec'),
    path('api/sessions/<uuid:session_id>/prediction/', views.prediction_annotate, name='prediction_annotate'),

    # Camera management
    path('api/sessions/<uuid:session_id>/cameras/upload/', views.upload_camera, name='upload_camera'),
    path('api/cameras/<int:camera_id>/delete/', views.delete_camera, name='delete_camera'),
    path('api/cameras/<int:camera_id>/update-position/', views.update_camera_position, name='update_camera_position'),
    path('api/cameras/<int:camera_id>/stream/', views.stream_video, name='stream_video'),

    # Analysis (Phase 2)
    path('api/sessions/<uuid:session_id>/start/', views.start_analysis, name='start_analysis'),
    path('api/sessions/<uuid:session_id>/status/', views.get_session_status, name='session_status'),
    path('api/sessions/<uuid:session_id>/cancel/', views.cancel_analysis, name='cancel_analysis'),
    path('api/sessions/<uuid:session_id>/recompute-windows/', views.recompute_windows, name='recompute_windows'),
    path('api/sessions/<uuid:session_id>/start-sam3/', views.start_sam3_only, name='start_sam3_only'),
    path('api/sessions/<uuid:session_id>/ortho-recalage/', views.ortho_recalage, name='ortho_recalage'),
    path('api/sessions/<uuid:session_id>/calibrate/', views.calibrate_homography, name='calibrate_homography'),
    path('api/sessions/<uuid:session_id>/sam3-test/', views.sam3_test_frame, name='sam3_test_frame'),
    path('api/sessions/<uuid:session_id>/sam3-test-result/', views.sam3_test_result, name='sam3_test_result'),
    path('api/sessions/<uuid:session_id>/passes/', views.list_passes, name='list_passes'),
    path('api/sessions/<uuid:session_id>/passes/run/', views.run_passes, name='run_passes'),
    path('api/sessions/<uuid:session_id>/cameras/<int:camera_id>/detections/', views.get_detections, name='get_detections'),

    # Export & Analytics (Phase 3)
    path('api/sessions/<uuid:session_id>/export/detections/', views.export_detections_csv, name='export_detections'),
    path('api/sessions/<uuid:session_id>/export/json/', views.export_session_json, name='export_json'),
    path('api/sessions/<uuid:session_id>/export/segments/', views.export_segments_csv, name='export_segments'),
    path('api/sessions/<uuid:session_id>/export/conflicts/', views.export_conflicts_csv, name='export_conflicts'),
    path('api/sessions/<uuid:session_id>/segments/', views.get_segments, name='get_segments'),
    path('api/sessions/<uuid:session_id>/analytics/', views.get_analytics_data, name='get_analytics'),

    # Profiles
    path('api/profiles/', views.list_profiles, name='list_profiles'),
    path('api/profiles/save/', views.save_profile, name='save_profile'),
    path('api/profiles/<int:profile_id>/delete/', views.delete_profile, name='delete_profile'),

    # Road segmentation model auto-download (keremberke/yolov8m-bdd100k-seg)
    path('api/road-model/download/', views.download_road_model, name='download_road_model'),

    # RTMaps extraction
    path('api/sessions/<uuid:session_id>/rtmaps/upload/', views.upload_rtmaps, name='upload_rtmaps'),
    path('api/sessions/<uuid:session_id>/rtmaps/upload-avi/', views.upload_quadrature_avi, name='upload_quadrature_avi'),
    path('api/sessions/<uuid:session_id>/rtmaps/status/', views.rtmaps_status, name='rtmaps_status'),

    # Console
    path('console/', views.console_content, name='console'),
]
