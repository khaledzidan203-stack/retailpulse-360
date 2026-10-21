@echo off
py -3.13 "%~dp0tools\start_portfolio.py"
if errorlevel 1 pause
