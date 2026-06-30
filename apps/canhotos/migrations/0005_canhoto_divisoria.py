from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('canhotos', '0004_canhoto_barcode_confianca'),
    ]

    operations = [
        migrations.AddField(
            model_name='canhoto',
            name='tipo_pagina',
            field=models.CharField(
                choices=[
                    ('CANHOTO', 'Canhoto'),
                    ('DIVISORIA', 'Folha Divisória'),
                    ('DIVISORIA_MISTA', 'Divisória com Canhotos'),
                ],
                default='CANHOTO',
                max_length=20,
                verbose_name='Tipo de Página',
            ),
        ),
        migrations.AddField(
            model_name='canhoto',
            name='numeros_lista',
            field=models.TextField(
                blank=True,
                help_text='Lista de números sequenciais detectados em uma folha divisória.',
                verbose_name='Números detectados na divisória',
            ),
        ),
        migrations.AlterField(
            model_name='canhoto',
            name='status_processamento',
            field=models.CharField(
                choices=[
                    ('PENDENTE', 'Pendente'),
                    ('PROCESSANDO', 'Processando'),
                    ('SUCESSO', 'Sucesso'),
                    ('ERRO', 'Erro'),
                    ('REVISAO', 'Revisão Manual'),
                ],
                default='PENDENTE',
                max_length=20,
                verbose_name='Status de Processamento',
            ),
        ),
    ]
