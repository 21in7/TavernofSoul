# Generated manually for ChallengeModeAutoMap model

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ChallengeModeAutoMap',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('class_id', models.IntegerField(db_index=True, help_text='ClassID', unique=True)),
                ('class_name', models.CharField(db_index=True, help_text='ClassName', max_length=50)),
                ('map_name', models.CharField(db_index=True, help_text='MapName', max_length=100)),
                ('name', models.CharField(help_text='Name (한글 맵 이름)', max_length=200)),
                ('value_str', models.CharField(blank=True, help_text='Value_Str', max_length=200, null=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Challenge Mode Auto Map',
                'verbose_name_plural': 'Challenge Mode Auto Maps',
                'ordering': ['class_id'],
            },
        ),
    ]
