# Generated by Django 3.2.9 on 2021-11-16 08:36

from django.db import migrations, models
import django_mysql.models


class Migration(migrations.Migration):

    dependencies = [
        ('Maps', '0006_alter_map_npc_positions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='map_npc',
            name='positions',
            field=django_mysql.models.ListCharField(models.CharField(max_length=700), max_length=5600, size=7),
        ),
    ]