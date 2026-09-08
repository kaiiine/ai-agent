#!/usr/bin/env python
"""Le filet de rattrapage, mesuré — la seule pièce du routage qui ne l'était pas.

AXON ne prédit pas l'outil : il en lie seize, met le catalogue des 105 sous les
yeux du modèle, et lui donne `obtenir_outil(nom=…)` à chaque tour. C'est la forme
de Claude Code, et c'est elle qui explique l'écart 84,7 % → 93,9 % entre l'étage
1 et ce que le modèle reçoit vraiment.

Mais la question que ce chiffre laisse ouverte n'est pas « l'architecture
est-elle bonne » — elle l'est. C'est :

    le modèle utilise-t-il FIABLEMENT l'échappatoire, sous pression de budget,
    quand seize outils approximatifs lui tendent déjà les bras ?

Tant que ce taux n'existe pas, les 6,1 % d'échecs de routage sont peut-être 6,1 %
de rattrapages silencieux, ou 6,1 % d'échecs définitifs. On ne sait pas lequel, et
optimiser le routeur avant de le savoir, c'est optimiser à l'aveugle.

Ce script assemble le MÊME prompt que la production — même sélection, même
catalogue, même consigne — et classe ce que le modèle fait :

    JUSTE       il appelle le bon outil, qui était lié         → rien à rattraper
    DIRECT      il appelle le bon outil NON LIÉ, lu au catalogue → rattrapé
    RÉCLAMÉ     il appelle `obtenir_outil` avec le nom attendu   → rattrapé
    RÉCLAMÉ ✗   il appelle `obtenir_outil` avec un autre nom     → il a cherché, mal
    APPROXIMÉ   il appelle un outil qui n'est pas le bon         → ÉCHEC SILENCIEUX
    TEXTE       il répond sans outil                             → capacité niée
    CLARIF      il demande une précision                         → coûte un tour

Le taux qui compte est celui des ÉCHECS SILENCIEUX : ce sont les seuls dont
l'utilisateur ne voit rien. Un tour de plus n'est pas une erreur ; un mauvais
outil appelé avec assurance en est une.

Coûte des appels au modèle. Ne tourne pas dans la suite de tests, qui est
entièrement hors ligne.

    python outils/mesure_filet.py                    # backend selon l'ordre de repli
    python outils/mesure_filet.py --backend gemini   # forcé
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

#: Les six requêtes du corpus réel où AUCUN outil du groupe attendu n'est lié,
#: avec l'outil que le modèle devrait réclamer. Ce sont les cas où le filet est
#: la SEULE issue — mesurés par `outils/mesure_routage.py`.
DECOUVERTES = [
    ("Hmm peux tu regarder voir s'il n'y a pas moins risqué ? "
     "estime moi le purcentage de réussite sur ce combo", "betting_recommend"),
    ("Peux tu me dire s'il y a de bon pris a faire la en ce moment ou pas ?",
     "betting_recommend"),
    ("le match kansas city il est quand ?", "web_search"),
    ("reprend ou tu en étais sans rien oublier", "run_coding_agent"),
    ("contoinue alors, reprend le travail et finin moi tout ça", "run_coding_agent"),
    ("gznre quans je lance saphire alpha ça me dis "
     "\"vous ne pouvez pas utiliser ceete carte de jeu\"", "web_search"),
]

#: Des requêtes que le routage sert CORRECTEMENT. Sans elles, on mesurerait la
#: propension du modèle à réclamer, pas sa justesse : un modèle qui réclamerait à
#: chaque tour ferait 100 % sur les six premières et serait inutilisable.
TEMOINS = [
    ("quelle heure est-il ?", "get_current_time"),
    ("quel temps fait-il à Paris ?", "get_weather_by_city"),
    ("quels sont mes fichiers modifiés ?", "git_status"),
    ("envoie le récap dans le salon test-cron sur Slack", "slack_send_message"),
]


#: Des demandes LIMPIDES dont l'outil porte un schéma qu'un résumé d'une ligne ne
#: laisse pas deviner : paramètres requis nombreux, noms non évidents, formats de
#: date. Les quatre premiers témoins ne testaient que « le modèle sait-il qu'un
#: outil nommé `get_weather_by_city` prend une ville » — ce qui se devine sans
#: catalogue. Ici, deviner ne suffit plus : si l'appel direct produit des
#: arguments invalides, `obtenir_outil` n'est pas redondant, il est mal packagé.
SCHEMAS_RICHES = [
    ("Surveille le cours du Bitcoin toutes les 2 minutes et notifie-moi sur Slack "
     "dans test-cron si le prix change de plus de 1%", "surveiller"),
    ("Crée un événement « Point AXON » demain de 14h à 15h dans mon agenda",
     "calendar_create_event"),
    ("Crée un ticket Jira dans le projet AXON, une tâche intitulée "
     "« Le routage des skills surapprend »", "jira_create_issue"),
    ("Envoie un mail à nicolas@example.com avec pour objet « Récap » et "
     "pour texte « voici le récap de la semaine »", "gmail_send_email"),
]


def _arguments_valides(attendu: str, reponse) -> tuple[bool, str]:
    """Les arguments produits passent-ils le schéma de l'outil ?

    C'est la question que « le modèle a appelé le bon outil » laisse entière. Le
    catalogue ne donne QUE le nom et un résumé d'une ligne — jamais le schéma,
    qui coûte ~446 tokens l'unité. Un appel direct est donc un appel à l'aveugle :
    il réussit quand la signature se devine, et rien ne dit qu'il réussisse quand
    elle ne se devine pas.
    """
    from src.orchestrator.catalogue import outil as _outil

    cible = _outil(attendu)
    if cible is None or not getattr(cible, "args_schema", None):
        return True, "pas de schéma à vérifier"
    args = next((a.get("args", {}) for a in (getattr(reponse, "tool_calls", None) or [])
                 if a.get("name") == attendu), None)
    if args is None:
        return True, ""
    try:
        cible.args_schema.model_validate(args)
    except Exception as erreur:                                  # noqa: BLE001
        premiere = str(erreur).splitlines()
        detail = premiere[1].strip() if len(premiere) > 1 else str(erreur)[:70]
        return False, f"{sorted(args)} → {detail[:80]}"
    return True, f"{sorted(args)}"


def _backend(force: str | None) -> tuple[str, object]:
    """Le premier backend disponible de la chaîne de repli, et sa fabrique.

    Le nom est rendu avec le chiffre : un taux dépend du modèle qui l'a produit,
    et un résultat obtenu sur un 4B local ne dit rien de la production.
    """
    # `settings` porte le `load_dotenv()`. Sans cet import, `utilisables()` ne
    # voit aucune clé et la chaîne se réduit à `ollama` local EN SILENCE — le
    # chiffre serait alors produit par un petit modèle de la machine, et rien ne
    # le dirait.
    import src.infra.settings  # noqa: F401
    from src.llm.backends import fabriques, ordre_de_repli

    chaine = [force] if force else ordre_de_repli()
    usines = fabriques()
    for nom in chaine:
        if nom in usines:
            return nom, usines[nom]
    raise SystemExit(f"aucun backend utilisable dans {chaine}")


def _classer(reponse, attendu: str, lies: set[str]) -> tuple[str, str]:
    """Ce que le modèle a fait, en une étiquette et un détail.

    `JUSTE` et `RÉCLAMÉ` sont distingués exprès. Les confondre — appeler
    « réclamé » un outil qu'on n'a pas eu besoin de réclamer — ferait lire
    l'échappatoire comme utilisée alors qu'elle ne l'a jamais été. C'est
    précisément ce que la première version de cet instrument affichait.
    """
    appels = getattr(reponse, "tool_calls", None) or []
    if not appels:
        return "TEXTE", (getattr(reponse, "content", "") or "")[:70].replace("\n", " ")

    noms = [a.get("name", "?") for a in appels]
    if "obtenir_outil" in noms:
        reclames = [a.get("args", {}).get("nom", "?")
                    for a in appels if a.get("name") == "obtenir_outil"]
        return ("RÉCLAMÉ" if attendu in reclames else "RÉCLAMÉ ✗"), ",".join(reclames)
    if attendu in noms:
        if attendu in lies:
            return "JUSTE", f"{attendu} — était lié, rien à réclamer"
        # RÉCUPÉRÉ, sans passer par l'échappatoire. Le modèle a lu le nom dans le
        # catalogue et l'a appelé DIRECTEMENT. Ça marche parce que le `ToolNode`
        # est construit sur les 105 outils, pas sur la sélection du tour : la
        # liaison est un tri, pas une barrière. `obtenir_outil` n'est donc pas
        # mort — il est REDONDANT.
        return "DIRECT", f"{attendu} — non lié, appelé depuis le catalogue"
    if "ask_clarification" in noms:
        return "CLARIF", ""
    return "APPROXIMÉ", ",".join(n for n in noms if n in lies) or ",".join(noms)


#: Secondes entre deux appels. Les paliers gratuits limitent au débit, pas au
#: volume : `gemini` et `mistral` ont rendu 429 sur 9 et 16 appels d'une série de
#: quatorze tirée d'affilée. Un instrument qui sature le fournisseur ne mesure
#: plus le modèle, il mesure le quota.
_PAUSE_PAR_DEFAUT = 4.0


def _invoquer(llm, messages: list, pause: float):
    """Un appel, avec une seule reprise si le fournisseur demande d'attendre."""
    import time

    try:
        return llm.invoke(messages)
    except Exception as erreur:                                  # noqa: BLE001
        if "429" not in str(erreur) and "RESOURCE_EXHAUSTED" not in str(erreur):
            raise
        time.sleep(max(pause, 1.0) * 5)
        return llm.invoke(messages)


