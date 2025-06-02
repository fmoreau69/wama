import os
import sys

sys.path.insert(0, "D:/WAMA/web-app-for-media-automation")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wama.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
