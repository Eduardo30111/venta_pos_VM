#!/bin/bash
# Lanzador de VmPOS - usa Miniconda para Tk 9.0 compatible con macOS
export PATH="$HOME/miniconda3/bin:$PATH"
cd "$(dirname "$0")"
export PYTHONPATH="$PWD:$PWD/interface${PYTHONPATH:+:$PYTHONPATH}"
python3 interface/inicio_sesion.py
