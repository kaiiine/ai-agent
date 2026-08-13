"""Aucun credential ne doit vivre dans le dépôt.

Un jeton committé ne se retire pas : même supprimé, il reste dans l'historique
git, dans les forks, dans les caches. La seule protection qui tienne est de ne
jamais l'y mettre — ce que ce test vérifie à chaque exécution plutôt qu'à chaque
relecture.

Portée : les fichiers SUIVIS par git. Le répertoire de travail peut contenir des
`.env` non suivis, et c'est leur place ; ce qui compte est ce qui part au commit.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

#: Motifs de jetons, reconnaissables à leur PRÉFIXE. On ne cherche pas « une
#: longue chaîne » : les empreintes sha256, les identifiants de fixtures et les
#: clés de cache y ressembleraient, et un test qui crie au loup finit ignoré.
MOTIFS = {
    "jeton Kaggle": re.compile(r"\bKGAT_[A-Za-z0-9]{16,}"),
    "clé AWS": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "jeton GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "clé OpenAI": re.compile(r"\bsk-[A-Za-z0-9]{32,}"),
    "clé Anthropic": re.compile(r"\bsk-ant-[A-Za-z0-9\-]{32,}"),
    "clé privée": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}

#: Extensions lues. Le binaire est exclu : une fixture `.csv.gz` ne contient pas
#: de jeton en clair, et la décompresser à chaque exécution coûterait des minutes.
EXTENSIONS = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg",
              ".ini", ".sh", ".env", ".example"}

#: Fichiers dont le MÉTIER est de reconnaître des secrets : ils en portent les
#: motifs par construction. Les exclure n'ouvre aucune brèche — un vrai jeton s'y
#: verrait à la relecture, puisqu'ils ne contiennent que des expressions
#: régulières. Les inclure produirait une alerte permanente, et une alerte
#: permanente finit par être ignorée, ce qui coûterait la vraie détection.
EXCLUS = {
    "tests/test_aucun_secret_dans_le_depot.py",   # ce fichier
    "src/infra/redactor.py",                      # caviarde les secrets sortants
}


def _fichiers_suivis() -> list[str]:
    sortie = subprocess.run(["git", "ls-files", "-z"], cwd=RACINE,
                            capture_output=True, text=True, check=True).stdout
    return [f for f in sortie.split("\0") if f]


@pytest.fixture(scope="module")
def suivis() -> list[Path]:
    return [RACINE / f for f in _fichiers_suivis()
            if f not in EXCLUS and Path(f).suffix in EXTENSIONS]


def test_aucun_jeton_dans_les_fichiers_suivis(suivis):
    """Un jeton committé est un jeton à révoquer, pas à supprimer."""
    trouves = []
    for chemin in suivis:
        try:
            contenu = chemin.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for nom, motif in MOTIFS.items():
            if motif.search(contenu):
                trouves.append(f"{nom} dans {chemin.relative_to(RACINE)}")
    assert not trouves, "credentials dans le dépôt :\n  " + "\n  ".join(trouves)


def test_le_jeton_kaggle_ne_se_lit_que_dans_l_environnement(monkeypatch):
    """Kaggle lit aussi `~/.kaggle/access_token` — un fichier du répertoire
    personnel finit copié, sauvegardé, ou pris par un `git add .` distrait."""
    from src.agents.quant.historical_discovery.adapters import kaggle_tennis as kt

    monkeypatch.delenv(kt.VARIABLE_JETON, raising=False)
    assert not kt.jeton_disponible()
    with pytest.raises(RuntimeError) as erreur:
        kt.exiger_jeton()
    # Le message NOMME la variable et ne montre aucune valeur.
    assert kt.VARIABLE_JETON in str(erreur.value)

    monkeypatch.setenv(kt.VARIABLE_JETON, "KGAT_valeurfactice0123456789")
    assert kt.jeton_disponible()
    assert kt.exiger_jeton() == "KGAT_valeurfactice0123456789"


def test_aucun_chemin_de_jeton_en_dur_dans_le_code_kaggle():
    """`~/.kaggle/access_token` ne doit apparaître nulle part comme source de
    lecture : le mentionner en commentaire pour l'écarter est acceptable,
    l'ouvrir ne l'est pas."""
    import inspect

    from src.agents.quant.historical_discovery.adapters import kaggle_tennis as kt

    source = inspect.getsource(kt)
    for interdit in ("open(", "read_text(", "Path.home()", "expanduser"):
        assert interdit not in source, interdit


def test_les_fixtures_de_backfill_portent_leur_licence():
    """La clause d'attribution voyage avec les données ou elle se perd."""
    avis = RACINE / "tests" / "fixtures" / "tennis" / "LICENCE-BACKFILL.md"
    assert avis.exists()
    texte = avis.read_text(encoding="utf-8")
    for attendu in ("CC BY-NC-SA", "Jeff Sackmann", "Taylor Brownlow",
                    "NonCommercial", "ShareAlike"):
        assert attendu in texte, attendu
