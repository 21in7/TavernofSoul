from django.db import migrations, models


def remove_duplicate_drops(apps, schema_editor):
    """Keep the latest write; importer updates it from the authoritative release."""
    drops = apps.get_model('Monsters', 'Item_Monster').objects.using(
        schema_editor.connection.alias)
    previous = None
    duplicates = []
    for pk, monster, item in drops.order_by('monster_id', 'item_id', '-pk').values_list(
            'pk', 'monster_id', 'item_id').iterator(chunk_size=2000):
        pair = (monster, item)
        if pair == previous:
            duplicates.append(pk)
        previous = pair
    for offset in range(0, len(duplicates), 1000):
        drops.filter(pk__in=duplicates[offset:offset + 1000]).delete()


def restore_foreign_key_index(apps, schema_editor):
    # MySQL can silently replace the original FK index with the unique index.
    # Recreate its support before removing the constraint on rollback.
    if schema_editor.connection.vendor != 'mysql':
        return
    model = apps.get_model('Monsters', 'Item_Monster')
    with schema_editor.connection.cursor() as cursor:
        indexes = schema_editor.connection.introspection.get_constraints(
            cursor, model._meta.db_table)
    if not any(index.get('index') and not index.get('unique') and
               index['columns'] == ['monster_id'] for index in indexes.values()):
        schema_editor.add_index(model, models.Index(
            fields=['monster'], name='monster_drop_fk_restore'))


class Migration(migrations.Migration):
    dependencies = [('Monsters', '0009_delete_buff_skill_monster')]
    operations = [
        migrations.RunPython(remove_duplicate_drops, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='item_monster',
            constraint=models.UniqueConstraint(
                fields=('monster', 'item'), name='unique_monster_item_drop')),
        migrations.RunPython(migrations.RunPython.noop, restore_foreign_key_index, atomic=False),
    ]
