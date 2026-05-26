---
name: python
description: Python FastAPI Django pytest mypy venv pip ruff
aliases: [fastapi, django, flask]
---

━━ STACK DÉTECTÉ : PYTHON ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ENVIRONNEMENT :
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt   ou   pip install -e ".[dev]"

QUALITÉ :
   ruff check . && ruff format .   (lint + format — remplace flake8/black)
   mypy .                          (type checking si mypy configuré)

TESTS :
   pytest -x -q                    (arrêt au premier échec)
   pytest --tb=short               (traceback court pour les CI)

AUTH (si API) :
   JWT avec httponly cookies ou headers Authorization: Bearer
   Jamais stocker les tokens dans localStorage.

VÉRIFICATION :
   ruff check . && pytest -x -q
