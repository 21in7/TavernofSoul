from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('Monsters', '0010_unique_monster_item_drop')]
    operations = [migrations.AlterField(
        model_name='skill_monster', name='sfr',
        field=models.FloatField(blank=True, null=True))]
