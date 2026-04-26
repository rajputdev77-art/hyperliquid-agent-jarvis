@echo off
REM jarvis — one-click full recovery.
REM Double-click this if anything seems broken.
title jarvis FIX EVERYTHING
color 0B
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0recover.ps1"
