"""Check the target and privileges before Django creates or drops its test DB."""
import re

from harness.mysql_config import database_config


def validate_grants(grants):
    # Escaped underscores are literal schema names, not MySQL grant wildcards.
    allowed = {r'`tavern\_harness`.*', r'`test\_tavern\_harness`.*'}
    scopes = set()
    for grant in grants:
        match = re.fullmatch(r'GRANT (.+) ON (.+) TO .+', grant)
        if not match or 'WITH GRANT OPTION' in grant:
            raise RuntimeError('MySQL harness account must have no roles or grant option')
        privileges, scope = match.groups()
        if scope == '*.*' and privileges == 'USAGE':
            continue
        if scope not in allowed:
            raise RuntimeError('MySQL harness account may access only the two harness schemas')
        scopes.add(scope)
    if scopes != allowed:
        raise RuntimeError('MySQL harness account needs privileges on both harness schemas')


def inspect_database():
    from django.conf import settings
    from django.db import connection
    expected = database_config()
    actual = settings.DATABASES['default']
    for key in ('ENGINE', 'NAME', 'USER', 'PASSWORD', 'HOST', 'PORT', 'OPTIONS'):
        if actual[key] != expected[key]:
            raise RuntimeError('MySQL harness database settings differ from the isolated configuration')
    for key, value in expected['TEST'].items():
        if actual['TEST'].get(key) != value:
            raise RuntimeError('MySQL harness test database settings differ from the isolated configuration')
    with connection.cursor() as cursor:
        cursor.execute('SHOW GRANTS FOR CURRENT_USER')
        validate_grants([row[0] for row in cursor.fetchall()])
        cursor.execute('SELECT VERSION(), @@SESSION.sql_mode, @@SESSION.default_storage_engine, '
                       '@@SESSION.character_set_connection, @@SESSION.transaction_isolation')
        version, sql_mode, engine, charset, isolation = cursor.fetchone()
    if 'MariaDB' in version or int(version.split('.')[0]) < 8:
        raise RuntimeError('MySQL harness requires MySQL 8 or newer')
    if 'STRICT_TRANS_TABLES' not in sql_mode.split(',') or engine != 'InnoDB' or \
            charset != 'utf8mb4' or isolation != 'READ-COMMITTED':
        raise RuntimeError('MySQL harness requires strict SQL, InnoDB, utf8mb4 and read committed')
    return {'vendor': 'mysql', 'version': version, 'sql_mode': sql_mode,
            'storage_engine': engine, 'charset': charset, 'isolation': isolation,
            'host': actual['HOST'], 'port': actual['PORT'],
            'database': actual['NAME'], 'test_database': actual['TEST']['NAME'],
            'collation': actual['TEST']['COLLATION']}
