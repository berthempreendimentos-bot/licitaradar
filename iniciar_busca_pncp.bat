@echo off
echo ==============================================
echo INICIANDO BUSCA DE LICITACOES NO PNCP (API)
echo ==============================================
echo Buscando as novas licitacoes nos ultimos 3 dias...
echo.
cd server
node -r dotenv/config src/services/pncpFetcher.js
pause
