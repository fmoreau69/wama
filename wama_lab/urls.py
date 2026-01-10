"""
URL patterns for WAMA Lab applications.
"""
from django.urls import path, include

app_name = 'wama_lab'

urlpatterns = [
    path('face-analyzer/', include('wama_lab.face_analyzer.urls', namespace='face_analyzer')),
]
