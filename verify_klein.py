import sys, os
sys.path.insert(0, r'D:\WAMA\web-app-for-media-automation')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()
from wama.imager.utils.model_config import FLUX2_KLEIN_MODELS, IMAGER_MODELS, get_model_info
print('flux2-klein-4b in IMAGER_MODELS:', 'flux2-klein-4b' in IMAGER_MODELS)
info = get_model_info('flux2-klein-4b')
print('hf_id:', info['hf_id'])
print('cache_dir:', info['cache_dir'])
from wama.imager.backends.flux2_klein_backend import Flux2KleinBackend, SUPPORTED_MODELS
print('SUPPORTED_MODELS:', list(SUPPORTED_MODELS.keys()))
print('is_available:', Flux2KleinBackend.is_available())
