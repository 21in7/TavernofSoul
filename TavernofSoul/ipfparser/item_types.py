"""Reuse item types by their unchanged name and equipment flag."""

from django.db.models import BinaryField
from django.db.models.functions import Cast

from Items.models import Item_Type


class _NameBytes(Cast):
    """Use MySQL/MariaDB's binary cast syntax, not a blob column type."""

    def as_mysql(self, compiler, connection, **extra_context):
        extra_context['template'] = 'CAST(%(expressions)s AS BINARY)'
        return super().as_sql(compiler, connection, **extra_context)


def get_or_create_item_type(name, is_equipment, cache=None):
    """Return ``(row, created)`` for an exact, unnormalized string/flag pair.

    The optional dict belongs to one invocation and must not survive rollback.
    Cache hits return created=False. No concurrent-writer guarantee is added.
    """
    pair = (name, is_equipment)
    if cache is not None and pair in cache:
        return cache[pair], False

    exact_types = Item_Type.objects.alias(
        _item_type_name_bytes=_NameBytes('name', output_field=BinaryField()),
    ).filter(_item_type_name_bytes=name.encode('utf-8'))
    try:
        item_type, created = exact_types.get_or_create(
            name=name, is_equipment=is_equipment,
        )
    except Item_Type.MultipleObjectsReturned:
        # Keep legacy duplicate rows, consistently reusing the smallest PK.
        item_type = exact_types.filter(
            name=name, is_equipment=is_equipment,
        ).order_by('pk').first()
        if item_type is None:
            raise
        created = False

    if cache is not None:
        cache[pair] = item_type
    return item_type, created
