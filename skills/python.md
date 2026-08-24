---
name: python
description: Builds and scaffolds Python projects from scratch: FastAPI, Django, Flask, pytest, mypy, venv, pip, ruff. Use when writing new Python code.
aliases: [fastapi, django, flask]
---

━━ STACK DÉTECTÉ : PYTHON ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   uv venv && source .venv/bin/activate       (uv si présent — 10× plus rapide)
   python -m venv .venv && source .venv/bin/activate     (repli standard)
   Vérifier ce que le projet utilise AVANT de choisir : uv.lock, poetry.lock,
   requirements.txt ou pyproject.toml. Ne jamais introduire un gestionnaire que
   le dépôt n'utilise pas.

   Projet neuf → pyproject.toml, jamais setup.py :
      [project]  name, version, dependencies
      [project.optional-dependencies]  dev = ["pytest", "ruff", "mypy"]

DISPOSITION :
   src/<paquet>/        le code (layout src/, pas de paquet à la racine)
   tests/               les tests, hors du paquet livré
   pyproject.toml       dépendances + config ruff/mypy/pytest

FASTAPI :
   uvicorn app.main:app --reload
   • Un routeur par domaine : APIRouter(prefix="/users", tags=["users"])
     inclus dans main.py par app.include_router(...). Jamais tout dans main.py.
   • Pydantic v2 : BaseModel pour l'entrée ET la sortie, response_model= sur
     chaque route. model_validate / model_dump — plus de .dict() ni .parse_obj().
   • Dépendances par Depends() : session DB, utilisateur courant, réglages.
     Une session par requête, fermée par le yield de la dépendance.
   • def bloquant dans une route async = event loop gelé. Soit la route est
     `def` (FastAPI la passe au threadpool), soit tout ce qu'elle appelle est
     async. Ne jamais mélanger.

DJANGO :
   django-admin startproject <projet> . && python manage.py startapp <app>
   • Réglages découpés : settings/base.py + dev.py + prod.py, jamais un fichier
     unique avec des if DEBUG.
   • Migrations : makemigrations puis migrate — les relire avant de committer,
     une migration générée peut supprimer une colonne sans le dire.
   • select_related / prefetch_related sur toute boucle qui traverse une
     relation, sinon N+1 requêtes.
   • Jamais SECRET_KEY ni identifiants en dur : os.environ, avec un défaut qui
     échoue bruyamment en prod.

FLASK :
   • Fabrique d'application : create_app() qui renvoie l'app, blueprints
     enregistrés dedans. Pas d'app globale au niveau module.
   • Extensions initialisées en deux temps : db = SQLAlchemy() au module,
     db.init_app(app) dans la fabrique.

QUALITÉ :
   ruff check --fix . && ruff format .    (lint + format — remplace flake8/black)
   mypy .                                 (si mypy est configuré dans le projet)

TESTS :
   pytest -x -q                    (arrêt au premier échec)
   pytest --tb=short               (traceback court pour les CI)
   pytest -k "<motif>"             (cibler pendant le développement)
   • Fixtures dans conftest.py, pas d'état partagé entre tests.
   • Une base de test jetable, jamais la base de développement.

AUTH (si API) :
   JWT en cookie httponly, ou header Authorization: Bearer.
   Jamais stocker les tokens dans localStorage.
   Mots de passe : passlib/bcrypt — jamais de hash maison, jamais de sha256 nu.

PIÈGES :
   • Argument par défaut mutable : def f(x=[]) partage la liste entre appels.
   • except: nu ou except Exception: pass — avale les erreurs. Attraper précis,
     et relancer ou journaliser.
   • Import circulaire : signe qu'un module fait deux choses, pas qu'il faut
     déplacer l'import dans la fonction.

VÉRIFICATION :
   ruff check . && mypy . && pytest -x -q
