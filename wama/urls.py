from django.urls import path, include
from django.conf import settings
from django.contrib import admin
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import HttpResponse

urlpatterns = [
    path('', TemplateView.as_view(template_name='home.html'), name='home'),
    path('accounts/', include(('wama.accounts.urls', 'accounts'), namespace='accounts')),
    path('medias/', include(('wama.medias.urls', 'medias'), namespace='medias')),
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('favicon.ico'))),
    path('ping/', lambda request: HttpResponse("Django OK via Apache")),
    path('admin/', admin.site.urls),
    # path('celery-progress/', include('celery_progress.urls')),
    # path('help/', TemplateView.as_view(template_name='help/index.html'), name='help'),
    # path('about/', TemplateView.as_view(template_name='about/index.html'), name='about'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
