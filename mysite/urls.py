from django.urls import path, re_path
from django.conf import settings
from django.conf.urls import include
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from django.contrib.staticfiles.storage import staticfiles_storage

urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('accounts/', include(('mysite.accounts.urls', 'accounts'), namespace='accounts')),
    path('medias/', include(('mysite.medias.urls', 'medias'), namespace='medias')),
    path('help/', TemplateView.as_view(template_name='help/index.html'), name='help'),
    path('about/', TemplateView.as_view(template_name='about/index.html'), name='about'),
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('favicon.ico'))),
    # path('celery-progress/', include('celery_progress.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
