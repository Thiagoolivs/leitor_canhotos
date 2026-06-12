# Notas de Produção - Leitor de Canhotos

Este documento descreve como configurar e executar o sistema em ambiente de produção.

---

## 1. Arquivo de override para produção

Crie um arquivo `docker-compose.prod.yml` (não versionado) que sobrescreve os valores de desenvolvimento:

```yaml
version: '3.9'

services:
  web:
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.base
      - DEBUG=False
      - SECRET_KEY=${SECRET_KEY}
      - ALLOWED_HOSTS=${ALLOWED_HOSTS}
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    command: >
      gunicorn config.wsgi:application
        --bind 0.0.0.0:8000
        --workers 4
        --worker-class sync
        --timeout 120
        --access-logfile -
        --error-logfile -

  celery:
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.base
      - DEBUG=False
      - SECRET_KEY=${SECRET_KEY}
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    command: celery -A config worker -l info -c 4

  monitor:
    environment:
      - DJANGO_SETTINGS_MODULE=config.settings.base
      - DEBUG=False
      - SECRET_KEY=${SECRET_KEY}
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}

  nginx:
    image: nginx:1.25-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - staticfiles:/app/staticfiles:ro
      - media:/app/media:ro
    depends_on:
      - web

volumes:
  staticfiles:
  media:
```

Execute em produção com:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

---

## 2. Variáveis de ambiente obrigatórias em produção

Crie um arquivo `.env` (nunca versione este arquivo) com:

```dotenv
# OBRIGATÓRIO: gere com: python -c "import secrets; print(secrets.token_urlsafe(50))"
SECRET_KEY=<chave-secreta-forte-aqui>

DEBUG=False
ALLOWED_HOSTS=seu-dominio.com.br,www.seu-dominio.com.br

# Banco de dados de produção
DB_NAME=leitor_canhotos_prod
DB_USER=leitor_canhotos
DB_PASSWORD=<senha-forte>
DB_HOST=db
DB_PORT=5432

# Redis de produção (pode usar instância externa)
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# Pastas do scanner
SCANNER_INPUT_DIR=/entrada_canhotos
SCANNER_PROCESSED_DIR=/processados
SCANNER_ERROR_DIR=/erro

# Logs
LOGS_DIR=/app/logs

# Media
MEDIA_ROOT=/app/media
STATIC_ROOT=/app/staticfiles
```

---

## 3. Configurações de segurança para produção

Adicione ao arquivo `config/settings/production.py` (a criar):

```python
from .base import *
from decouple import config

DEBUG = False
ALLOWED_HOSTS = config('ALLOWED_HOSTS', cast=Csv())

# HTTPS security headers
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_SSL_REDIRECT = True  # redireciona HTTP -> HTTPS
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
```

---

## 4. Backup do banco de dados

```bash
# Fazer backup
docker compose exec db pg_dump -U leitor_canhotos leitor_canhotos > backup_$(date +%Y%m%d).sql

# Restaurar backup
docker compose exec -T db psql -U leitor_canhotos leitor_canhotos < backup_YYYYMMDD.sql
```

---

## 5. Rotação de logs

O sistema usa `RotatingFileHandler` configurado em `config/settings/base.py`:
- `leitor_canhotos.log`: até 10 MB, 5 backups
- `errors.log`: apenas erros, até 10 MB, 5 backups

Para rotação adicional via `logrotate` no host:

```
/app/logs/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    sharedscripts
    postrotate
        docker compose exec web kill -USR1 1
    endscript
}
```

---

## 6. Monitoramento de saúde dos serviços

```bash
# Verificar status de todos os containers
docker compose ps

# Verificar healthcheck do banco
docker compose exec db pg_isready -U leitor_canhotos

# Verificar Redis
docker compose exec redis redis-cli ping

# Verificar filas Celery
docker compose exec celery celery -A config inspect active
docker compose exec celery celery -A config inspect stats
```

---

## 7. Atualização do sistema

```bash
# 1. Fazer backup do banco primeiro
docker compose exec db pg_dump -U leitor_canhotos leitor_canhotos > backup_pre_update.sql

# 2. Baixar nova versão
git pull origin main

# 3. Rebuild das imagens
docker compose build

# 4. Reiniciar serviços com zero-downtime (um de cada vez)
docker compose up -d --no-deps web celery monitor

# 5. Aplicar migrações
docker compose exec web python manage.py migrate

# 6. Coletar estáticos
docker compose exec web python manage.py collectstatic --noinput
```

---

## 8. Adicionar nginx ao docker-compose

Para usar o nginx em produção, adicione ao `docker-compose.yml` (ou ao arquivo de override):

```yaml
nginx:
  image: nginx:1.25-alpine
  restart: unless-stopped
  ports:
    - "80:80"
  volumes:
    - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    - staticfiles_volume:/app/staticfiles:ro
    - media_volume:/app/media:ro
  depends_on:
    - web
```

E remova o mapeamento de porta `8000:8000` do serviço `web` (deixe sem `ports:` ou mapeie apenas para o host interno).

---

## 9. Certificado SSL com Let's Encrypt (Certbot)

Para habilitar HTTPS no nginx:

```bash
# Instalar certbot
apt install certbot python3-certbot-nginx

# Obter certificado (substitua pelo seu domínio)
certbot --nginx -d seu-dominio.com.br

# Renovação automática (já configurada pelo certbot)
certbot renew --dry-run
```

Adicione ao `nginx.conf` os blocos para porta 443 com os caminhos do certificado gerados pelo certbot.
