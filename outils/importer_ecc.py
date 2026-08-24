"""Convertit un agent ECC en skill Axon.

ECC (MIT, github.com/affaan-m/ECC) décrit ses agents dans un frontmatter très
proche de celui d'Axon — d'où la conversion mécanique :

    ECC                          Axon
    name:        →  name:        identique
    description: →  description: identique, c'est ce qui est INDEXÉ
    tools:       →  scope:       traduit ; ECC nomme des outils Claude Code
    model:       →  (retiré)     Axon choisit son backend, pas le skill

Pourquoi un LOT à la fois, et pas les 68 d'un coup
──────────────────────────────────────────────────
Mesuré sur ce dépôt : ajouter UN seul skill mal cadré a fait tomber un test de
routage — son texte élargissait le document du groupe `coding`, et « montre-moi
le dernier commit » s'est mis à proposer `run_coding_agent`. Mesuré aussi : les
ancres d'un seul skill ont fait passer la recherche de 10/10 à 9/10.

Verser 68 skills en bloc, c'est la certitude de casser le routage sans savoir
lequel en est la cause. Ce script importe donc un lot nommé, et le jeu de
référence se relance après chaque lot.

Le `scope` par défaut est `coding` — délibérément. Une portée `orchestrator`
verse le texte du skill dans le corpus de routage des GROUPES d'outils, ce qui
est exactement ce qui a cassé le test cité plus haut.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ECC = Path.home() / "Documents" / "projets-perso" / "ECC" / "agents"
SKILLS = Path(__file__).resolve().parent.parent / "skills"

_FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _decouper(texte: str) -> tuple[dict, str]:
    m = _FRONT.match(texte)
    if not m:
        return {}, texte
    meta = {}
    for ligne in m.group(1).splitlines():
        if ":" in ligne:
            k, v = ligne.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, texte[m.end():]


def convertir(source: Path, scope: str = "coding") -> tuple[str, str]:
    """Rend (nom, contenu du skill Axon)."""
    meta, corps = _decouper(source.read_text(encoding="utf-8"))
    nom = meta.get("name") or source.stem
    desc = meta.get("description", "").strip().strip('"')

    # La description est ce qu'Axon INDEXE pour la recherche sémantique. Celles
    # d'ECC sont écrites pour le RÉPARTITEUR de Claude Code, pas pour décrire un
    # domaine — « MUST BE USED for Python projects », « Use PROACTIVELY after
    # writing code », « Use for all code changes ».
    #
    # Mesuré : importées telles quelles, ces injonctions dominent l'index.
    # `python-reviewer` (184 caractères, contenant « security » et
    # « performance ») captait « audite la sécurité de ce code » ET « relis ce
    # fichier typescript » — trois skills sur quatre devenaient inatteignables.
    #
    # On ne garde donc que la PREMIÈRE phrase, celle qui décrit le domaine. Les
    # injonctions n'ont pas d'équivalent chez Axon : c'est `load_skill` qui dit
    # quand consulter un skill, pas le skill lui-même.
    phrases = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", desc).strip())
    utiles = [ph for ph in phrases
              if not re.search(r"\b(MUST BE USED|Use PROACTIVELY|Use immediately|"
                               r"Use for all|Proactively|Invoke|Trigger)\b", ph, re.I)]
    desc = " ".join(utiles[:2]).strip() or (phrases[0] if phrases else nom)

    entete = [f"name: {nom}", f"description: {desc}", f"scope: {scope}"]
    origine = ("<!-- Importé de ECC (MIT) — github.com/affaan-m/ECC\n"
               f"     source : agents/{source.name}\n"
               "     `tools:` et `model:` du frontmatter d'origine retirés : ils\n"
               "     nomment des outils Claude Code, et Axon choisit son backend\n"
               "     lui-même. -->\n")
    return nom, "---\n" + "\n".join(entete) + "\n---\n\n" + origine + "\n" + corps.lstrip()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("agents", nargs="+", help="noms d'agents ECC, sans .md")
    p.add_argument("--scope", default="coding")
    p.add_argument("--source", type=Path, default=ECC)
    p.add_argument("--dest", type=Path, default=SKILLS)
    p.add_argument("--simuler", action="store_true", help="n'ecrit rien")
    args = p.parse_args()

    ecrits, ignores = [], []
    for nom in args.agents:
        src = args.source / f"{nom}.md"
        if not src.exists():
            print(f"  introuvable : {src}", file=sys.stderr)
            continue
        cible_nom, contenu = convertir(src, args.scope)
        cible = args.dest / f"{cible_nom}.md"
        if cible.exists():
            ignores.append(f"{cible_nom} (existe deja)")
            continue
        if not args.simuler:
            cible.write_text(contenu, encoding="utf-8")
        ecrits.append(f"{cible_nom}  ({len(contenu):,} car.)")

    for e in ecrits:
        print(f"  {'(simule) ' if args.simuler else ''}ecrit : {e}")
    for i in ignores:
        print(f"  ignore : {i}")
    print(f"\n  {len(ecrits)} skill(s) - relance le jeu de reference de routage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
