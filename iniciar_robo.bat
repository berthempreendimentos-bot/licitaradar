@echo off
echo ==============================================
echo INICIANDO O ROBO DE MENSAGENS (MODO INFINITO)
echo ==============================================
echo O robo rodara a cada 5 minutos.
echo Deixe esta janela aberta.
echo.
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe bot_infinito.py
) else (
    python bot_infinito.py
)
pause
