@echo off
REM Orcamento Express Oficina - inicia o sistema (duplo clique neste arquivo)
cd /d "%~dp0"

if not exist ".venv" (
    echo Criando ambiente Python isolado (.venv), so na primeira vez...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Instalando/atualizando dependencias...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

if not exist ".env" (
    echo Nenhum .env encontrado - copiando .env.example como ponto de partida.
    copy .env.example .env >nul
)

echo.
echo Iniciando Orcamento Express Oficina...
echo Feche esta janela para desligar o sistema.
echo.
python app.py

pause
