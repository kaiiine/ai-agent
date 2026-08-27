"""L'agent de code comme sous-graphe : demander sans tout rejouer.

Il tournait dans une boucle ordinaire, à l'intérieur d'un outil. Un outil est
atomique pour le moteur : interrompre depuis là rejoue tout son travail. Mesuré —
une étape déjà faite s'exécutait DEUX fois à la reprise. C'est pour ça qu'il ne
demandait jamais rien : demander aurait réécrit les fichiers et relancé les
commandes déjà passées.

Compilé sans checkpointer, ce graphe hérite de celui du parent. Vérifié depuis un
outil exécuté par le `ToolNode` : l'`interrupt()` remonte, et la reprise continue
au lieu de recommencer.

    trace : ['outil-entree', 'travail-lourd', 'outil-entree', 'apres-accord:oui']

L'enveloppe de l'outil est ré-entrée — c'est inévitable — mais l'étape
checkpointée, non. D'où la règle qui gouverne le découpage ci-dessous : **tout ce
qui coûte est un nœud**. `enrich_task` est un appel modèle ; le laisser dans
l'enveloppe le ferait payer deux fois à chaque confirmation.
"""
from __future__ import annotations

import operator
import uuid
from typing import Annotated, Any, Callable

from langchain_core.messages import (
    AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from typing_extensions import TypedDict

from src.orchestrator import hitl

#: Au-delà, on rend la main plutôt que de tourner. Repris de la boucle d'origine.
TOURS_MAX = 80

#: Ce qu'un outil rend quand il refuse faute d'accord.
_STATUTS_A_CONFIRMER = ("requires_confirmation",)

#: Ce que rend l'outil de délégation : le graphe l'intercepte au lieu de le
#: laisser filer au modèle, exactement comme `deep_research` côté orchestrateur.
MARQUEUR_DELEGATION = "deleguer"

#: Au-delà, on refuse d'éclater : dix explorations parallèles coûtent dix
#: contextes, et le modèle ne sait plus quoi faire du rapport.
SOUS_TACHES_MAX = 4

#: Tours accordés à une exploration. Elle rapporte, elle ne construit pas.
TOURS_SOUS_TACHE = 6


class EtatCode(TypedDict, total=False):
    """Tout ce qui doit survivre à une interruption.

    Rien d'autre : le client LLM et le retriever se reconstruisent à chaque nœud
    (l'un est un objet vide, l'autre est mis en cache globalement), et un objet
    non sérialisable dans l'état empêcherait le checkpoint.
    """
    tache: str
    tache_enrichie: str
    messages: Annotated[list, add_messages]
    fournisseur: str
    tours: int
    appels_outils: int
    #: Ce que l'utilisateur a injecté en cours de route, consommé au tour suivant.
    redirection: str
    #: Rempli une seule fois, à la fin.
    resultat: str
    abandon: str
    #: Le modèle a conclu — plan achevé, ou aucun plan à achever.
    fini: bool
    #: Le plan a déjà été soumis. Un plan révisé rouvre la question, pas un
    #: simple pas de plus.
    plan_vu: str
    #: Ce que les explorations parallèles ont rapporté.
    trouvailles: Annotated[list[dict], operator.add]
    #: L'appel de délégation en cours, à qui rendre le rapport.
    appel_delegue: str
    #: Les sujets à explorer en parallèle, posés par le nœud d'outils.
    a_deleguer: list[str]
    #: L'appel qui attend un accord. Posé par `outils`, consommé par `confirmer`.
    en_attente: dict | None


#: Ce que l'utilisateur veut dire à l'agent SANS attendre qu'il ait fini.
#
# Le sous-graphe checkpointe ses pas : une consigne déposée ici est lue au tour
# suivant, et le travail déjà fait n'est pas rejoué. C'est ce que la boucle
# d'origine ne pouvait pas offrir — elle n'avait aucun point où reprendre.
_boite: list[str] = []


def rediriger(consigne: str) -> None:
    """Dépose une consigne que l'agent lira à son prochain tour."""
    consigne = (consigne or "").strip()
    if consigne:
        _boite.append(consigne)


def consignes_en_attente() -> int:
    return len(_boite)


def _relever() -> str:
    """Vide la boîte. Plusieurs consignes se lisent d'un coup, dans l'ordre."""
    if not _boite:
        return ""
    tout = " Puis : ".join(_boite)
    _boite.clear()
    return tout


def _texte(message: Any) -> str:
    contenu = getattr(message, "content", "")
    return contenu if isinstance(contenu, str) else str(contenu)


def construire(
    *,
    outils: list,
    selectionner: Callable[[list, str], list],
    appeler_modele: Callable[[list, list, str], tuple[Any, str]],
    enrichir: Callable[[str], str],
    prompt_systeme: str,
    executer: Callable[[str, dict], Any],
    tracer: Callable[[list], str],
    #: Ce qui part en contexte pour un résultat d'outil. Un `local_read_file` sur
    #: un gros fichier remplit la fenêtre à lui seul : la troncature est une
    #: politique, elle reste injectée.
    rendre: Callable[[Any], str] = str,
    #: Les outils qu'une exploration déléguée a le droit d'appeler. LECTURE
    #: SEULE, délibérément : une sous-tâche tourne sous `Send`, où une
    #: interruption ne peut pas remonter proprement — donc rien qui exigerait un
    #: accord. Elle rapporte, elle ne construit pas.
    outils_exploration: list | None = None,
    #: Ce que le specialist fait d'une réponse : récupérer un appel écrit en
    #: JSON, décider si le plan permet de conclure, relancer sur un plan
    #: inachevé. Rend `(appels, fini, rappel)`.
    interpreter: Callable[[Any, list], tuple[list, bool, str]] = lambda r, m: (
        list(getattr(r, "tool_calls", None) or []), not getattr(r, "tool_calls", None), ""),
    notifier: Callable[[str, dict | None], None] = lambda *_: None,
):
    """Le sous-graphe compilé.

    Tout ce qui décide est injecté : ce module porte la STRUCTURE — quels pas
    sont checkpointés, où l'on peut interrompre — et rien de la politique, qui
    reste dans `specialist.py` où elle a été réglée.
    """
    par_nom = {o.name: o for o in outils}

    # ── les nœuds ────────────────────────────────────────────────────────────
    def preparer(etat: EtatCode) -> dict:
        """L'enrichissement est un appel modèle : il doit être checkpointé."""
        enrichie = enrichir(etat["tache"])
        return {
            "tache_enrichie": enrichie,
            "messages": [SystemMessage(prompt_systeme), HumanMessage(enrichie)],
            "tours": 0,
            "appels_outils": 0,
        }

    def modele(etat: EtatCode) -> dict:
        messages = list(etat["messages"])

        # Une redirection est une consigne, pas une réponse : elle arrive comme
        # message humain pour que le modèle la lise comme telle, et elle est
        # vidée pour ne pas se rejouer au tour suivant.
        #
        # La boîte est relevée ICI, au plus tard : une consigne déposée pendant
        # qu'un outil tournait est ainsi prise en compte au tour suivant, sans
        # avoir à interrompre quoi que ce soit.
        etat = {**etat, "redirection": etat.get("redirection") or _relever()}
        ajouts: list = []
        if etat.get("redirection"):
            ajouts.append(HumanMessage(
                f"[UTILISATEUR, en cours de route] {etat['redirection']}\n"
                "Tiens-en compte immédiatement : abandonne ce qui devient inutile."))
            messages = messages + ajouts

        actifs = selectionner(messages, etat.get("tache_enrichie", ""))
        reponse, echec, utilises = appeler_modele(messages, actifs, etat.get("fournisseur", ""))
        if reponse is None:
            return {"messages": ajouts, "abandon": echec or "Aucune réponse du modèle.",
                    "redirection": ""}

        # Une compression a remplacé la liste : l'état doit suivre, sinon le tour
        # suivant repart du transcript non compressé et rebute sur la même limite.
        prefixe: list = []
        if utilises is not None and len(utilises) < len(messages):
            prefixe = [RemoveMessage(id=REMOVE_ALL_MESSAGES)] + list(utilises)
            ajouts = []

        appels, fini, rappel = interpreter(reponse, utilises if utilises is not None else messages)
        suite: list = [reponse]
        if appels and not getattr(reponse, "tool_calls", None):
            # L'appel était écrit en JSON : le déclarer dans l'AIMessage, sinon
            # Mistral voit des paires déséquilibrées.
            suite = [AIMessage(content="", tool_calls=appels)]
        if rappel:
            suite.append(HumanMessage(rappel))

        return {"messages": prefixe + ajouts + suite,
                "fournisseur": getattr(reponse, "_fournisseur", etat.get("fournisseur", "")),
                "tours": etat.get("tours", 0) + 1,
                "fini": fini and not appels,
                "redirection": ""}

    def noeud_outils(etat: EtatCode) -> dict:
        """Exécute, et s'ARRÊTE sur ce qui demande un accord.

        Chaque appel est traité l'un après l'autre, et le résultat est écrit dans
        l'état AVANT de demander : sans ça, la confirmation rejouerait les appels
        déjà exécutés du même lot.
        """
        # Le DERNIER AIMessage porteur d'appels, pas le dernier message : on
        # repasse ici après une confirmation, et l'état se termine alors par les
        # réponses déjà obtenues du même lot.
        porteur = next((m for m in reversed(etat["messages"])
                        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None)), None)
        appels = list(getattr(porteur, "tool_calls", None) or []) if porteur else []
        deja = {m.tool_call_id for m in etat["messages"] if isinstance(m, ToolMessage)}
        rendus: list = []
        a_deleguer: list[str] = []
        appel_delegue = ""

        for appel in appels:
            if appel["id"] in deja:
                continue
            nom, args = appel["name"], appel.get("args") or {}
            resultat = executer(nom, args)

            if isinstance(resultat, dict) and resultat.get("status") in _STATUTS_A_CONFIRMER:
                # On NE demande PAS ici. Ce qui précède un `interrupt()` dans le
                # même nœud s'exécute deux fois à la reprise : l'outil serait
                # rejoué avant la question. Inoffensif pour une commande refusée
                # d'emblée, pas pour un outil qui agit à moitié avant de buter.
                # La question part donc d'un nœud séparé, déjà checkpointé.
                return {"messages": rendus,
                        "en_attente": {"id": appel["id"], "nom": nom,
                                       "commande": str(resultat.get("command") or ""),
                                       "message": str(resultat.get("message") or ""),
                                       "raison": str(resultat.get("reason") or "")},
                        "appels_outils": etat.get("appels_outils", 0) + len(rendus)}

            # La délégation ne rend rien tout de suite : l'éventail s'ouvre, et
            # `rassembler` écrira LE message de réponse. Émettre un ToolMessage
            # ici laisserait deux réponses pour un seul appel.
            if isinstance(resultat, dict) and resultat.get("status") == MARQUEUR_DELEGATION:
                sujets = [str(t).strip() for t in (resultat.get("taches") or []) if str(t).strip()]
                a_deleguer = sujets[:SOUS_TACHES_MAX]
                appel_delegue = appel["id"]
                notifier("specialist:delegation", {"taches": a_deleguer})
                continue

            rendus.append(ToolMessage(content=rendre(resultat), tool_call_id=appel["id"],
                                      name=nom))
            notifier("specialist:tool", {"nom": nom})

        return {"messages": rendus,
                "a_deleguer": a_deleguer,
                "appel_delegue": appel_delegue,
                "appels_outils": etat.get("appels_outils", 0) + len(rendus)}

    def confirmer(etat: EtatCode) -> dict:
        """Rien d'autre que la question. Ce nœud peut être rejoué sans dommage."""
        demande = etat.get("en_attente") or {}
        question = hitl.Question(
            texte=demande.get("message") or f"{demande.get('nom')} demande une confirmation.",
            choix=("Non, annuler", "Oui, exécuter"),
            affirmatif="Oui, exécuter")
        reponses = hitl.demander(hitl.Demande(
            genre=hitl.AUTORISATION,
            cle=demande.get("commande") or demande.get("nom", ""),
            questions=(question,),
            apercu=demande.get("commande", ""),
            extra={"outil": demande.get("nom", ""), "raison": demande.get("raison", "")},
        ))

        # ── après l'interruption : exécuté une seule fois ────────────────────
        # La QUESTION est passée à `accorde` : sans elle, seul le jeton interne
        # vaut accord et « Oui, exécuter » était lu comme un refus.
        if hitl.accorde(reponses[0] if reponses else "", question):
            if demande.get("commande"):
                from src.agents.shell.autorisation import accorder
                accorder(demande["commande"])
            # L'appel repart par le nœud d'outils : il n'a pas encore de réponse,
            # donc il sera repris — et cette fois l'accord est acquis.
            return {"en_attente": None}
        return {"en_attente": None, "messages": [ToolMessage(
            content=rendre({"status": "refused",
                            "error": "L'utilisateur a refusé. Ne redemande pas la même "
                                     "chose : change de voie ou termine."}),
            tool_call_id=demande.get("id", "?"), name=demande.get("nom", "?"))]}

    def explorer(charge: dict) -> dict:
        """Une exploration déléguée : son propre contexte, son propre budget.

        Le modèle principal garde un fil court — il reçoit un rapport, pas les
        vingt lectures qui l'ont produit. C'est là qu'est le gain : la
        délégation n'accélère rien, elle DÉCHARGE le contexte.
        """
        sujet = charge["sujet"]
        lisibles = outils_exploration if outils_exploration is not None else []
        fil: list = [
            SystemMessage(
                "Tu explores un point précis pour un agent de code. Tu LIS et tu "
                "rapportes ; tu n'écris rien et tu ne lances rien. Termine par un "
                "compte rendu court et factuel, chemins et noms exacts inclus."),
            HumanMessage(sujet),
        ]
        for _ in range(TOURS_SOUS_TACHE):
            reponse, echec, utilises = appeler_modele(fil, lisibles, "")
            if reponse is None:
                return {"trouvailles": [{"sujet": sujet,
                                         "rapport": f"[exploration échouée : {echec}]"}]}
            fil = list(utilises or fil) + [reponse]
            appels = list(getattr(reponse, "tool_calls", None) or [])
            if not appels:
                return {"trouvailles": [{"sujet": sujet, "rapport": _texte(reponse)}]}
            noms_lisibles = {o.name for o in lisibles}
            for appel in appels:
                nom = appel["name"]
                resultat = (executer(nom, appel.get("args") or {}) if nom in noms_lisibles
                            else {"status": "error",
                                  "error": f"`{nom}` n'est pas disponible en exploration : "
                                           "tu lis et tu rapportes."})
                fil.append(ToolMessage(content=rendre(resultat),
                                       tool_call_id=appel["id"], name=nom))
        return {"trouvailles": [{"sujet": sujet,
                                 "rapport": "[exploration close — budget de tours épuisé]"}]}

    def rassembler(etat: EtatCode) -> dict:
        """Un seul message pour tout l'éventail, à la place de l'appel délégué."""
        rapports = etat.get("trouvailles") or []
        corps = "\n\n".join(f"### {t['sujet']}\n{t['rapport']}" for t in rapports)
        return {"messages": [ToolMessage(
            content=rendre(corps or "Aucune exploration n'a abouti."),
            tool_call_id=etat.get("appel_delegue") or "delegation",
            name=MARQUEUR_DELEGATION)],
            "trouvailles": []}

    def valider_le_plan(etat: EtatCode) -> dict:
        """Le plan existait déjà, mais restait interne : il défilait dans la trace
        sans que personne puisse le corriger avant qu'il ne soit suivi.

        Rouvert à chaque plan DIFFÉRENT, pas à chaque étape cochée — sinon on
        redemanderait la même chose à tous les tours.
        """
        from src.agents.coding.pending import dev_plan

        etapes = [e.label for e in dev_plan.steps]
        signature = " | ".join(etapes)
        apercu = "\n".join(f"{i}. {label}" for i, label in enumerate(etapes, 1))

        reponses = hitl.demander(hitl.Demande(
            genre=hitl.PLAN,
            cle=signature[:80],
            apercu=apercu,
            questions=(
                hitl.Question(texte="Ce plan te convient ?",
                              choix=("Abandonner", "Préciser", "Exécuter"),
                              affirmatif="Exécuter"),
                hitl.Question(texte="Que faut-il changer ?"),
            ),
        ))

        # ── après l'interruption : exécuté une seule fois ────────────────────
        decision = (reponses[0] or "").strip()
        precision = (reponses[1] or "").strip() if len(reponses) > 1 else ""

        if decision == "Exécuter" or not decision:
            return {"plan_vu": signature}
        if decision == "Préciser" and precision:
            return {"plan_vu": signature, "messages": [HumanMessage(
                f"[UTILISATEUR] Le plan n'est pas validé. {precision}. Appelle "
                f"`dev_plan_update` avec un plan révisé qui en tient compte, "
                f"avant de continuer.")]}
        return {"plan_vu": signature, "fini": True,
                "messages": [HumanMessage(
                    "[UTILISATEUR] Plan abandonné. N'exécute rien de plus et "
                    "explique ce que tu comptais faire.")]}

    def finir(etat: EtatCode) -> dict:
        if etat.get("abandon"):
            return {"resultat": etat["abandon"]}
        dernier = next((m for m in reversed(etat["messages"]) if isinstance(m, AIMessage)),
                       None)
        return {"resultat": tracer(etat["messages"]) + (_texte(dernier) if dernier else "")}

    # ── les arêtes ───────────────────────────────────────────────────────────
    def apres_les_outils(etat: EtatCode):
        """L'éventail d'abord, puis le plan neuf, puis le tour suivant."""
        from src.agents.coding.pending import dev_plan

        if etat.get("en_attente"):
            return "confirmer"
        if etat.get("a_deleguer"):
            return [Send("explorer", {"sujet": sujet}) for sujet in etat["a_deleguer"]]
        if not dev_plan.steps:
            return "modele"
        signature = " | ".join(e.label for e in dev_plan.steps)
        return "modele" if signature == etat.get("plan_vu") else "valider_le_plan"

    def apres_le_modele(etat: EtatCode) -> str:
        if etat.get("abandon"):
            return "finir"
        if etat.get("tours", 0) >= TOURS_MAX:
            return "finir"
        if etat.get("fini"):
            return "finir"
        dernier = etat["messages"][-1]
        if getattr(dernier, "tool_calls", None):
            return "outils"
        # Ni appel ni conclusion : un rappel vient d'être posé, on relance.
        return "modele" if isinstance(dernier, HumanMessage) else "finir"

    g = StateGraph(EtatCode)
    g.add_node("preparer", preparer)
    g.add_node("modele", modele)
    g.add_node("outils", noeud_outils)
    g.add_node("confirmer", confirmer)
    g.add_node("explorer", explorer)
    g.add_node("rassembler", rassembler)
    g.add_node("valider_le_plan", valider_le_plan)
    g.add_node("finir", finir)

    g.add_edge(START, "preparer")
    g.add_edge("preparer", "modele")
    g.add_conditional_edges("modele", apres_le_modele,
                            {"outils": "outils", "finir": "finir", "modele": "modele"})
    g.add_conditional_edges("outils", apres_les_outils,
                            {"modele": "modele", "valider_le_plan": "valider_le_plan",
                             "explorer": "explorer", "confirmer": "confirmer"})
    # Retour aux outils : l'appel accordé n'a pas de réponse, il sera repris ;
    # l'appel refusé en a une, et la boucle passe au tour suivant.
    g.add_edge("confirmer", "outils")
    g.add_edge("explorer", "rassembler")
    g.add_edge("rassembler", "modele")
    g.add_conditional_edges("valider_le_plan",
                            lambda e: "finir" if e.get("fini") else "modele",
                            {"modele": "modele", "finir": "finir"})
    g.add_edge("finir", END)

    # SANS checkpointer : il hérite de celui du parent, et ses pas sont
    # checkpointés dans le même fil. Lui en donner un l'isolerait, et
    # l'interruption ne remonterait plus.
    return g.compile()
