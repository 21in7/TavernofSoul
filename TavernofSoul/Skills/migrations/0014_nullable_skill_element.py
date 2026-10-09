from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('Skills', '0013_alter_skills_is_riding_delete_buff_skill')]
    operations = [migrations.AlterField(
        model_name='skills', name='element',
        field=models.CharField(max_length=30, null=True))]
