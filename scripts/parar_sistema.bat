@echo off
title Leitor de Canhotos - Parando servicos...
echo Encerrando todos os servicos...
taskkill /FI "WINDOWTITLE eq Django - Leitor Canhotos*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Celery Worker*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Monitor Scanner*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Redis*" /F >nul 2>&1
taskkill /IM redis-server.exe /F >nul 2>&1
echo Todos os servicos encerrados.
pause
