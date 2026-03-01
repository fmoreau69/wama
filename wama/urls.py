from django.urls import path, include
from django.conf import settings
from django.contrib import admin
from django.conf.urls.static import static
from django.views.generic.base import RedirectView
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import HttpResponse
from . import views
from . import tool_api as tool_views

urlpatterns = [
    path('api/v1/', include(('wama.api.v1.urls', 'api_v1'), namespace='api_v1')),
    path('', views.home, name='home'),
    path('presentation/', views.presentation, name='presentation'),
    path('api/ai-chat/', views.ai_chat, name='ai_chat'),
    # WAMA Tool API (agentic AI assistant)
    path('api/tools/list-files/',        tool_views.list_user_files_view,       name='tool_list_files'),
    path('api/tools/anonymizer/add/',    tool_views.add_to_anonymizer_view,     name='tool_anon_add'),
    path('api/tools/anonymizer/start/',  tool_views.start_anonymizer_view,      name='tool_anon_start'),
    path('api/tools/anonymizer/status/', tool_views.get_anonymizer_status_view, name='tool_anon_status'),
    path('api/tools/sam3-examples/',     tool_views.sam3_examples_view,         name='tool_sam3_examples'),
    path('accounts/', include(('wama.accounts.urls', 'accounts'), namespace='accounts')),
    path('common/', include(('wama.common.urls', 'common'), namespace='common')),
    path('anonymizer/', include(('wama.anonymizer.urls', 'anonymizer'), namespace='anonymizer')),
    path('describer/', include(('wama.describer.urls', 'describer'), namespace='describer')),
    path('enhancer/', include(('wama.enhancer.urls', 'enhancer'), namespace='enhancer')),
    path('filemanager/', include(('wama.filemanager.urls', 'filemanager'), namespace='filemanager')),
    path('imager/', include(('wama.imager.urls', 'imager'), namespace='imager')),
    path('synthesizer/', include(('wama.synthesizer.urls', 'synthesizer'), namespace='synthesizer')),
    path('transcriber/', include(('wama.transcriber.urls', 'transcriber'), namespace='transcriber')),
    path('avatarizer/', include(('wama.avatarizer.urls', 'avatarizer'), namespace='avatarizer')),
    path('model-manager/', include(('wama.model_manager.urls', 'model_manager'), namespace='model_manager')),
    # WAMA Lab - Experimental/Research applications
    path('lab/', include(('wama_lab.urls', 'wama_lab'), namespace='wama_lab')),
    path('favicon.ico', RedirectView.as_view(url=staticfiles_storage.url('images/favicon.ico'))),
    path('ping/', lambda request: HttpResponse("Django OK via Apache")),
    path('admin/', admin.site.urls),
    # path('celery-progress/', include('celery_progress.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
