#!/bin/bash
# Arranca Kodea con el entorno virtual del proyecto.
cd "$(dirname "$0")"
exec .venv/bin/python main.py
