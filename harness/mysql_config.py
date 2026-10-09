"""Explicit, narrowly scoped connection settings for a disposable MySQL server."""
import os

DATABASE_NAME = 'tavern_harness'
TEST_DATABASE_NAME = 'test_tavern_harness'
DATABASE_USER = 'tavern_harness'


def database_config(environ=None):
    environ = os.environ if environ is None else environ
    required = ('HARNESS_MYSQL_HOST', 'HARNESS_MYSQL_PORT',
                'HARNESS_MYSQL_USER', 'HARNESS_MYSQL_PASSWORD')
    missing = [name for name in required if not environ.get(name)]
    if missing:
        raise RuntimeError('MySQL harness requires explicit ' + ', '.join(missing))
    if environ['HARNESS_MYSQL_HOST'] != '127.0.0.1':
        raise RuntimeError('MySQL harness host must be 127.0.0.1')
    try:
        port = int(environ['HARNESS_MYSQL_PORT'])
    except ValueError:
        raise RuntimeError('MySQL harness port must be an integer') from None
    if not 1024 <= port <= 65535 or port == 3306:
        raise RuntimeError('MySQL harness requires a mapped port above 1023, excluding 3306')
    if environ['HARNESS_MYSQL_USER'] != DATABASE_USER:
        raise RuntimeError('MySQL harness user must be ' + DATABASE_USER)
    return {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': DATABASE_NAME,
        'USER': DATABASE_USER,
        'PASSWORD': environ['HARNESS_MYSQL_PASSWORD'],
        'HOST': '127.0.0.1',
        'PORT': port,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'connect_timeout': 5,
            'isolation_level': 'read committed',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION', "
                            "default_storage_engine='InnoDB'",
        },
        'TEST': {
            'NAME': TEST_DATABASE_NAME,
            'CHARSET': 'utf8mb4',
            'COLLATION': 'utf8mb4_unicode_ci',
        },
    }
