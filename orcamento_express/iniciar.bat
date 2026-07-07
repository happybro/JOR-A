@echo off
setlocal enabledelayedexpansion
REM Orcamento Express Oficina - inicia o sistema (duplo clique neste arquivo)
REM Se der problema, este script grava tudo em iniciar_log.txt para diagnostico.
cd /d "%~dp0"

set LOG=iniciar_log.txt
echo ============================================= > "%LOG%"
echo Orcamento Express - log de inicializacao      >> "%LOG%"
echo %DATE% %TIME%                                  >> "%LOG%"
echo ============================================= >> "%LOG%"

echo.
echo Orcamento Express Oficina - iniciando...
echo (log detalhado sendo gravado em iniciar_log.txt)
echo.

REM ---- Descobre o comando Python (python, py -3, ou nenhum) ----
set PY=
where python >nul 2>>"%LOG%"
if !errorlevel! == 0 (
    set PY=python
) else (
    where py >nul 2>>"%LOG%"
    if !errorlevel! == 0 (
        set PY=py -3
    )
)

if "!PY!"=="" (
    echo.
    echo [ERRO] Nao encontrei o Python instalado neste computador.
    echo.
    echo Instale o Python 3 antes de continuar:
    echo   https://www.python.org/downloads/
    echo IMPORTANTE: na tela de instalacao, marque a caixa
    echo   "Add Python to PATH" antes de clicar em Install.
    echo.
    echo Depois de instalar, feche esta janela e clique de novo em iniciar.bat.
    echo. >> "%LOG%"
    echo ERRO: python e py nao encontrados no PATH. >> "%LOG%"
    pause
    exit /b 1
)

echo Usando: !PY! ( versao encontrada abaixo )
!PY! --version
echo Comando Python usado: !PY! >> "%LOG%"
!PY! --version >> "%LOG%" 2>&1

REM ---- Cria o ambiente virtual, se ainda nao existir ----
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo Criando ambiente Python isolado ^(.venv^), so na primeira vez...
    !PY! -m venv .venv >> "%LOG%" 2>&1
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo [ERRO] Nao consegui criar o ambiente virtual .venv
        echo Veja o arquivo iniciar_log.txt para detalhes e me envie o conteudo.
        pause
        exit /b 1
    )
)

REM ---- A partir daqui, chama sempre o python de dentro do .venv ----
set VENV_PY=.venv\Scripts\python.exe

echo.
echo Instalando/atualizando dependencias ^(pode demorar na primeira vez^)...
"%VENV_PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%VENV_PY%" -m pip install -r requirements.txt >> "%LOG%" 2>&1
if !errorlevel! neq 0 (
    echo.
    echo [ERRO] Falha ao instalar as dependencias.
    echo Abra o arquivo iniciar_log.txt, copie o erro e me envie.
    pause
    exit /b 1
)

if not exist ".env" (
    echo Nenhum .env encontrado - copiando .env.example como ponto de partida.
    copy .env.example .env >nul
)

echo.
echo Tudo pronto! Iniciando o servidor...
echo Depois de abrir, acesse no navegador: http://localhost:5055
echo Feche esta janela para desligar o sistema.
echo.
"%VENV_PY%" app.py
if !errorlevel! neq 0 (
    echo.
    echo [ERRO] O programa fechou com erro. Veja iniciar_log.txt e logs\app.log.
)

echo.
pause
