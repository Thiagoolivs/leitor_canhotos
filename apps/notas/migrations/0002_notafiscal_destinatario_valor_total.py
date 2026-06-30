from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notas', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='notafiscal',
            name='destinatario',
            field=models.CharField(blank=True, max_length=200, verbose_name='Destinatário'),
        ),
        migrations.AddField(
            model_name='notafiscal',
            name='valor_total',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=15, null=True, verbose_name='Valor Total (R$)'),
        ),
        migrations.AlterField(
            model_name='notafiscal',
            name='data_emissao',
            field=models.DateField(blank=True, null=True, verbose_name='Data de Emissão'),
        ),
    ]
