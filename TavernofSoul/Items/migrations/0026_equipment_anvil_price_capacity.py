from django.db import migrations, models
from django_mysql.models import ListCharField


class Migration(migrations.Migration):
    dependencies = [('Items', '0025_reinforcement_and_gem_bonuses')]
    operations = [migrations.AlterField(
        model_name='equipments', name='anvil_price',
        field=ListCharField(base_field=models.IntegerField(), size=41,
                            max_length=5000, blank=True, null=True))]
