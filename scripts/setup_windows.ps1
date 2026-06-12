#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Script de instalacao automatica do Leitor de Canhotos para Windows 10.
    Deve ser executado como Administrador no PowerShell.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PROJECT_ROOT = Split-Path -Parent $PSScriptRoot
$REDIS_DIR = "C:\Redis"
$REDIS_VERSION = "3.0.504"
$REDIS_URL = "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip"
$TESSERACT_URL = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.3.3.20231005.exe"
$POPPLER_URL = "https://github.com/oschwartz10612/poppler-windows/releases/download/v24.02.0-0/Release-24.02.0-0.zip"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Write-OK($msg) { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Info($msg) { Write-Host "[..] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[ERRO] $msg" -ForegroundColor Red }

# -- 1. Verify admin --
Write-Step "Verificando privilegios de administrador"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$identity
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Err "Execute este script como Administrador."
    Write-Host "Clique com botao direito no PowerShell -> 'Executar como administrador'"
    exit 1
}
Write-OK "Rodando como administrador"

# -- 2. Set execution policy --
# Ignorado se bloqueado por politica de grupo corporativa (o script ja roda com Bypass)
try {
    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine -Force -ErrorAction Stop
    Write-OK "ExecutionPolicy configurada"
} catch {
    Write-Info "ExecutionPolicy nao alterada (politica de grupo ativa) - sem impacto, continuando..."
}

# -- 3. Install Chocolatey --
Write-Step "Instalando Chocolatey (gerenciador de pacotes)"
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Info "Baixando e instalando Chocolatey..."
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    $env:PATH += ";" + $env:ALLUSERSPROFILE + "\chocolatey\bin"
    Write-OK "Chocolatey instalado"
} else {
    Write-OK "Chocolatey ja instalado"
}

# -- 4. Install Python 3.12 --
Write-Step "Verificando Python 3.12"
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $pyVersion = python --version 2>&1
    Write-OK "Python encontrado: $pyVersion"
} else {
    Write-Info "Instalando Python 3.12 via Chocolatey..."
    choco install python312 -y
    $env:PATH += ";C:\Python312;C:\Python312\Scripts"
    Write-OK "Python 3.12 instalado"
}

# -- 5. Install PostgreSQL 15 --
Write-Step "Verificando PostgreSQL"
$pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue
if ($pgService) {
    Write-OK "PostgreSQL ja instalado (servico: $($pgService.Name))"
} else {
    Write-Info "Instalando PostgreSQL 15 via Chocolatey..."
    choco install postgresql15 --params '/Password:leitor2024' -y
    $env:PATH += ";C:\Program Files\PostgreSQL\15\bin"
    Write-OK "PostgreSQL 15 instalado (senha do postgres: leitor2024)"
}

# -- 6. Create PostgreSQL database --
Write-Step "Criando banco de dados"
$env:PGPASSWORD = "leitor2024"
$pgBin = "C:\Program Files\PostgreSQL\15\bin"
if (Test-Path "$pgBin\psql.exe") {
    Write-Info "Criando usuario e banco leitor_canhotos..."
    & "$pgBin\psql.exe" -U postgres -c "CREATE USER leitor_canhotos WITH PASSWORD 'leitor2024';" 2>$null
    & "$pgBin\psql.exe" -U postgres -c "CREATE DATABASE leitor_canhotos OWNER leitor_canhotos;" 2>$null
    & "$pgBin\psql.exe" -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE leitor_canhotos TO leitor_canhotos;" 2>$null
    Write-OK "Banco de dados configurado"
} else {
    Write-Info "psql nao encontrado em $pgBin, tente adicionar ao PATH manualmente"
}
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

# -- 7. Install Redis for Windows --
Write-Step "Instalando Redis para Windows"
if (-not (Test-Path "$REDIS_DIR\redis-server.exe")) {
    Write-Info "Baixando Redis $REDIS_URL ..."
    $zipPath = "$env:TEMP\redis.zip"
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $REDIS_URL -OutFile $zipPath -UseBasicParsing
    New-Item -ItemType Directory -Path $REDIS_DIR -Force | Out-Null
    Expand-Archive -Path $zipPath -DestinationPath $REDIS_DIR -Force
    Remove-Item $zipPath
    Write-OK "Redis extraido em $REDIS_DIR"
} else {
    Write-OK "Redis ja encontrado em $REDIS_DIR"
}

