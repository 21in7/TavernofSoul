"""Disposable MySQL DB with the same isolated files/cache as the offline harness."""
from .settings_harness import *  # noqa: F403
from harness.mysql_config import database_config

DATABASES = {'default': database_config()}
