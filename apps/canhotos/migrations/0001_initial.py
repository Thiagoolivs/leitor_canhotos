from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('notas', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Canhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('arquivo', models.FileField(upload_to='canhotos/', verbose_name='Arquivo')),
                ('numero_detectado', models.CharField(blank=True, max_length=50, verbose_name='Número Detectado pelo OCR')),
                ('status_processamento', models.CharField(
                    choices=[
                        ('PENDENTE', 'Pendente'),
                        ('PROCESSANDO', 'Processando'),
                        ('SUCESSO', 'Sucesso'),
                        ('ERRO', 'Erro'),
                    ],
                    default='PENDENTE',
                    max_length=20,
                    verbose_name='Status de Processamento',
                )),
                ('nota', models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='canhoto',
                    to='notas.notafiscal',
                    verbose_name='Nota Fiscal Vinculada',
                )),
                ('texto_ocr', models.TextField(blank=True, verbose_name='Texto Extraído pelo OCR')),
                ('erro_mensagem', models.TextField(blank=True, verbose_name='Mensagem de Erro')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
            ],
            options={
                'verbose_name': 'Canhoto',
                'verbose_name_plural': 'Canhotos',
                'ordering': ['-created_at'],
            },
        ),
    ]
