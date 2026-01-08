@echo off
echo.
echo ====================================
echo   Nettoyage VRAM et relance
echo ====================================
echo.

echo Arret d'Ollama...
taskkill /F /IM ollama.exe 2>nul
taskkill /F /IM ollama_llama_server.exe 2>nul

timeout /t 3 /nobreak >nul

echo Redemarrage d'Ollama...
start "" ollama serve

timeout /t 5 /nobreak >nul

echo.
echo Verification VRAM...
nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader

echo.
echo Lancement en mode SEQUENTIEL (plus stable)...
echo.

python wama_feature_extractor.py --screenshots ui_screenshots --mode sequential --output results

echo.
echo Termine !
pause