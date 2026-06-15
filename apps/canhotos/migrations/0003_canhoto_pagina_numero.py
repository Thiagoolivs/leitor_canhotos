from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('canhotos', '0002_canhoto_data_recebimento'),
    ]

    operations = [
        migrations.AddField(
            model_name='canhoto',
            name='pagina_numero',
            field=models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='Página (PDF original)'),
        ),
    ]
