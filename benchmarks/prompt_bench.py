"""Banc de mesure des prompts système — sur les backends réels d'AXON.

Pourquoi il existe : chaque correctif apporté à `BASE_PROMPT` a été validé par un
test unitaire ou à l'œil. Aucun ne répondait à « est-ce que l'agent produit un
meilleur résultat ? ». Sans instrument, une modification de prompt est une opinion.

Inspiré de benchmarks/benchmark-local.py de ponytail (MIT, DietrichGebert/ponytail),
adapté à ce qui compte ici : les backends d'AXON, sa rotation de clés, et le prompt
d'AXON comme sujet de mesure — pas celui de ponytail.

⚠ Ce que ce banc peut et ne peut pas montrer
    Il compare des PROMPTS en génération unique : un prompt, une complétion, on
    compte les lignes de code produites. Il ne mesure PAS une session agentique
    (outils, plan, itérations) — donc pas ce que fait vraiment le specialist.
    Un prompt qui produit moins de lignes n'est meilleur que si le code fait
    encore le travail : `--montrer` existe pour aller le lire.
    ponytail a mesuré que son échelle ne transfère PAS à un petit modèle local
    (llama3.2, 3.2B) : le signal disparaît dans la variance. Sur un modèle plus
    gros, la question est ouverte — d'où ce banc.

Usage :
    python benchmarks/prompt_bench.py --repeat 3
    python benchmarks/prompt_bench.py --backend gemini --repeat 5
    python benchmarks/prompt_bench.py --montrer email actuel   # lire une réponse
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

SORTIE = Path(__file__).parent / "resultats"

# Tâches à piège : chacune a une solution native ou stdlib qu'un modèle
# non contraint remplace par du sur-mesure.
TACHES: list[tuple[str, str]] = [
    ("email", "Écris une fonction Python qui valide une adresse email."),
    ("date-picker", "Ajoute un sélecteur de date à ce formulaire HTML."),
    ("debounce", "Ajoute un debounce sur un champ de recherche en JavaScript. "
                 "Il déclenche actuellement un appel API à chaque frappe."),
    ("csv-sum", "Écris du code Python qui lit ventes.csv et somme la colonne 'montant'."),
    ("cache", "Ajoute un cache aux réponses de cette fonction Python qui appelle une API."),
    ("countdown", "Construis un composant React de compte à rebours à partir d'un nombre "
                  "de secondes donné."),
]


def _bras() -> dict[str, str | None]:
    """Les prompts comparés. `None` = aucun prompt système (le plancher)."""
    from src.agents.coding.prompts import BASE_PROMPT

    bras: dict[str, str | None] = {"aucun": None, "actuel": BASE_PROMPT}
    # Toute variante déposée dans benchmarks/variantes/*.md devient un bras — sauf
    # le README du dossier, qui serait sinon mesuré comme un prompt.
    for fichier in sorted((Path(__file__).parent / "variantes").glob("*.md")):
        if fichier.stem.lower() == "readme":
            continue
        bras[fichier.stem] = fichier.read_text(encoding="utf-8")
    return bras


def compter_lignes(texte: str) -> int:
    """Lignes de code non vides, hors commentaires — blocs clôturés, ou tout le
    texte quand le modèle a répondu sans clôture (fréquent sur petits modèles)."""
    blocs = re.findall(r"```[a-zA-Z0-9_+\-]*\n([\s\S]*?)```", texte)
    lignes = ("\n".join(blocs) if blocs else texte).splitlines()
    return sum(
        1 for l in lignes
        if l.strip() and not l.strip().startswith(("//", "#", "/*", "*", "--"))
    )


def _client(backend: str):
    """Construit un client sur la première clé saine, via le pool d'AXON."""
    from src.llm.key_pool import get_pool
    from src.llm.models import make_coding_llm_with_key

    cle = get_pool().next_healthy(backend) or ""
    if not cle:
        configurees = get_pool().keys_for(backend) or []
        cle = configurees[0] if configurees else ""
    if not cle:
        raise SystemExit(
            f"Aucune clé configurée pour « {backend} ». `/config` dans AXON pour l'état courant."
        )
    return make_coding_llm_with_key(backend, cle)