def _avec_reparation(llm, messages: list, selection: list, pause: float = 0.0):
    """Un tour de modèle, réparation du faux appel en texte COMPRISE.

    `graph.py` détecte un appel d'outil rendu en JSON brut et relance une fois
    pour forcer un vrai appel structuré. Sans reproduire ce tour ici, l'instrument
    classait « TEXTE » ce que la production répare — et faisait passer un défaut
    corrigé pour un défaut ouvert. Une mesure qui court-circuite le chemin réel
    mesure autre chose que ce qu'elle prétend.
    """
    from langchain_core.messages import HumanMessage

    from src.orchestrator.provider_quirks import outil_ecrit_en_json

    reponse = _invoquer(llm, messages, pause)
    if getattr(reponse, "tool_calls", None):
        return reponse

    texte = getattr(reponse, "content", "") or ""
    if not isinstance(texte, str) or not outil_ecrit_en_json(texte, selection):
        return reponse

    rappel = HumanMessage(content=(
        "[SYSTEME] Ta dernière réponse contenait un faux appel d'outil écrit en "
        "texte brut au lieu d'un vrai appel : une balise 'xxx:tool_call', ou les "
        "arguments rendus comme objet JSON. Ni l'un ni l'autre n'exécute quoi que "
        "ce soit. Refais le même appel en utilisant le vrai mécanisme de function "
        "calling à ta disposition, pas du texte."))
    try:
        return _invoquer(llm, messages + [reponse, rappel], pause)
    except Exception:                                            # noqa: BLE001
        return reponse