# -- 8. Install Tesseract OCR --
Write-Step "Instalando Tesseract OCR"
$tesseractPath = "C:\Program Files\Tesseract-OCR\tesseract.exe"
if (-not (Test-Path $tesseractPath)) {
    Write-Info "Instalando Tesseract via Chocolatey..."
    choco install tesseract -y
    Write-OK "Tesseract instalado"
} else {
    Write-OK "Tesseract ja instalado"
}

# Add Tesseract to PATH
$tesseractDir = "C:\Program Files\Tesseract-OCR"
if ($env:PATH -notlike "*Tesseract-OCR*") {
    [Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";$tesseractDir", "Machine")
    $env:PATH += ";$tesseractDir"
    Write-OK "Tesseract adicionado ao PATH"
}

# -- 9. Install Poppler (required by pdf2image) --
Write-Step "Instalando Poppler (necessario para pdf2image)"
$popplerDir = "C:\poppler"
if (-not (Test-Path "$popplerDir\bin\pdftoppm.exe")) {
    Write-Info "Baixando Poppler para Windows..."
    $popplerZip = "$env:TEMP\poppler.zip"
    Invoke-WebRequest -Uri $POPPLER_URL -OutFile $popplerZip -UseBasicParsing
    New-Item -ItemType Directory -Path $popplerDir -Force | Out-Null
    Expand-Archive -Path $popplerZip -DestinationPath "$env:TEMP\poppler_extract" -Force
    # Move contents (poppler release has a subfolder)
    $extractedFolder = Get-ChildItem "$env:TEMP\poppler_extract" | Select-Object -First 1
    Copy-Item "$($extractedFolder.FullName)\*" -Destination $popplerDir -Recurse -Force
    Remove-Item $popplerZip -ErrorAction SilentlyContinue
    Remove-Item "$env:TEMP\poppler_extract" -Recurse -ErrorAction SilentlyContinue
    Write-OK "Poppler extraido em $popplerDir"
} else {
    Write-OK "Poppler ja encontrado"
}
$popplerBin = "$popplerDir\bin"
if ($env:PATH -notlike "*poppler*") {
    [Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";$popplerBin", "Machine")
    $env:PATH += ";$popplerBin"
    Write-OK "Poppler adicionado ao PATH"
}

# -- 10. Create virtual environment --
Write-Step "Criando ambiente virtual Python"
Set-Location $PROJECT_ROOT
if (-not (Test-Path "venv\Scripts\activate.bat")) {
    Write-Info "Criando venv..."
    python -m venv venv
    Write-OK "venv criado"
} else {
    Write-OK "venv ja existe"
}

# -- 11. Install Python dependencies --
Write-Step "Instalando dependencias Python"
Write-Info "Isso pode levar alguns minutos..."
& "venv\Scripts\pip.exe" install --upgrade pip
& "venv\Scripts\pip.exe" install -r requirements.txt
Write-OK "Dependencias instaladas"

# -- 12. Copy .env --
Write-Step "Configurando variaveis de ambiente"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.windows.example" ".env"
    Write-OK ".env criado a partir de .env.windows.example"
    Write-Host ""
    Write-Host "IMPORTANTE: Edite o arquivo .env e ajuste:" -ForegroundColor Yellow
    Write-Host "  - SCANNER_INPUT_DIRS (pasta do scanner, ex: M:\Nota_Fiscal\NF)" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-OK ".env ja existe, nao sobrescrito"
}

# -- 13. Run migrations --
Write-Step "Executando migrations do banco de dados"
& "venv\Scripts\python.exe" manage.py migrate
Write-OK "Migrations aplicadas"

# -- 14. Collect static files --
Write-Step "Coletando arquivos estaticos"
& "venv\Scripts\python.exe" manage.py collectstatic --noinput
Write-OK "Arquivos estaticos coletados"

# -- 15. Create superuser --
Write-Step "Criando superusuario"
Write-Host "Voce sera solicitado a criar o usuario administrador do sistema." -ForegroundColor Yellow
& "venv\Scripts\python.exe" manage.py createsuperuser

# -- Done --
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "   INSTALACAO CONCLUIDA COM SUCESSO!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Para iniciar o sistema, execute:" -ForegroundColor Cyan
Write-Host "   scripts\iniciar_sistema.bat" -ForegroundColor White
Write-Host ""
Write-Host "Acesse o sistema em: http://localhost:8000" -ForegroundColor Cyan
Write-Host "Painel admin em:     http://localhost:8000/admin" -ForegroundColor Cyan
Write-Host ""
