@echo off
title Resource Event Discord Bot V4
cd /d "%~dp0"
python -m pip install -r requirements.txt
python bot.py
pause