def _repare_sur_lerreur(llm, messages: list, reponse, attendu: str) -> tuple[bool, str]:
    """Le modèle corrige-t-il ses arguments quand l'outil les lui refuse ?

    C'est la question qui décide s'il faut empaqueter des schémas dans le
    catalogue ou rien du tout. `tool_error_to_message` renvoie déjà le détail
    pydantic — « project_key / Field required » — et un message qui NOMME le
    champ manquant est peut-être toute la réparation nécessaire. Le vérifier
    coûte un tour ; l'écrire sans vérifier coûterait un mécanisme entier.
    """
    from langchain_core.messages import ToolMessage

    from src.orchestrator.catalogue import outil as _outil
    from src.orchestrator.resilience import tool_error_to_message

    appel = next((a for a in (getattr(reponse, "tool_calls", None) or [])
                  if a.get("name") == attendu), None)
    cible = _outil(attendu)
    if appel is None or cible is None:
        return False, "rien à réparer"
    try:
        cible.args_schema.model_validate(appel.get("args", {}))
        return True, "déjà valide"
    except Exception as erreur:                                  # noqa: BLE001
        refus = tool_error_to_message(erreur)

    retour = ToolMessage(content=refus, tool_call_id=appel.get("id", "x"), name=attendu,
                         status="error")
    try:
        suite = llm.invoke(messages + [reponse, retour])
    except Exception as erreur:                                  # noqa: BLE001
        return False, f"relance impossible : {type(erreur).__name__}"

    valides, mot = _arguments_valides(attendu, suite)
    noms = [a.get("name") for a in (getattr(suite, "tool_calls", None) or [])]
    if attendu not in noms:
        return False, f"n'a pas refait l'appel → {','.join(noms) or 'texte'}"
    return valides, mot


