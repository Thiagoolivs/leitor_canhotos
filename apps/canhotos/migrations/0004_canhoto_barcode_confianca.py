from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('canhotos', '0003_canhoto_pagina_numero'),
    ]

    operations = [
        migrations.AddField(
            model_name='canhoto',
            name='numero_barcode',
            field=models.CharField(blank=True, max_length=50, verbose_name='Número via Código de Barras'),
        ),
        migrations.AddField(
            model_name='canhoto',
            name='confianca_deteccao',
            field=models.CharField(
                blank=True,
                choices=[('ALTA', 'Alta'), ('MEDIA', 'Média'), ('BAIXA', 'Baixa')],
                max_length=5,
                verbose_name='Confiança da Detecção',
            ),
        ),
    ]
