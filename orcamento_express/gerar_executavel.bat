@echo off
REM Gera um executavel standalone (OrcamentoExpress.exe) usando PyInstaller.
REM Rode este .bat NO WINDOWS da oficina (nao funciona em outro sistema).
REM Depois de gerar, copie a pasta dist\ inteira para onde quiser rodar.
cd /d "%~dp0"

if not exist ".venv" (
    echo Criando ambiente Python isolado (.venv)...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Instalando dependencias (inclusive PyInstaller)...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
python -m pip install --quiet pyinstaller

echo.
echo Gerando OrcamentoExpress.exe (isso pode levar alguns minutos)...
pyinstaller --onefile --name OrcamentoExpress ^
    --add-data "templates;templates" ^
    --add-data "static;static" ^
    --add-data "ficha_templates;ficha_templates" ^
    app.py

if not exist "dist\.env" (
    if exist ".env" (
        copy ".env" "dist\.env" >nul
    ) else (
        copy ".env.example" "dist\.env" >nul
    )
)

echo.
echo Pronto! O executavel esta em dist\OrcamentoExpress.exe
echo Copie a pasta "dist" inteira (com o .env junto) para onde quiser usar.
echo Na primeira execucao, o programa cria as pastas uploads, processed,
echo pdfs, logs, data e ficha_templates ao lado do .exe automaticamente.
pause
