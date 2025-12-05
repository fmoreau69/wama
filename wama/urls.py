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
    path('anonymizer/', include(('wama.anonymizer.urls', 'anonymizer'), namespace='anonymizer')),
    path('synthesizer/', include(('wama.synthesizer.urls', 'synthesizer'), namespace='synthesizer')),
    path('transcriber/', include(('wama.transcriber.urls', 'transcriber'), namespace='transcriber')),
    path('imager/', include(('wama.imager.urls', 'imager'), namespace='imager')),
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('favicon.ico'))),
    path('ping/', lambda request: HttpResponse("Django OK via Apache")),
    path('admin/', admin.site.urls),
    # path('celery-progress/', include('celery_progress.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
