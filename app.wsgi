import os
import sys

sys.path.insert(0, "D:/WAMA/webapp-for-autormatic-media-anonymization")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wama.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

with open("D:/WAMA/debug_wsgi.txt", "a") as f:
    f.write("app.wsgi exécuté\n")