def _appeler(llm, prompt_systeme: str | None, tache: str) -> tuple[str, float]:
    """Un appel, avec rotation de clé si le quota tombe — le banc ne doit pas
    mourir sur un 429 au milieu de trente appels."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from src.llm import rotation

    messages = ([SystemMessage(content=prompt_systeme)] if prompt_systeme else [])
    messages.append(HumanMessage(content=tache))

    depart = time.time()
    try:
        reponse = llm.invoke(messages)
    except Exception as exc:
        if not rotation.vaut_la_peine_de_reessayer(exc):
            raise
        raise SystemExit(
            f"Quota ou clé morte pendant le banc : {exc}\n"
            "→ relance plus tard, ou `--backend <autre>`."
        )
    contenu = reponse.content
    if isinstance(contenu, list):
        contenu = " ".join(p.get("text", "") if isinstance(p, dict) else str(p)
                           for p in contenu)
    return contenu, round(time.time() - depart, 1)


def executer(backend: str, repetitions: int) -> dict:
    bras = _bras()
    llm = _client(backend)
    brut: dict = {nom: {t: [] for t, _ in TACHES} for nom in bras}
    total = len(bras) * len(TACHES) * repetitions
    fait = 0

    for _ in range(repetitions):
        for nom, systeme in bras.items():
            for tache_id, enonce in TACHES:
                fait += 1
                print(f"[{fait}/{total}] {nom:10s} / {tache_id:12s} …", end=" ", flush=True)
                texte, duree = _appeler(llm, systeme, enonce)
                lignes = compter_lignes(texte)
                brut[nom][tache_id].append(
                    {"lignes": lignes, "secondes": duree, "reponse": texte})
                print(f"{lignes:4d} lignes  {duree}s")
    return brut


def _median(valeurs: list[float]) -> float:
    return statistics.median(valeurs) if valeurs else 0.0


def rapporter(brut: dict, backend: str, repetitions: int) -> None:
    ids = [t for t, _ in TACHES]
    med = {nom: {t: _median([r["lignes"] for r in brut[nom][t]]) for t in ids}
           for nom in brut}
    temps = {nom: sum(_median([r["secondes"] for r in brut[nom][t]]) for t in ids)
             for nom in brut}

    largeur = max(12, max(len(t) for t in ids) + 2)
    entete = f"{'bras':<12}" + "".join(f"{t:>{largeur}}" for t in ids) + f"{'TOTAL':>10}"
    print(f"\n{'=' * len(entete)}")
    print(f"  {backend}  ·  n={repetitions}  ·  médiane des lignes de code")
    print("=" * len(entete))
    print(entete)
    print("-" * len(entete))
    for nom in brut:
        ligne = [med[nom][t] for t in ids]
        print(f"{nom:<12}" + "".join(f"{v:>{largeur}.0f}" for v in ligne)
              + f"{sum(ligne):>10.0f}")

    base = sum(med["aucun"][t] for t in ids)
    print(f"\n  écart au bras « aucun » ({base:.0f} lignes) :")
    for nom in brut:
        if nom == "aucun":
            continue
        somme = sum(med[nom][t] for t in ids)
        pct = (1 - somme / base) * 100 if base else 0
        sens = "de moins" if pct >= 0 else "de PLUS"
        print(f"    {nom:<12} {somme:>6.0f} lignes  ({abs(pct):.0f}% {sens})"
              f"   {temps[nom]:.0f}s cumulées")

    ecarts = []
    for nom in brut:
        for t in ids:
            v = [r["lignes"] for r in brut[nom][t]]
            if len(v) > 1:
                ecarts.append(statistics.pstdev(v) / (statistics.mean(v) or 1))
    if ecarts:
        bruit = 100 * sum(ecarts) / len(ecarts)
        print(f"\n  dispersion moyenne intra-cellule : {bruit:.0f}%")
        if repetitions < 3:
            print("  ⚠ n<3 : aucune conclusion tenable, relance avec --repeat 5.")
        elif bruit > 30:
            print("  ⚠ dispersion supérieure à l'écart mesuré : le signal est dans le bruit.")

    SORTIE.mkdir(parents=True, exist_ok=True)
    chemin = SORTIE / f"{backend}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    chemin.write_text(json.dumps(brut, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  réponses complètes → {chemin}")
    print("  Moins de lignes ne vaut que si le code marche encore :"
          " `--montrer <tâche> <bras>` pour lire.")


def montrer(tache_id: str, bras: str) -> None:
    fichiers = sorted(SORTIE.glob("*.json"))
    if not fichiers:
        raise SystemExit("Aucun résultat enregistré — lance le banc d'abord.")
    brut = json.loads(fichiers[-1].read_text(encoding="utf-8"))
    if bras not in brut or tache_id not in brut[bras]:
        raise SystemExit(f"Inconnu. Bras : {list(brut)} · tâches : {list(brut[bras[0:1] or bras])}")
    for i, essai in enumerate(brut[bras][tache_id], 1):
        print(f"\n──── {bras} / {tache_id} — essai {i} ({essai['lignes']} lignes) ────\n")
        print(essai["reponse"])


def main() -> None:
    from src.infra.settings import settings

    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument("--backend", default=settings.llm_backend,
                         help="fournisseur AXON (défaut : le backend courant)")
    parseur.add_argument("--repeat", type=int, default=3,
                         help="essais par cellule, médiane rapportée (défaut : 3)")
    parseur.add_argument("--montrer", nargs=2, metavar=("TÂCHE", "BRAS"),
                         help="affiche les réponses enregistrées au lieu de mesurer")
    args = parseur.parse_args()

    if args.montrer:
        montrer(*args.montrer)
        return
    rapporter(executer(args.backend, args.repeat), args.backend, args.repeat)


if __name__ == "__main__":
    main()
