#!/bin/bash
set -e

VENV_DIR="venv"

echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "Installing dependencies from requirements.txt..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Setup complete. To activate the environment in your shell:"
echo "  source venv/bin/activate"