def _monde():
    """Les mêmes outils et le même retriever que `build_graph`, reconstruits.

    Les deux y sont LOCAUX à la fonction : rien à importer. On les rebâtit à
    l'identique, MCP en moins — ses serveurs ne tournent pas forcément, et un
    catalogue qui varie d'une exécution à l'autre rendrait le chiffre incomparable.
    """
    from src.orchestrator.catalogue import indexer, obtenir_outil
    from src.orchestrator.registry import build_all_tools
    from src.orchestrator.tool_retriever import ToolRetriever

    outils = build_all_tools()
    retriever = ToolRetriever(outils)
    indexer(outils + [obtenir_outil])
    return retriever, obtenir_outil


def mesurer(cas: list[tuple[str, str]], titre: str, fabrique, monde,
            compte: dict, delier: frozenset[str] = frozenset(),
            delier_attendu: bool = False, pause: float = 0.0) -> None:
    """`delier` retire des outils AVANT la liaison — c'est l'ablation.

    Zéro appel à `obtenir_outil` sur six cas ne dit pas encore POURQUOI. Deux
    lectures s'opposent, et elles n'appellent pas le même correctif :

        le modèle ignore le catalogue           → il faut réparer la consigne
        le modèle préfère la sortie la moins
        coûteuse quand deux existent            → il faut supprimer l'alternative

    Délier `ask_clarification` tranche : s'il se met alors à réclamer, il n'a
    jamais ignoré le catalogue — il suivait une règle implicite plus forte, « ne
    devine pas », que demander satisfait plus simplement que fouiller 105 lignes.
    """
    import time
    from datetime import datetime

    from langchain_core.messages import HumanMessage

    from src.orchestrator.catalogue import menu
    from src.orchestrator.graph import _ensure_system_prompt, _restreindre_les_skills

    retriever, obtenir_outil = monde
    print(f"\n━━ {titre} ━━")
    for requete, attendu in cas:
        selection = _restreindre_les_skills(
            retriever.get(requete), requete, "orchestrator") + [obtenir_outil]
        retire = delier | ({attendu} if delier_attendu else frozenset())
        selection = [t for t in selection if t.name not in retire]
        lies = {t.name for t in selection}

        messages = _ensure_system_prompt(
            [HumanMessage(content=requete)], selection,
            datetime.now().strftime("%Y-%m-%d"), catalogue=menu(),
        )
        llm = fabrique().bind_tools(selection)
        if pause:
            time.sleep(pause)
        try:
            reponse = _avec_reparation(llm, messages, selection, pause)
        except Exception as erreur:                              # noqa: BLE001
            print(f"   ERREUR   {type(erreur).__name__}: {str(erreur)[:70]}")
            continue

        verdict, detail = _classer(reponse, attendu, lies)
        if verdict in ("DIRECT", "JUSTE"):
            valides, mot = _arguments_valides(attendu, reponse)
            detail = f"{detail}  ·  {mot}" if mot else detail
            if not valides:
                repare, apres = _repare_sur_lerreur(llm, messages, reponse, attendu)
                verdict = "ARGS ✗→OK" if repare else "ARGS ✗"
                detail += f"\n              ↩ après refus de l'outil : {apres}"
        compte[verdict] = compte.get(verdict, 0) + 1
        deja = "  (déjà lié)" if attendu in lies else ""
        print(f"   {verdict:<10} attendu {attendu}{deja}")
        if detail:
            print(f"              → {detail}")
        print(f"              « {requete[:88]} »")


