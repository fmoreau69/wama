@echo off
echo.
echo ====================================
echo   WAMA - Analyse UI
echo ====================================
echo.
echo Demarrage de l'analyse...
echo Cela prendra environ 15-20 minutes
echo.

python wama_feature_extractor.py --screenshots ui_screenshots --mode parallel --output results

echo.
echo ====================================
echo   Termine !
echo ====================================
echo.
echo Resultats dans: results\
echo.

explorer results

pause