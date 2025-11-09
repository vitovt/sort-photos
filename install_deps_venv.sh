#!/usr/bin/env bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install pillow python-vlc
python -c "import tkinter" >/dev/null 2>&1 || echo "[!] Tkinter зазвичай входить до системного Python; переконайтесь, що пакет python3-tk встановлено"
