"""Python stack prompt — FastAPI / Django / Flask / scripts."""

PYTHON_PROMPT = """\
━━ STACK DÉTECTÉ : PYTHON ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING (nouveau projet) :
   uv init <nom>              (préféré)
   django-admin startproject <nom>
   python -m venv venv && pip install -r requirements.txt

DÉPENDANCES :
   • uv (préféré) : uv add <pkg>, uv sync
   • Sinon pip : pip install <pkg> puis ajouter à requirements.txt

QUALITÉ :
   • Annotations de type complètes sur toutes les fonctions publiques.
   • ruff check . && ruff format .    (ou black + isort)
   • mypy . si configuré.

BACKEND (FastAPI / Django / Flask) :
   • Architecture : routes/views → services/use-cases → repos/DAL → schemas/DTOs
   • Auth : JWT + httponly cookies ou sessions — jamais localStorage.
   • BDD : ORM avec migrations versionnées, transactions multi-tables.
   • Validation : Pydantic (FastAPI), Django forms/serializers, WTForms.
   • Async : handlers async par défaut, pas de blocking I/O.

TESTS :
   • pytest + fixtures scopées correctement.
   • Coverage > 80% sur le code métier.
   • Intégration : vraie BDD, pas de mock DB.

VÉRIFICATION :
   pytest                           (tests complets)
   python -m py_compile <fichier>   (fichier isolé rapide)
   ruff check . && ruff format --check .
"""
