@echo off
chcp 65001 >nul
title Leitor de Canhotos - Iniciando...

echo.
echo ============================================================
echo   LEITOR DE CANHOTOS - Iniciando servicos...
echo ============================================================
echo.

cd /d "%~dp0.."

REM Check venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERRO] Ambiente virtual nao encontrado.
    echo Execute: python -m venv venv
    pause
    exit /b 1
)

REM Check .env exists
if not exist ".env" (
    echo [ERRO] Arquivo .env nao encontrado.
    echo Copie .env.windows.example para .env e configure.
    pause
    exit /b 1
)

echo [1/4] Iniciando Redis...
start "Redis" cmd /k "C:\Redis\redis-server.exe C:\Redis\redis.windows.conf"
timeout /t 2 /nobreak >nul

echo [2/4] Iniciando Django...
start "Django - Leitor Canhotos" cmd /k "call venv\Scripts\activate.bat && python manage.py runserver 0.0.0.0:8000"
timeout /t 3 /nobreak >nul

echo [3/4] Iniciando Celery...
start "Celery Worker" cmd /k "call venv\Scripts\activate.bat && celery -A config worker --pool=solo -l info"
timeout /t 2 /nobreak >nul

echo [4/4] Iniciando Monitor de Scanner...
start "Monitor Scanner" cmd /k "call venv\Scripts\activate.bat && python monitoring\scanner_monitor.py"

echo.
echo ============================================================
echo   Sistema iniciado com sucesso!
echo   Acesse: http://localhost:8000
echo   Admin:  http://localhost:8000/admin
echo ============================================================
echo.
echo Para PARAR todos os servicos, execute: parar_sistema.bat
echo.
pause
