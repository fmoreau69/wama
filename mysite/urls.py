from django.urls import re_path
from django.conf import settings
from django.conf.urls import include
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from django.contrib.staticfiles.storage import staticfiles_storage

urlpatterns = [
    re_path(r'^$', TemplateView.as_view(template_name='home.html'), name='home'),
    re_path(r'^accounts/', include(('mysite.accounts.urls', 'accounts'), namespace='accounts')),
    re_path(r'^medias/', include(('mysite.medias.urls', 'medias'), namespace='medias')),
    re_path(r'^help/', TemplateView.as_view(template_name='help/index.html'), name='help'),
    re_path(r'^about/', TemplateView.as_view(template_name='about/index.html'), name='about'),
    re_path(r'^favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('favicon.ico'))),
    # re_path(r'^celery-progress/', include('celery_progress.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
