@echo off
cd /d "%~dp0"
echo Installation des dependances...
pip install -r requirements.txt -q
echo.
echo Demarrage du bot Discord...
echo (Ferme cette fenetre pour arreter le bot)
echo.
python bot.py
pause
