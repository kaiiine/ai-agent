"""Python stack prompt — FastAPI / Django / Flask / scripts."""

PYTHON_PROMPT = """\
━━ STACK : PYTHON ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ENV VIRTUEL   Vérifie d'abord si .venv existe (local_find_file ou shell_ls).
                S'il n'existe pas : shell_run("python -m venv .venv")  ← toujours .venv, jamais venv
                Installe via .venv/bin/pip — JAMAIS pip install global.
                Mets toujours à jour requirements.txt après chaque install.

  VÉRIFICATION  Après modif : exécute le script / les tests, lis la sortie entière.
                python -m py_compile <fichier>   (syntax check rapide)
                pytest -x -q                     (tests)

  QUALITÉ       Annotations de type sur les fonctions publiques.
                ruff check . && ruff format .  (ou black + isort). mypy si configuré.

  BACKEND       Routes → services → repos → schémas/DTOs.
                Auth : JWT + httponly cookies — jamais localStorage.
                Async par défaut. ORM + migrations versionnées. Pydantic / sérialiseurs.
                Intégration : vraie BDD, pas de mock DB.
"""