def main() -> None:
    analyseur = argparse.ArgumentParser(description="Mesure du filet de rattrapage.")
    analyseur.add_argument("--backend", default=None, help="forcer un backend")
    analyseur.add_argument("--pause", type=float, default=_PAUSE_PAR_DEFAUT,
                           help="secondes entre deux appels (0 pour enchaîner)")
    analyseur.add_argument("--delier", default="",
                           help="outils à retirer avant la liaison, séparés par des virgules "
                                "(ablation — ex. ask_clarification)")
    args = analyseur.parse_args()

    nom, fabrique = _backend(args.backend)
    from src.infra.settings import settings
    from src.llm.backends import champ_modele

    modele = getattr(settings, champ_modele(nom), "?")
    print(f"backend : {nom}   modèle : {modele}")

    delier = frozenset(n.strip() for n in args.delier.split(",") if n.strip())
    if delier:
        print(f"ABLATION : {', '.join(sorted(delier))} délié(s)")

    monde = _monde()
    decouverte: dict[str, int] = {}
    temoin: dict[str, int] = {}
    mesurer(DECOUVERTES, "LE FILET EST LA SEULE ISSUE", fabrique, monde, decouverte, delier, pause=args.pause)
    mesurer(TEMOINS, "TÉMOINS — le bon outil est déjà lié", fabrique, monde, temoin, delier, pause=args.pause)

    # L'ÉPREUVE PROPRE du filet. Les six `DECOUVERTES` sont toutes des demandes
    # VAGUES : on y mesurait l'ambiguïté de la requête, pas la vivacité de
    # l'échappatoire. Un catalogue ne répare pas une demande sous-spécifiée.
    # Ici la demande est limpide et l'outil qui la sert est RETIRÉ : c'est le
    # seul montage où réclamer est à la fois nécessaire et évident.
    ablation: dict[str, int] = {}
    mesurer(TEMOINS, "ÉPREUVE — demande claire, outil attendu RETIRÉ",
            fabrique, monde, ablation, delier, delier_attendu=True, pause=args.pause)

    riche: dict[str, int] = {}
    mesurer(SCHEMAS_RICHES, "SCHÉMA RICHE — outil RETIRÉ, signature non devinable",
            fabrique, monde, riche, delier, delier_attendu=True, pause=args.pause)

    n = len(DECOUVERTES)
    reclame = decouverte.get("RÉCLAMÉ", 0) + decouverte.get("RÉCLAMÉ ✗", 0)
    silencieux = decouverte.get("APPROXIMÉ", 0)
    print(f"\n━━ RÉSULTAT ━━  backend {nom}, modèle {modele}")
    print(f"   échappatoire utilisée   {reclame}/{n}"
          f"   ← la pièce dont dépend tout le rattrapage")
    print(f"   ÉCHECS SILENCIEUX       {silencieux}/{n}"
          f" = {100 * silencieux / n:.0f} %   ← un mauvais outil appelé avec assurance")
    rattrape = ablation.get("RÉCLAMÉ", 0) + ablation.get("DIRECT", 0)
    print(f"   ÉPREUVE PROPRE          {rattrape}/{len(TEMOINS)} rattrapés"
          f"   ← demande claire, outil RETIRÉ de la liaison")
    print(f"      dont par `obtenir_outil`  {ablation.get('RÉCLAMÉ', 0)}")
    print(f"      dont appel DIRECT au nom  {ablation.get('DIRECT', 0)}"
          f"   ← le `ToolNode` porte les 105 outils : la liaison trie, elle ne barre pas")
    print(f"   découvertes : {dict(sorted(decouverte.items()))}")
    print(f"   témoins     : {dict(sorted(temoin.items()))}")
    print(f"   épreuve     : {dict(sorted(ablation.items()))}")
    print(f"\n   SCHÉMA RICHE — l'appel à l'aveugle tient-il ?")
    print(f"      appel direct valide     {riche.get('DIRECT', 0) + riche.get('JUSTE', 0)}"
          f"/{len(SCHEMAS_RICHES)}")
    print(f"      invalide PUIS réparé    {riche.get('ARGS ✗→OK', 0)}"
          f"   ← le message pydantic a suffi, rien à construire")
    print(f"      invalide, resté faux    {riche.get('ARGS ✗', 0)}"
          f"   ← là seulement, empaqueter un schéma se justifie")
    print(f"      réclamé via l'échappatoire {riche.get('RÉCLAMÉ', 0)}")
    print(f"      détail : {dict(sorted(riche.items()))}")
    print("\nC'est le taux d'échecs silencieux que le plan doit faire descendre,"
          "\npas le rang 1 : un tour de plus n'est pas une erreur.")


if __name__ == "__main__":
    main()
