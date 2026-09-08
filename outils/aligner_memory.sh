#!/usr/bin/env bash
# Aligne `feat/memory` sur `feat/harness` — même travail que celui déjà fait sur
# `feat/monitoring`, à lancer APRÈS avoir committé cette dernière.
#
#   1. fusionne feat/harness (aucun conflit attendu : 4 fichiers en commun)
#   2. migre les chemins d'état en dur vers `src/infra/chemins.py`
#   3. laisse tout dans l'index, sans committer
set -euo pipefail
cd "$(dirname "$0")/.."

git switch feat/memory 2>/dev/null || git switch -c feat/memory origin/feat/memory
git merge feat/harness --no-commit --no-ff || {
    echo "CONFLIT — résous-le, puis relance la migration ci-dessous à la main." >&2
    exit 1
}

python - <<'PY'
from pathlib import Path

# `feat/harness` ne porte pas ces trois accesseurs : ils sont nés avec la trace.
ACCESSEURS = """def decisions() -> Path:
    \"\"\"La trace de décision — une ligne par action, `run_id` en clé.\"\"\"
    return etat("decisions.jsonl")


def repere_langfuse() -> Path:
    \"\"\"Jusqu'où l'export Langfuse est monté, pour reprendre sans doublon.\"\"\"
    return etat("langfuse_export.json")


def incidents() -> Path:
    \"\"\"Erreurs déduites de la trace, gardées d'une conversation à l'autre.\"\"\"
    return etat("incidents.jsonl")


"""

_chemins = Path("src/infra/chemins.py")
_s = _chemins.read_text(encoding="utf-8")
if "def decisions()" not in _s and "def memoire_projet()" in _s:
    _chemins.write_text(_s.replace("def memoire_projet()", ACCESSEURS + "def memoire_projet()", 1),
                        encoding="utf-8")
    print("accesseurs ajoutés à chemins.py")

MIGRATIONS = [
    ("src/infra/trace.py",
     'FICHIER = Path.home() / ".axon" / "decisions.jsonl"',
     'FICHIER = _chemins.decisions()'),
    ("src/infra/langfuse_export.py",
     'REPERE = Path.home() / ".axon" / "langfuse_export.json"',
     'REPERE = _chemins.repere_langfuse()'),
    ("src/infra/incident.py",
     'FICHIER = Path.home() / ".axon" / "incidents.jsonl"',
     'FICHIER = _chemins.incidents()'),
]
for fichier, avant, apres in MIGRATIONS:
    p = Path(fichier)
    if not p.exists():
        continue
    t = p.read_text(encoding="utf-8")
    if avant not in t:
        continue
    t = t.replace(avant, apres, 1)
    if "from src.infra import chemins" not in t:
        lignes = t.splitlines(keepends=True)
        i = max(n for n, l in enumerate(lignes) if l.startswith(("import ", "from ")))
        lignes.insert(i + 1, "\nfrom src.infra import chemins as _chemins\n")
        t = "".join(lignes)
    p.write_text(t, encoding="utf-8")
    print(f"migré : {fichier}")
PY

git add -A
echo
echo "Vérification :"
PYTHONPATH=. venv/bin/python -m pytest tests/test_chemins_etat.py -q -p no:cacheprovider | tail -2
echo
echo "Prêt dans l'index. À toi de committer."
