# Instalação Windows Nativo (sem Docker)

## Pré-requisitos
- Windows 10 (64-bit)
- 4 GB de RAM
- Permissão de Administrador
- Conexão com internet

---

## Opção A — Instalação Automática (Recomendada)

### Passo 1 — Baixar o projeto

```powershell
# No PowerShell, navegue até onde quer instalar
cd C:\
git clone https://github.com/Thiagoolivs/leitor_canhotos.git
cd leitor_canhotos
```

Se não tiver Git:
- Baixe em https://git-scm.com/download/win
- Ou baixe o ZIP diretamente do GitHub e extraia em `C:\leitor_canhotos`

### Passo 2 — Executar o script de instalação

Abra o PowerShell **como Administrador**:
1. Pressione `Win + X`
2. Clique em **"Windows PowerShell (Admin)"** ou **"Terminal (Admin)"**
3. Execute:

```powershell
cd C:\leitor_canhotos
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

O script instala automaticamente:
- Python 3.12
- PostgreSQL 15
- Redis para Windows
- Tesseract OCR
- Poppler (conversor de PDF)
- Todas as dependências Python

### Passo 3 — Configurar pasta do scanner

Edite o arquivo `.env` que foi criado:
```
SCANNER_INPUT_DIRS=M:\Nota_Fiscal\NF
```
Ajuste para o caminho real onde o scanner salva os arquivos.

### Passo 4 — Iniciar o sistema

```bat
scripts\iniciar_sistema.bat
```

Isso abre 4 janelas:
- **Redis** — banco de cache/fila
- **Django** — servidor web
- **Celery** — processador de tarefas (OCR)
- **Monitor** — vigia a pasta do scanner

### Passo 5 — Acessar

- Sistema: http://localhost:8000
- Admin: http://localhost:8000/admin

---

## Opção B — Instalação Manual

### 1. Python 3.12
Baixe em: https://www.python.org/downloads/
Durante a instalação, marque **"Add Python to PATH"**

### 2. PostgreSQL 15
Baixe em: https://www.enterprisedb.com/downloads/postgres-postgresql-downloads
- Senha do postgres: `leitor2024`
- Porta: `5432`

Após instalar, abra o pgAdmin ou SQL Shell e execute:
```sql
CREATE USER leitor_canhotos WITH PASSWORD 'leitor2024';
CREATE DATABASE leitor_canhotos OWNER leitor_canhotos;
GRANT ALL PRIVILEGES ON DATABASE leitor_canhotos TO leitor_canhotos;
```

### 3. Redis para Windows
Baixe o ZIP em: https://github.com/tporadowski/redis/releases
Extraia em `C:\Redis\`

### 4. Tesseract OCR
Baixe o instalador em: https://github.com/UB-Mannheim/tesseract/wiki
Execute o instalador, anote o caminho de instalação (padrão: `C:\Program Files\Tesseract-OCR`)

### 5. Poppler
Baixe em: https://github.com/oschwartz10612/poppler-windows/releases
Extraia em `C:\poppler\`
Adicione `C:\poppler\bin` ao PATH do Windows

### 6. Clonar e configurar

```powershell
git clone https://github.com/Thiagoolivs/leitor_canhotos.git
cd leitor_canhotos
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.windows.example .env
# Edite o .env com suas configurações
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### 7. Iniciar serviços manualmente

Abra 4 janelas PowerShell separadas:

**Janela 1 — Redis:**
```powershell
C:\Redis\redis-server.exe
```

**Janela 2 — Django:**
```powershell
cd C:\leitor_canhotos
venv\Scripts\activate
python manage.py runserver 0.0.0.0:8000
```

**Janela 3 — Celery:**
```powershell
cd C:\leitor_canhotos
venv\Scripts\activate
celery -A config worker --pool=solo -l info
```

**Janela 4 — Monitor:**
```powershell
cd C:\leitor_canhotos
venv\Scripts\activate
python monitoring\scanner_monitor.py
```

---

## Atualizar o sistema

```powershell
cd C:\leitor_canhotos
git pull
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
```

Depois reinicie os serviços com `scripts\iniciar_sistema.bat`.

---

## Problemas Comuns

### "tesseract is not installed or it's not in your PATH"
Adicione manualmente ao PATH:
1. `Win + R` → `sysdm.cpl`
2. Avançado → Variáveis de Ambiente
3. Em "Variáveis do Sistema", selecione `Path` → Editar
4. Adicione: `C:\Program Files\Tesseract-OCR`

### "Unable to connect to Redis"
Verifique se o Redis está rodando:
```powershell
C:\Redis\redis-cli.exe ping
# Deve retornar: PONG
```

### "could not connect to server: Connection refused (PostgreSQL)"
Verifique se o serviço está rodando:
```powershell
Get-Service postgresql*
Start-Service postgresql-x64-15
```

### Pasta do scanner não está sendo monitorada
Verifique se o caminho no `.env` está correto:
```
SCANNER_INPUT_DIRS=M:\Nota_Fiscal\NF
```
A pasta deve existir. Crie-a se necessário.

### Celery trava no Windows com multiprocessing
Certifique-se de usar `--pool=solo`:
```powershell
celery -A config worker --pool=solo -l info
```
Isso já está configurado no `iniciar_sistema.bat`.

---

## Para parar o sistema

```bat
scripts\parar_sistema.bat
```
