"""
URL patterns for Face Analyzer.
"""
from django.urls import path
from . import views

app_name = 'face_analyzer'

urlpatterns = [
    # Main views
    path('', views.index, name='index'),
    path('realtime/', views.realtime_view, name='realtime'),
    path('video/', views.video_view, name='video'),
    path('video/<uuid:session_id>/', views.video_view, name='video_session'),

    # Session management API
    path('api/sessions/', views.list_sessions, name='list_sessions'),
    path('api/sessions/create/', views.create_session, name='create_session'),
    path('api/sessions/<uuid:session_id>/start/', views.start_analysis, name='start_analysis'),
    path('api/sessions/<uuid:session_id>/cancel/', views.cancel_analysis, name='cancel_analysis'),
    path('api/sessions/<uuid:session_id>/status/', views.get_session_status, name='session_status'),
    path('api/sessions/<uuid:session_id>/frames/', views.get_frame_data, name='frame_data'),
    path('api/sessions/<uuid:session_id>/delete/', views.delete_session, name='delete_session'),

    # Real-time analysis API
    path('api/realtime/frame/', views.process_frame_realtime, name='process_frame'),
]
