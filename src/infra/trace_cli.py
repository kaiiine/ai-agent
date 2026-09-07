"""`axon trace` — relire la trace de décision au lieu de la remesurer à la main.

C'est la moitié utile du chantier : un journal que personne ne sait relire ne
remplace pas la mesure manuelle, il s'y ajoute. Les trois vues correspondent aux
trois questions qui ont été reposées à la main cette semaine.

    axon trace                     les derniers tours, action par action
    axon trace <run_id>            un tour en entier
    axon trace --route             quel groupe gagne, et à quel rang
    axon trace --outils            ce que chaque outil rend, et en combien de temps
    axon trace --erreurs           ce qui a raté, compté par outil et par cible
    axon trace --export-langfuse   pousser vers un Langfuse auto-hébergé

`--route` porte la mesure que `graph.py` réclamait en commentaire : le taux de
rattrapage au catalogue. C'est LUI qui dira jusqu'où la sélection peut être
resserrée — un filet qui sert souvent dit que le budget est trop bas, un filet
qui ne sert jamais dit qu'il peut baisser encore.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from rich.console import Console
from rich.table import Table

from src.infra import trace
from src.ui.ascii.palette import ACCENT, BOITE, SOURD

console = Console()

#: Couleur par résultat. Le vert est réservé à ce qui a EU LIEU — un tour bloqué
#: n'est pas un tour réussi, et le peindre en vert est le défaut qu'un commit
#: entier a corrigé ailleurs.
_TEINTES = {
    trace.OK: "green",
    "casse": "red",
    trace.ERREUR: "red",
    trace.BLOQUE: "yellow",
    trace.CACHE: SOURD,
}


def _table(*colonnes: str) -> Table:
    table = Table(box=BOITE, border_style=f"dim {ACCENT}", header_style=ACCENT,
                  pad_edge=False)
    for i, nom in enumerate(colonnes):
        table.add_column(nom, justify="left" if i == 0 else "right")
    return table


def _mediane(valeurs: list[int]) -> int:
    retenues = sorted(v for v in valeurs if v > 0)
    if not retenues:
        return 0
    milieu = len(retenues) // 2
    if len(retenues) % 2:
        return retenues[milieu]
    return (retenues[milieu - 1] + retenues[milieu]) // 2


# ── Vue « derniers tours » ───────────────────────────────────────────────────
def _rendre_run(lignes: list[dict]) -> None:
    if not lignes:
        return
    tete = lignes[0]
    intention = next((l.get("intent") for l in lignes if l.get("intent")), "")
    console.print()
    console.print(
        f"[{ACCENT}]{tete.get('run_id') or '—'}[/]  "
        f"[{SOURD}]{tete.get('at', '')[:19]}  ·  {tete.get('source') or '?'}"
        f"{'  ·  ' + tete['axon_sha'] if tete.get('axon_sha') else ''}[/]")
    if intention:
        console.print(f"  [white]{intention}[/]")

    for ligne in lignes:
        genre = str(ligne.get("genre") or "")
        resultat = str(ligne.get("resultat") or "")
        # L'écriture a réussi ET le fichier ne tient pas debout : les deux sont
        # vrais, et c'est le second qui doit se voir. Afficher un « ok » vert sur
        # une ligne qui porte `casse` peindrait en vert ce qui n'a pas eu lieu.
        if ligne.get("verification") == "casse":
            resultat = "casse"
        teinte = _TEINTES.get(resultat, SOURD)
        detail = _detail(ligne, genre)
        marque = f"[{teinte}]{resultat or '·'}[/]" if resultat else f"[{SOURD}]·[/]"
        console.print(f"  [{SOURD}]{genre:<12}[/] {marque}  {detail}")


def _detail(ligne: dict, genre: str) -> str:
    """Ce qui distingue cette ligne des autres de son genre."""
    if genre == trace.ROUTE:
        groupes = ", ".join(f"{g}#{r}" for g, r in (ligne.get("groupes") or []))
        return (f"[{SOURD}]{groupes or 'aucun groupe'} → "
                f"{len(ligne.get('outils_lies') or [])} outils liés[/]")
    if genre == trace.RATTRAPAGE:
        return f"[yellow]+ catalogue → {ligne.get('outil') or '?'}[/]"
    if genre == trace.APPEL_LLM:
        strategies = " ".join(f"[yellow]{k}[/]" for k in (ligne.get("extra") or {}))
        return (f"[{SOURD}]{ligne.get('backend') or '?'}  "
                f"{ligne.get('tokens_entree', 0):,}→{ligne.get('tokens_sortie', 0):,} tk  "
                f"{ligne.get('latence_ms', 0)} ms[/] {strategies}".replace(",", " "))
    verdict = ligne.get("policy") or ""
    controle = ligne.get("verification") or ""
    morceaux = [f"[white]{ligne.get('outil') or '?'}[/]"]
    if ligne.get("cible"):
        morceaux.append(f"[{SOURD}]{ligne['cible'][:60]}[/]")
    if verdict and verdict != trace.AUTORISE:
        morceaux.append(f"[yellow]{verdict}[/]")
    if controle and controle != trace.NON_VERIFIE:
        morceaux.append(f"[{'red' if controle == 'casse' else 'green'}]{controle}[/]")
    if ligne.get("erreur"):
        morceaux.append(f"[red]{ligne['erreur']}[/]")
    if ligne.get("latence_ms"):
        morceaux.append(f"[{SOURD}]{ligne['latence_ms']} ms[/]")
    return "  ".join(morceaux)


# ── Vue « routage » ──────────────────────────────────────────────────────────
def _rendre_route(lignes: list[dict]) -> None:
    routes = [l for l in lignes if l.get("genre") == trace.ROUTE]
    if not routes:
        console.print(f"[{SOURD}]  aucun routage tracé[/]")
        return

    retenus: Counter = Counter()
    rangs: dict[str, list[int]] = defaultdict(list)
    lies: list[int] = []
    for ligne in routes:
        lies.append(len(ligne.get("outils_lies") or []))
        for groupe, rang in (ligne.get("groupes") or []):
            retenus[groupe] += 1
            rangs[groupe].append(int(rang))

    table = _table("groupe", "retenu", "part", "rang médian")
    for groupe, compte in retenus.most_common():
        table.add_row(groupe, str(compte), f"{100 * compte / len(routes):.0f} %",
                      str(_mediane(rangs[groupe]) or "—"))
    console.print()
    console.print(table)

    moyenne = sum(lies) / len(lies) if lies else 0
    console.print(f"\n  [{SOURD}]{len(routes)} tour(s)  ·  "
                  f"{moyenne:.1f} outils liés en moyenne  ·  "
                  f"max {max(lies, default=0)}[/]")

    # Le taux que `graph.py` demandait en commentaire. Le dénominateur est le
    # nombre de TOURS, pas de rattrapages : « combien de tours ont eu besoin du
    # filet » est la question, « combien de fois au total » ne se compare à rien.
    rattrapages = [l for l in lignes if l.get("genre") == trace.RATTRAPAGE]
    touches = {l.get("run_id") for l in rattrapages}
    part = 100 * len(touches) / len(routes) if routes else 0
    console.print(f"  [{SOURD}]filet du catalogue : {len(rattrapages)} réclamation(s) "
                  f"sur {len(touches)} tour(s) — {part:.0f} % des tours[/]")
    if rattrapages:
        top = Counter(l.get("outil") for l in rattrapages).most_common(8)
        console.print("  [" + SOURD + "]" + "  ".join(
            f"{nom}×{n}" for nom, n in top) + "[/]")


# ── Vue « erreurs » ──────────────────────────────────────────────────────────
def _rendre_erreurs(lignes: list[dict]) -> None:
    """Les deux signaux d'erreur que la trace écrit déjà, comptés.

    Des COMPTES, pas des taux : à volume mono-utilisateur un ratio ne veut rien
    dire — « trois rattrapages sur gmail_send_email ce mois-ci » se lit, « 4,2 % »
    ne se lit pas. C'est le même arbitrage qui a fait reporter Prometheus.
    """
    from src.infra import erreurs

    vue = erreurs.couverture(lignes)
    console.print(f"\n  [{SOURD}]{vue['runs']} tour(s) observé(s)  ·  "
                  f"{vue['avec_signal']} portant un signal  ·  "
                  f"projets : {', '.join(vue['projets']) or '—'}[/]")

    rattrapes = erreurs.rattrapages(lignes)
    if rattrapes:
        table = _table("outil réclamé", "projet", "n", "exemple")
        for compte in rattrapes:
            table.add_row(compte.quoi, compte.projet, str(compte.n),
                          (compte.exemples[0][:52] if compte.exemples else "—"))
        console.print()
        console.print(table)
        # Écrit à chaque affichage, et pas seulement dans la doc : c'est au
        # moment de lire le chiffre qu'on est tenté d'en tirer une règle.
        console.print(f"  [{SOURD}]un rattrapage dit que la sélection n'a pas lié[/]")
        console.print(f"  [{SOURD}]l'outil réclamé — pas qu'il était le bon.[/]")
        console.print(f"  [{SOURD}]relire un échantillon avant d'en durcir une porte.[/]")
    else:
        console.print(f"  [{SOURD}]aucun rattrapage au catalogue[/]")

    refuses = erreurs.refus(lignes)
    if refuses:
        table = _table("cible refusée", "projet", "motif", "n", "consigne donnée")
        for compte in refuses:
            table.add_row(compte.quoi[-46:], compte.projet,
                          compte.motif, str(compte.n),
                          (compte.exemples[0][:40] if compte.exemples else "—"))
        console.print()
        console.print(table)
    else:
        console.print(f"  [{SOURD}]aucun refus à la demande[/]")


# ── Vue « outils » ───────────────────────────────────────────────────────────
def _rendre_outils(lignes: list[dict]) -> None:
    # Les tâches planifiées sont comptées à part : leur identifiant n'est pas un
    # nom d'outil, et les mélanger rendrait la colonne illisible pour les deux.
    taches = [l for l in lignes if l.get("genre") == trace.TACHE]
    appels = [l for l in lignes if l.get("genre") == trace.OUTIL]
    if not appels and not taches:
        console.print(f"[{SOURD}]  aucun appel d'outil tracé[/]")
        return

    if taches:
        rates = sum(1 for t in taches if t.get("resultat") == trace.ERREUR)
        console.print(f"\n  [{SOURD}]tâches planifiées : {len(taches)} exécution(s), "
                      f"{rates} en erreur[/]")
    if not appels:
        return

    par_outil: dict[str, list[dict]] = defaultdict(list)
    for ligne in appels:
        par_outil[str(ligne.get("outil") or "?")].append(ligne)

    table = _table("outil", "appels", "ok", "erreur", "bloqué", "cache",
                   "latence méd.")
    for outil, siennes in sorted(par_outil.items(),
                                 key=lambda kv: -len(kv[1])):
        compte = Counter(str(l.get("resultat") or "") for l in siennes)
        med = _mediane([int(l.get("latence_ms") or 0) for l in siennes])
        table.add_row(
            outil, str(len(siennes)),
            str(compte[trace.OK] or "—"),
            f"[red]{compte[trace.ERREUR]}[/]" if compte[trace.ERREUR] else "—",
            f"[yellow]{compte[trace.BLOQUE]}[/]" if compte[trace.BLOQUE] else "—",
            str(compte[trace.CACHE] or "—"),
            f"{med} ms" if med else "—")
    console.print()
    console.print(table)

    # La couverture de VERIFY, comptée plutôt que supposée. C'est le chiffre qui
    # dira quand l'étendre vaut le coup, et à quelles extensions.
    controles = Counter(str(l.get("verification") or "") for l in appels)
    verifies = sum(v for k, v in controles.items()
                   if k and k != trace.NON_VERIFIE)
    console.print(f"\n  [{SOURD}]vérifié : {verifies} action(s) sur {len(appels)} "
                  f"— le reste n'a pas de contrôle déterministe[/]")


def _rendre_llm(lignes: list[dict]) -> None:
    appels = [l for l in lignes if l.get("genre") == trace.APPEL_LLM]
    if not appels:
        return
    entree = [int(l.get("tokens_entree") or 0) for l in appels]
    table = _table("backend", "appels", "tk entrée méd.", "tk entrée max",
                   "latence méd.")
    par_backend: dict[str, list[dict]] = defaultdict(list)
    for ligne in appels:
        par_backend[str(ligne.get("backend") or "?")].append(ligne)
    for backend, siennes in sorted(par_backend.items(), key=lambda kv: -len(kv[1])):
        tk = [int(l.get("tokens_entree") or 0) for l in siennes]
        table.add_row(
            backend, str(len(siennes)), f"{_mediane(tk):,}".replace(",", " "),
            f"{max(tk, default=0):,}".replace(",", " "),
            f"{_mediane([int(l.get('latence_ms') or 0) for l in siennes])} ms")
    console.print()
    console.print(table)
    console.print(f"\n  [{SOURD}]pic d'entrée : "
                  f"{max(entree, default=0):,} tokens[/]".replace(",", " "))


def main(argv: list[str]) -> int:
    parseur = argparse.ArgumentParser(
        prog="axon trace", description="Relire la trace de décision d'AXON.")
    parseur.add_argument("run_id", nargs="?", default="",
                         help="le détail d'un run précis")
    parseur.add_argument("--runs", type=int, default=10,
                         help="nombre de tours affichés (défaut 10)")
    parseur.add_argument("--source", default="",
                         help="ne garder que tui | cron | api | mcp")
    parseur.add_argument("--route", action="store_true",
                         help="agrégat du routage et du filet de catalogue")
    parseur.add_argument("--outils", action="store_true",
                         help="agrégat par outil, et couverture de VERIFY")
    parseur.add_argument("--erreurs", action="store_true",
                         help="ce qui a raté : rattrapages au catalogue, refus")
    parseur.add_argument("--llm", action="store_true",
                         help="agrégat des appels au modèle : tokens, latence")
    parseur.add_argument("--export-langfuse", action="store_true",
                         help="pousser la trace vers un Langfuse auto-hébergé")
    parseur.add_argument("--tout", action="store_true",
                         help="avec --export-langfuse : réexporter depuis le début")
    args = parseur.parse_args(argv)

    lignes = trace.lire()
    if args.source:
        lignes = [l for l in lignes if l.get("source") == args.source]
    if not lignes:
        console.print(f"\n  [{SOURD}]trace vide — {trace.FICHIER}[/]")
        console.print(f"  [{SOURD}]AXON_TRACE=0 la désactive ; "
                      f"vérifie qu'elle ne l'est pas.[/]\n")
        return 0

    if args.export_langfuse:
        from src.infra.langfuse_export import exporter

        return exporter(lignes, console=console, tout=args.tout)

    if args.route:
        _rendre_route(lignes)
    elif args.outils:
        _rendre_outils(lignes)
    elif args.erreurs:
        _rendre_erreurs(lignes)
    elif args.llm:
        _rendre_llm(lignes)
    elif args.run_id:
        voulus = [l for l in lignes if str(l.get("run_id", "")).startswith(args.run_id)]
        if not voulus:
            console.print(f"\n  [{SOURD}]aucun run ne commence par "
                          f"« {args.run_id} »[/]\n")
            return 1
        for run in trace.par_run(voulus):
            _rendre_run(run)
    else:
        for run in trace.par_run(lignes)[-args.runs:]:
            _rendre_run(run)
    console.print()
    return 0
