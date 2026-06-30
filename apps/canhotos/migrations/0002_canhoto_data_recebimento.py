from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('canhotos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='canhoto',
            name='data_recebimento',
            field=models.DateField(blank=True, null=True, verbose_name='Data de Recebimento'),
        ),
    ]
