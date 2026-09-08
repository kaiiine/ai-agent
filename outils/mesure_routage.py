#!/usr/bin/env python
"""Le routage, mesuré sur le corpus réel — hors ligne, sans modèle, reproductible.

Quatre taux, parce qu'ils ne disent pas la même chose et qu'un seul induirait en
erreur :

    rang 1          le groupe attendu arrive en tête de l'étage 1
    rappel étage 1  il apparaît quelque part dans le classement
    RAPPEL RÉEL     un de ses outils est effectivement LIÉ au modèle
    largeur         combien d'outils sont liés, et si le budget sature

Le rappel réel est le seul qui compte : lui seul tient compte des groupes
épinglés et des portes déterministes, que l'étage 1 ignore. Mesuré séparément,
l'étage 1 donnait 84,7 % là où le modèle recevait en fait le bon outil 93,9 % du
temps — neuf points d'écart, et de quoi faire optimiser la mauvaise pièce.

Sur les skills, les deux jeux sont mesurés SÉPARÉMENT et l'écart est le résultat :
95,5 % en réglage contre 75,0 % sur le jeu tenu à l'écart. Un score sur le seul
jeu qui a servi à régler ne dirait rien.

Cet écart a d'abord été attribué aux alias curés à la main. C'était FAUX : en les
retirant du classement, il vaut toujours 20,5 points. Il vient des documents de
skills, écrits en anglais et nommant la solution, face à des requêtes françaises
qui décrivent un symptôme — « tsc refuse de compiler » contre « TypeScript error
resolution ». Le détail est dans `skills/retriever.pertinentes`.

Ce fichier est versionné pour que le chiffre se REJOUE. Une mesure qu'on ne peut
pas refaire est une anecdote.

    python outils/mesure_routage.py              # tout
    python outils/mesure_routage.py --skills     # les skills seules
    python outils/mesure_routage.py --journal    # enregistre et compare à hier

Le JOURNAL clôt ce que « rejouable » laissait ouvert. Un chiffre qu'on peut
refaire mais pas comparer ne détecte rien : on constate 93,9 % aujourd'hui sans
voir qu'on était à 96 % la semaine passée. `--journal` ajoute le relevé daté
dans `~/.axon/mesures.jsonl` et affiche l'écart avec le précédent — l'écriture
est explicite pour qu'une exécution exploratoire ne pollue pas la série.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

# Sortie NON BUFFERISÉE. Python bufferise dès qu'il n'écrit pas dans un terminal,
# et un balayage de plusieurs minutes redirigé vers un fichier n'affichait donc
# rien avant la toute fin — impossible de savoir s'il travaillait ou s'il était
# bloqué. Un instrument qu'on ne peut pas observer pendant qu'il tourne se fait
# tuer par impatience.
sys.stdout.reconfigure(line_buffering=True)

#: Une entrée du corpus : la requête citée, puis son étiquette. `fait:` est ce
#: qu'AXON avait produit — jamais la bonne réponse. On ne note pas un système sur
#: ses propres décisions.
#: `(\S*)` ne capturait qu'UN mot : « attendu: notebook, filesystem » devenait
#: l'étiquette « notebook, » — virgule comprise, donc fausse en silence. Une
#: tâche demande souvent deux domaines (trouver le notebook PUIS l'éditer), et
#: le format doit pouvoir le dire.
#: `**attendu**:` est accepté autant que `attendu:` — qui remplit un fichier
#: markdown à la main met du gras, et une entrée qui ne se parse pas disparaît
#: SANS BRUIT du calcul. Vécu : une étiquette sur 62 perdue de cette façon.
_ENTREE = re.compile(
    r"^> (.+?)$\n\n(?:\*{0,2}fait\*{0,2}:.*\n)?\*{0,2}attendu\*{0,2}:[ \t]*(.*)$", re.M)


def etiquettes(brut: str) -> list[str]:
    """Une étiquette par groupe attendu — « notebook, filesystem » en vaut deux."""
    return [e.strip() for e in brut.split(",") if e.strip()]

#: Écartées du calcul : l'utilisateur les a lui-même déclarées sans réponse unique.
_SANS_REPONSE = {"ambigu"}


#: Où les mesures s'accumulent. `~/.axon` porte déjà l'état d'AXON — index
#: sémantique, santé des clés, mémoire projet — et un relevé daté y a sa place.
from src.infra import chemins as _chemins  # noqa: E402

_JOURNAL = _chemins.mesures()

#: Sens de lecture de chaque métrique : +1 si monter est un progrès, -1 sinon.
#: Sans ça, « largeur 15,8 → 19,0 » s'afficherait comme une amélioration.
_SENS = {"rappel": +1, "rang 1": +1, "top 5": +1, "complètes": +1,
         "précision": +1, "largeur": -1, "écart": -1}


def _sens_de(cle: str) -> int:
    for motif, sens in _SENS.items():
        if motif in cle:
            return sens
    return +1


def journaliser(mesure: str, valeurs: dict[str, float], ecrire: bool) -> None:
    """Compare au dernier relevé de la même mesure, puis l'enregistre.

    Rejouer un chiffre ne suffit pas : sans historique, on peut mesurer
    aujourd'hui sans jamais voir qu'on a régressé depuis la semaine dernière.
    L'écriture est EXPLICITE — `--journal` — pour qu'une exécution
    exploratoire ne pollue pas la série.
    """
    import json as _json
    from datetime import datetime, timezone

    precedent = None
    if _JOURNAL.exists():
        for ligne in _JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                entree = _json.loads(ligne)
            except ValueError:
                continue
            if entree.get("mesure") == mesure:
                precedent = entree

    if precedent:
        quand = precedent.get("date", "?")[:10]
        print(f"   ── contre le relevé du {quand} ──")
        for cle, valeur in valeurs.items():
            avant = (precedent.get("valeurs") or {}).get(cle)
            if avant is None:
                print(f"      {cle:<26} {valeur:>7.1f}   (nouveau)")
                continue
            delta = valeur - avant
            if abs(delta) < 0.05:
                fleche = "="
            else:
                fleche = "▲" if delta * _sens_de(cle) > 0 else "▼"
            print(f"      {cle:<26} {valeur:>7.1f}   avant {avant:>6.1f}"
                  f"   {fleche} {abs(delta):.1f}")
    elif ecrire:
        print("   ── premier relevé : rien à comparer ──")

    if not ecrire:
        return
    _JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with _JOURNAL.open("a", encoding="utf-8") as sortie:
        sortie.write(_json.dumps({
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mesure": mesure, "valeurs": valeurs,
        }, ensure_ascii=False) + "\n")


def corpus() -> list[tuple[str, str]]:
    texte = (RACINE / "CORPUS-ROUTAGE.md").read_text(encoding="utf-8")
    return [(q.strip(), a.strip()) for q, a in _ENTREE.findall(texte)
            if a.strip() and a.strip() not in _SANS_REPONSE]


def en_reglage(requete: str) -> bool:
    """Le corpus outils n'avait AUCUNE séparation, contrairement aux skills et aux
    ellipses. Toute constante réglée dessus l'était donc sur le jeu qui servait
    aussi à la valider — la configuration exacte qui a fait passer pour un succès
    un mécanisme à 22/22 en réglage et 7/16 ailleurs.

    Le partage se fait par HACHAGE de la requête, comme pour `corpus_ellipses` :
    il se rejoue à l'identique, ne peut pas être arrangé après coup, et une
    requête ajoutée plus tard ne déplace pas celles qui existent déjà.
    """
    import hashlib

    return int(hashlib.sha1(requete.encode()).hexdigest(), 16) % 10 < 6


def _deux_jeux(cas: list[tuple[str, str]]):
    return ([c for c in cas if en_reglage(c[0])],
            [c for c in cas if not en_reglage(c[0])])


def mesurer_les_outils(journal: bool = False) -> None:
    from src.orchestrator import tool_retriever as module

    # Index ISOLÉ : mesurer ne doit pas réécrire le cache dont dépend le démarrage.
    module._CACHE_DIR = Path("/tmp/axon-mesure-routage")
    module._CACHE_HASH = module._CACHE_DIR / "fingerprint.txt"
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import TOOL_GROUPS, ToolRetriever

    cas = corpus()
    hors = sorted({a for _, a in cas if a not in TOOL_GROUPS and a != "aucun"})
    cas = [(q, a) for q, a in cas if a in TOOL_GROUPS or a == "aucun"]
    print(f"\n━━ OUTILS ━━  {len(cas)} requêtes labellisées et dans le catalogue")
    if hors:
        print(f"   écartées, étiquette hors catalogue : {', '.join(hors)}")

    retriever = ToolRetriever(build_all_tools())
    groupe_de = {t: g for g, spec in TOOL_GROUPS.items() for t in spec.tools}

    rang1 = etage1 = reel = 0
    largeurs: list[int] = []
    echecs: list[tuple[str, str, list[str], list[str]]] = []
    for requete, attendu in cas:
        ordre, _ = retriever._rank_groups_detaille(requete)
        outils = [t.name for t in retriever.get(requete)]
        servis = {groupe_de.get(n) for n in outils}
        largeurs.append(len(outils))

        rang1 += ordre[:1] == [attendu]
        etage1 += attendu in ordre
        if attendu in servis:
            reel += 1
        else:
            echecs.append((requete, attendu, ordre[:3], sorted(g for g in servis if g)))

    n = len(cas)
    sature = " — SATURÉ" if max(largeurs) >= module._BUDGET_OUTILS else ""
    print(f"   rang 1          {rang1:>3}/{n}  {100 * rang1 / n:5.1f} %")
    print(f"   rappel étage 1  {etage1:>3}/{n}  {100 * etage1 / n:5.1f} %")
    print(f"   RAPPEL RÉEL     {reel:>3}/{n}  {100 * reel / n:5.1f} %   ← ce que le modèle reçoit")
    print(f"   outils liés     moyenne {sum(largeurs) / n:.1f}, max {max(largeurs)}"
          f"  (budget {module._BUDGET_OUTILS}{sature})")

    journaliser("outils", {
        "rang 1 (%)": 100 * rang1 / n,
        "rappel réel (%)": 100 * reel / n,
        "largeur (outils)": sum(largeurs) / n,
    }, journal)

    print(f"\n   {len(echecs)} requêtes où aucun outil du groupe attendu n'est lié :")
    for requete, attendu, ordre, servis in echecs:
        print(f"     attendu {attendu:<9} étage1 {','.join(ordre)}")
        print(f"       servis : {','.join(servis)}")
        print(f"       « {requete[:100]} »")


def mesurer_les_skills(journal: bool = False) -> None:
    from src.skills import skills_pertinentes
    from src.skills.tools import BUDGET_SKILLS
    from tests.corpus_routage_skills import REGLAGE, TENU_A_L_ECART

    scores: dict[str, float] = {}
    for nom, jeu in (("RÉGLAGE — a servi à construire", REGLAGE),
                     ("TENU À L'ÉCART — n'a jamais servi à régler", TENU_A_L_ECART)):
        a1 = a3 = a5 = 0
        rates: list[tuple[str, str, list[str]]] = []
        for requete, attendue in jeu:
            rendu = skills_pertinentes(requete, "coding", BUDGET_SKILLS)
            a1 += rendu[:1] == [attendue]
            a3 += attendue in rendu[:3]
            if attendue in rendu:
                a5 += 1
            else:
                rates.append((requete, attendue, rendu[:3]))
        n = len(jeu)
        scores[nom] = 100 * a5 / n
        print(f"\n━━ SKILLS ━━  {nom}  ({n} requêtes)")
        print(f"   rang 1          {a1:>3}/{n}  {100 * a1 / n:5.1f} %")
        print(f"   top 3           {a3:>3}/{n}  {100 * a3 / n:5.1f} %")
        print(f"   top {BUDGET_SKILLS}           {a5:>3}/{n}  {100 * a5 / n:5.1f} %"
              f"   ← ce que le modèle voit")
        for requete, attendue, rendu in rates:
            print(f"     RATÉ  attendue {attendue:<22} rendu {','.join(rendu)}")
            print(f"           « {requete} »")

    ecart = max(scores.values()) - min(scores.values())
    print(f"\n   ÉCART entre les deux jeux : {ecart:.1f} points")
    journaliser("skills", {
        "top 5 réglage (%)": scores[list(scores)[0]],
        "top 5 tenu (%)": scores[list(scores)[1]],
        "écart (points)": ecart,
    }, journal)
    if ecart > 10:
        # Ne PAS l'appeler « surajustement » : mesuré, il vaut autant avec les
        # alias curés qu'en les retirant. Il vient des documents — anglais, et
        # nommant la solution — face à des requêtes françaises qui décrivent un
        # symptôme. Voir `skills/retriever.pertinentes`.
        print("      Il ne vient PAS des alias : il est identique en les retirant.")
        print("      Les documents nomment la solution en anglais, la requête")
        print("      décrit le symptôme en français.")


#: Les quatre formes de document que la docstring de `skills.retriever._document`
#: compare — pas des variantes inventées pour l'occasion. On REJOUE une
#: affirmation existante ; on ne cherche pas un document qui battrait les quatre
#: échecs connus du jeu tenu à l'écart. Le distinguo n'est pas cosmétique : caler
#: un document sur des échecs connus, c'est refaire l'erreur des alias de skills,
#: où une liste curée scorait vingt points de plus sur le jeu qui l'avait vue
#: naître.
VARIANTES_DE_DOCUMENT = {
    "description seule": lambda n, s: s.get("description") or n,
    "+ nom": lambda n, s: f"{n}. {s.get('description') or ''}",
    "+ nom + alias": lambda n, s: ". ".join(
        m for m in (n, " ".join(s.get("aliases") or []), s.get("description") or "")
        if m.strip()),
    "+ nom + alias + ancres": lambda n, s: ". ".join(
        m for m in (n, " ".join(s.get("aliases") or []), s.get("description") or "",
                    " ".join(s.get("anchors") or []))
        if m.strip()),
}


def mesurer_les_documents() -> None:
    """Ce qu'on INDEXE pour un skill change-t-il encore quelque chose ?

    La docstring de `_document` affirmait « description seule 4/10, + nom + alias
    10/10 » sur un jeu disparu. Rejoué ici sur les deux jeux de référence, à la
    métrique qui compte — le top 5, puisque le catalogue en montre cinq.
    """
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_ollama import OllamaEmbeddings

    from src.skills.retriever import _retriever
    from src.skills.tools import BUDGET_SKILLS
    from tests.corpus_routage_skills import REGLAGE, TENU_A_L_ECART

    _retriever._load()
    visible = _retriever._visible("coding")
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    print(f"\n━━ DOCUMENTS ━━  {len(visible)} skills, {len(VARIANTES_DE_DOCUMENT)} formes")
    print(f"   top {BUDGET_SKILLS} — ce que le modèle voit\n")
    print(f"   {'forme':<26} {'réglage':>12} {'TENU':>12}   écart")

    for etiquette, fabrique in VARIANTES_DE_DOCUMENT.items():
        docs = [Document(page_content=fabrique(n, s), metadata={"name": n})
                for n, s in visible.items()]
        index = Chroma.from_documents(
            docs, embeddings,
            collection_name=f"mesure-{abs(hash(etiquette)) % 99999}")
        taux = []
        for jeu in (REGLAGE, TENU_A_L_ECART):
            ok = sum(att in [d.metadata["name"]
                             for d in index.similarity_search(q, k=BUDGET_SKILLS)]
                     for q, att in jeu)
            taux.append(100 * ok / len(jeu))
        marque = "  ← en place" if etiquette == "+ nom + alias" else ""
        print(f"   {etiquette:<26} {taux[0]:>10.1f} % {taux[1]:>10.1f} %"
              f"   {taux[0] - taux[1]:>5.1f} pts{marque}")

    print("\n   L'écart réglage↔tenu ne se referme par AUCUNE forme : il ne vient")
    print("   pas de ce qu'on indexe, mais de la langue et du registre des")
    print("   descriptions. Voir `skills/retriever.pertinentes`.")


#: Les constantes réglables de l'étage 1, et les valeurs à essayer. Ce sont
#: celles dont un chiffre de docstring est le seul argument — pas toutes les
#: constantes du module.
BALAYAGES = {
    "_MARGE_CLAUSE": (0.10, 0.15, 0.20, 0.25, 0.30),
    "_MAX_GROUPES_UNION": (5, 6, 8, 10, 12),
    "_BUDGET_OUTILS": (10, 12, 16, 20, 24),
    "_TOP_GROUPS": (3, 5, 7),
    "_FAMILLES_MAX": (1, 2, 3),
}


def mesurer_les_constantes() -> None:  # noqa: C901
    """Chaque constante est-elle encore la meilleure valeur, sur le corpus réel ?

    Le balayage tourne sur le jeu de RÉGLAGE seul. Le jeu tenu à l'écart n'est lu
    qu'à la fin, pour CONSTATER — jamais pour choisir. C'est la discipline qui a
    invalidé un mécanisme entier sur les skills : 22/22 d'un côté, 7/16 de
    l'autre, et un jeu unique l'aurait expédié comme un succès.

    La métrique est le RAPPEL RÉEL — un outil du groupe attendu est-il lié — et
    non le rang 1 : c'est ce que le modèle reçoit. La largeur suit, parce qu'un
    budget plus large achète toujours du rappel et qu'il faut voir le prix.
    """
    from src.orchestrator import tool_retriever as module

    module._CACHE_DIR = Path("/tmp/axon-mesure-routage")
    module._CACHE_HASH = module._CACHE_DIR / "fingerprint.txt"
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import TOOL_GROUPS, ToolRetriever

    cas = [(q, a) for q, a in corpus() if a in TOOL_GROUPS or a == "aucun"]
    reglage, tenu = _deux_jeux(cas)
    retriever = ToolRetriever(build_all_tools())
    groupe_de = {t: g for g, spec in TOOL_GROUPS.items() for t in spec.tools}

    def rappel(jeu) -> tuple[float, float]:
        bons = largeur = 0
        for requete, attendu in jeu:
            outils = retriever.get(requete)
            largeur += len(outils)
            bons += attendu in {groupe_de.get(t.name) for t in outils}
        return 100 * bons / len(jeu), largeur / len(jeu)

    print(f"\n━━ CONSTANTES ━━  {len(reglage)} en réglage, {len(tenu)} tenues à l'écart")
    print("   balayage sur le RÉGLAGE seul ; le tenu n'est lu qu'en constat\n")

    a_revoir = []
    for nom, valeurs in BALAYAGES.items():
        actuelle = getattr(module, nom)
        scores = {}
        for valeur in valeurs:
            setattr(module, nom, valeur)
            scores[valeur] = rappel(reglage)
        setattr(module, nom, actuelle)

        meilleure = max(scores, key=lambda v: (scores[v][0], -scores[v][1]))
        # Ne signaler que ce qui VAUT la peine d'être signalé. La première version
        # marquait `_MARGE_CLAUSE` « à revoir » pour +0,0 point de rappel et 0,1
        # outil : un instrument qui remonte du bruit fait ignorer ses vrais
        # signaux. Un gain compte s'il apporte du rappel, ou s'il rend au moins un
        # outil de budget à rappel égal.
        gain = scores[meilleure][0] - scores[actuelle][0]
        economie = scores[actuelle][1] - scores[meilleure][1]
        notable = meilleure != actuelle and (gain > 0.5 or economie >= 1.0)
        marque = f"   ← {meilleure} fait mieux" if notable else ""
        if notable:
            a_revoir.append((nom, actuelle, meilleure, scores))
        print(f"   {nom} = {actuelle}{marque}")
        for valeur, (r, l) in scores.items():
            ici = " ←" if valeur == actuelle else ""
            print(f"      {valeur:>6}  rappel {r:5.1f} %   largeur {l:4.1f}{ici}")

    print("\n   ── constat sur le jeu TENU À L'ÉCART, valeurs en place ──")
    r, l = rappel(tenu)
    print(f"      rappel {r:.1f} %   largeur {l:.1f}")
    if not a_revoir:
        print("\n   Toutes les constantes sont encore optimales sur le réglage.")
    else:
        print(f"\n   {len(a_revoir)} constante(s) dont la valeur n'est plus la meilleure :")
        for nom, actuelle, meilleure, scores in a_revoir:
            gain = scores[meilleure][0] - scores[actuelle][0]
            cout = scores[meilleure][1] - scores[actuelle][1]
            print(f"      {nom} : {actuelle} → {meilleure}"
                  f"  ({gain:+.1f} pts de rappel, {cout:+.1f} outil(s) liés)")
        print("      À NE PAS appliquer sur ce seul balayage. Vécu le 6 septembre :")
        print("      `_BUDGET_OUTILS` 16 → 12 était indiscernable ICI, sur les deux")
        print("      jeux — et faisait tomber TROIS tests de non-régression, sur des")
        print("      tournures que ce corpus ne contient pas. Rejouer d'abord :")
        print("          pytest tests/test_tool_routing.py tests/test_budget_outils.py \\")
        print("                 tests/test_routing_generalization.py")

#: Routés sémantiquement mais sans domaine déclaré dans `_TOOL_GROUPS` — ils
#: étaient invisibles dans toute mesure jusqu'à ce que l'utilisateur demande
#: « il n'y a plus le groupe d'outils agent code ? ». Sept outils, dont les six
#: du graphe de projet, le domaine le plus souvent lié de tous.
_HORS_GROUPES = {
    "graph_affected": "graphe", "graph_build": "graphe", "graph_explain": "graphe",
    "graph_path": "graphe", "graph_query": "graphe", "project_graph_query": "graphe",
    "deleguer": "delegation",
}


def mesurer_le_coding(journal: bool = False) -> None:
    """Ce que l'agent de code reçoit, contre ce qu'il lui fallait.

    Le corpus est étiqueté par l'utilisateur, à partir du texte des tâches. La
    métrique est le RAPPEL — chaque groupe attendu est-il servi — et la PRÉCISION,
    qui manquait partout ailleurs : combien de groupes liés n'étaient pas
    demandés. Sur les outils, seul le rappel comptait parce que le budget était
    le prix. Ici l'utilisateur a dit ce qui était NÉCESSAIRE, donc le superflu
    devient mesurable.
    """
    from src.agents.coding.specialist import _get_coding_tools
    from src.agents.coding.tool_retriever import _TOOL_GROUPS, CodingToolRetriever

    texte = (RACINE / "CORPUS-CODING.md").read_text(encoding="utf-8")
    cas = [(q.strip(), etiquettes(a)) for q, a in _ENTREE.findall(texte) if a.strip()]
    cas = [(q, e) for q, e in cas if "ambigu" not in e]
    if not cas:
        print("\n━━ CODING ━━  aucune entrée étiquetée dans CORPUS-CODING.md")
        return

    outils = _get_coding_tools()
    groupe_de = {t: g for g, ts in _TOOL_GROUPS.items() for t in ts}
    groupe_de.update(_HORS_GROUPES)

    def domaine(nom: str) -> str | None:
        return nom.split("__", 1)[0] if "__" in nom else groupe_de.get(nom)

    retriever = CodingToolRetriever(outils, k=8)
    reglage, tenu = _deux_jeux(cas)

    for nom, jeu in (("RÉGLAGE", reglage), ("TENU À L'ÉCART", tenu)):
        if not jeu:
            continue
        servis_total = attendus_total = justes = 0
        complets = 0
        manques: dict[str, int] = {}
        superflus: dict[str, int] = {}
        for requete, attendus in jeu:
            servis = {domaine(t.name) for t in retriever.get(requete)} - {None}
            vises = set(attendus) - {"aucun"}
            justes += len(vises & servis)
            attendus_total += len(vises)
            servis_total += len(servis)
            complets += vises <= servis
            for g in vises - servis:
                manques[g] = manques.get(g, 0) + 1
            for g in servis - vises:
                superflus[g] = superflus.get(g, 0) + 1

        n = len(jeu)
        print(f"\n━━ CODING ━━  {nom}  ({n} tâches)")
        print(f"   rappel      {justes}/{attendus_total} groupes attendus servis"
              f"  ({100 * justes / max(attendus_total, 1):.1f} %)")
        print(f"   tâches complètement servies  {complets}/{n}"
              f"  ({100 * complets / n:.1f} %)   ← rien ne manque")
        print(f"   précision   {justes}/{servis_total} groupes liés étaient demandés"
              f"  ({100 * justes / max(servis_total, 1):.1f} %)")
        journaliser(f"coding {nom.lower()}", {
            "rappel (%)": 100 * justes / max(attendus_total, 1),
            "complètes (%)": 100 * complets / n,
            "précision (%)": 100 * justes / max(servis_total, 1),
        }, journal)

        if manques:
            print("   MANQUÉS  " + ", ".join(
                f"{g}×{c}" for g, c in sorted(manques.items(), key=lambda x: -x[1])))
        if superflus:
            print("   EN TROP  " + ", ".join(
                f"{g}×{c}" for g, c in sorted(superflus.items(), key=lambda x: -x[1])))


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Mesure du routage sur corpus réel.")
    analyseur.add_argument("--outils", action="store_true", help="les outils seuls")
    analyseur.add_argument("--skills", action="store_true", help="les skills seules")
    analyseur.add_argument("--documents", action="store_true",
                           help="comparer les formes de document indexé (avec --skills)")
    analyseur.add_argument("--constantes", action="store_true",
                           help="rejouer le balayage de chaque constante réglable")
    analyseur.add_argument("--coding", action="store_true",
                           help="le routage de l'agent de code (CORPUS-CODING.md)")
    analyseur.add_argument("--journal", action="store_true",
                           help=f"enregistrer le relevé dans {_JOURNAL} et le comparer "
                                "au précédent")
    args = analyseur.parse_args()
    tout = not (args.outils or args.skills or args.documents
                or args.constantes or args.coding)

    if args.outils or tout:
        mesurer_les_outils(args.journal)
    if args.skills or tout:
        mesurer_les_skills(args.journal)
    if args.documents or tout:
        mesurer_les_documents()
    if args.coding or tout:
        mesurer_le_coding(args.journal)
    if args.constantes or tout:
        mesurer_les_constantes()


if __name__ == "__main__":
    main()
