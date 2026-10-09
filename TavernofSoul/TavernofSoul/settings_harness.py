"""Offline harness settings. Never select a regional database or JSON tree."""
import os
from copy import deepcopy
from pathlib import Path

from .settings_test import *  # noqa: F403

# The launcher owns and cleans this directory; direct invocations must supply it.
HARNESS_WORK_DIR = Path(os.environ['HARNESS_WORK_DIR'])
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
        'TEST': {'NAME': ':memory:'},
    },
}
SECRET_KEY = 'offline-harness-only'
DEBUG = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
REGION = 'ktos'
JSON_ROOT = HARNESS_WORK_DIR / 'json'
MEDIA_ROOT = HARNESS_WORK_DIR / 'media'
MEDIA_URL = '/media/'
CHANGES_DIR = HARNESS_WORK_DIR / 'changes'
STATIC_ROOT = HARNESS_WORK_DIR / 'static'
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
TEMPLATES = deepcopy(TEMPLATES)
for template in TEMPLATES:
    template['OPTIONS']['context_processors'].append('harness.context_processors.offline')
