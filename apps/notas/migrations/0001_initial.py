from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='NotaFiscal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('numero', models.CharField(max_length=50, unique=True, verbose_name='Número')),
                ('data_emissao', models.DateField(verbose_name='Data de Emissão')),
                ('categoria', models.CharField(blank=True, max_length=100, verbose_name='Categoria')),
                ('status', models.CharField(
                    choices=[
                        ('AGUARDANDO_CANHOTO', 'Aguardando Canhoto'),
                        ('FINALIZADO', 'Finalizado'),
                        ('ERRO', 'Erro'),
                    ],
                    default='AGUARDANDO_CANHOTO',
                    max_length=30,
                    verbose_name='Status',
                )),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
            ],
            options={
                'verbose_name': 'Nota Fiscal',
                'verbose_name_plural': 'Notas Fiscais',
                'ordering': ['-created_at'],
            },
        ),
    ]
