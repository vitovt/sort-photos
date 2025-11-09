@echo off
setlocal

where python >nul 2>&1
if errorlevel 1 (
  echo Python 3 не знайдено. Встановіть з https://www.python.org/downloads/ і повторіть.
  exit /b 1
)

py -m pip install --upgrade pip
py -m pip install pillow python-vlc

where vlc >nul 2>&1
if errorlevel 1 (
  echo [!] VLC не знайдено у PATH. Встановіть VLC Media Player для повного функціоналу відео.
)

echo Залежності встановлено. Запускайте: py sort-photos.py ...
