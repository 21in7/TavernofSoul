from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Dashboard', '0002_rename_version_name_version_version'),
    ]

    operations = [
        migrations.AlterField(
            model_name='version',
            name='version',
            field=models.CharField(max_length=50, unique=True),
        ),
    ]
