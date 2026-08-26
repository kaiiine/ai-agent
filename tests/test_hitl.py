"""Le protocole unique de demande à l'utilisateur.

AXON avait SIX mécanismes pour un seul besoin — questionnaire, confirmation de
mail, revue d'un fichier, d'une cellule, par lot, et approbation de plan — sur
sept points d'appel, tous dans `src/ui/streaming.py`. Aucun n'existait côté API :
le garde d'autorisation shell y posait une question que personne n'entendait.
"""
from __future__ import annotations

from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.orchestrator.hitl import (
    ACCORD,
    REFUS,
    Demande,
    Question,
    accorde,
    demande_en_attente,
    demander,
    normaliser,
    reponse,
)


# ── La règle du rejeu ────────────────────────────────────────────────────────
def test_ce_qui_precede_l_interruption_s_execute_DEUX_fois():
    """LA propriété qui commande tout le reste, et la seule qu'on ne peut pas
    deviner en lisant le code d'un nœud.

    Un fichier écrit, un mail envoyé, une commande lancée ou une autorisation
    inscrite avant l'appel a lieu deux fois. Ce test existe pour que la règle
    reste vraie — si LangGraph changeait ce comportement, tous les nœuds qui
    placent leurs effets APRÈS l'appel resteraient corrects, mais ceux qui
    comptent dessus dans l'autre sens ne le sauraient pas."""
    avant, apres = [], []

    class S(TypedDict):
        x: int

    def noeud(state):
        avant.append(1)
        rep = demander(Demande(genre="test", cle="k",
                               questions=(Question("Continuer ?"),)))
        apres.append(rep)
        return {"x": 1}

    g = StateGraph(S)
    g.add_node("n", noeud)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "rejeu"}}

    app.invoke({"x": 0}, cfg)
    app.invoke(Command(resume=[ACCORD]), cfg)

    assert len(avant) == 2, "le nœud n'est plus rejoué — vérifier la doc du module"
    assert len(apres) == 1, "ce qui suit l'interruption ne doit tourner qu'une fois"
    assert apres[0] == [ACCORD]


def test_un_effet_place_apres_l_appel_n_a_lieu_qu_une_fois():
    """Le motif recommandé, prouvé : demander, PUIS agir, dans le même nœud."""
    monde: list[str] = []

    class S(TypedDict):
        x: int

    def noeud(state):
        reps = demander(Demande(genre="autorisation", cle="rm -rf /tmp/x",
                                questions=(Question("Exécuter ?", ("Refuser", "Accorder")),)))
        if accorde(reps[0]):
            monde.append("exécuté")
        return {"x": 1}

    g = StateGraph(S)
    g.add_node("n", noeud)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "effet"}}

    app.invoke({"x": 0}, cfg)
    app.invoke(Command(resume=[ACCORD]), cfg)
    assert monde == ["exécuté"], f"effet dupliqué ou perdu : {monde}"


def test_un_refus_n_execute_rien():
    monde: list[str] = []

    class S(TypedDict):
        x: int

    def noeud(state):
        reps = demander(Demande(genre="autorisation", cle="rm -rf /tmp/x",
                                questions=(Question("Exécuter ?"),)))
        if accorde(reps[0]):
            monde.append("exécuté")
        return {"x": 1}

    g = StateGraph(S)
    g.add_node("n", noeud)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "refus"}}

    app.invoke({"x": 0}, cfg)
    app.invoke(Command(resume=[REFUS]), cfg)
    assert monde == []


# ── Le protocole ─────────────────────────────────────────────────────────────
def test_une_demande_survit_a_l_aller_retour_JSON():
    """Elle traverse un checkpoint SQLite et, un jour, le fil d'une API : une
    dataclass y survivrait en mémoire, pas sur le disque."""
    demande = Demande(
        genre="diff", cle="/tmp/f.py", apercu="- a\n+ b",
        extra={"hote": "vps"},
        questions=(Question("Appliquer ?", ("Refuser", "Accorder")),
                   Question("Un commentaire ?"),))
    assert Demande.depuis(demande.en_clair()) == demande


def test_le_client_lit_la_demande_dans_la_sortie_du_graphe():
    """Ce que TUI et API partagent — c'est cette lecture commune qui fait que le
    HITL cesse d'être une propriété de l'interface."""
    class S(TypedDict):
        x: int

    def noeud(state):
        demander(Demande(genre="clarification", cle="bankroll",
                         questions=(Question("Ta bankroll ?", ("50 €", "100 €")),)))
        return {"x": 1}

    g = StateGraph(S)
    g.add_node("n", noeud)
    g.add_edge(START, "n")
    g.add_edge("n", END)
    app = g.compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "lecture"}}

    sortie = app.invoke({"x": 0}, cfg)
    demande = demande_en_attente(sortie)

    assert demande is not None
    assert demande.genre == "clarification"
    assert demande.cle == "bankroll"
    assert demande.questions[0].choix == ("50 €", "100 €")

    app.invoke(reponse(["100 €"]), cfg)
    assert demande_en_attente(app.invoke(None, cfg)) is None


def test_une_sortie_sans_interruption_ne_rend_aucune_demande():
    assert demande_en_attente({"messages": []}) is None
    assert demande_en_attente(None) is None
    assert demande_en_attente({"__interrupt__": []}) is None


# ── Normalisation ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("brut, attendu", [
    ("oui", ["oui"]),
    (["a", "b"], ["a", "b"]),
    ({"q1": "a", "q0": "b"}, ["b", "a"]),      # trié par clé, ordre stable
    (None, [""]),
])
def test_les_formes_de_reponse_convergent(brut, attendu):
    """Les clients sont libres de leur forme. Normaliser ici plutôt que chez
    chaque producteur évite que le prochain client casse les précédents."""
    assert normaliser(brut) == attendu


def test_une_reponse_manquante_est_comblee_par_du_vide():
    """Et le vide vaut refus, pas accord."""
    reps = normaliser(["seule"], attendues=3)
    assert reps == ["seule", "", ""]
    assert not accorde(reps[1])


@pytest.mark.parametrize("brut, attendu", [
    (ACCORD, True), ("  Accord ", True), ("ACCORD", True),
    (REFUS, False), ("", False), ("peut-être", False), ("oui", False),
])
def test_seul_un_accord_explicite_vaut_accord(brut, attendu):
    """« Tout ce qui n'est pas non est oui » ferait d'une session interrompue,
    d'une fenêtre fermée ou d'un client en panne un accord que personne n'a
    donné."""
    assert accorde(brut) is attendu


@pytest.mark.parametrize("reponse, attendu", [
    ("Oui, exécuter", True), ("Non, annuler", False), ("", False),
])
def test_le_libelle_affiche_vaut_accord_quand_la_question_le_declare(reponse, attendu):
    """Un client renvoie ce qu'il a AFFICHÉ. La question déclare lequel de ses
    choix vaut accord — explicitement, et non par position : « le dernier est le
    oui » se retourne en silence le jour où quelqu'un réordonne la liste."""
    q = Question("Exécuter ?", ("Non, annuler", "Oui, exécuter"),
                 affirmatif="Oui, exécuter")
    assert accorde(reponse, q) is attendu


def test_reordonner_les_choix_ne_change_pas_le_verdict():
    q1 = Question("?", ("Non", "Oui"), affirmatif="Oui")
    q2 = Question("?", ("Oui", "Non"), affirmatif="Oui")
    assert accorde("Oui", q1) and accorde("Oui", q2)
    assert not accorde("Non", q1) and not accorde("Non", q2)


# ── Comment une décision revient au modèle ───────────────────────────────────
def test_une_decision_arrive_comme_une_ENTREE_pas_comme_une_reponse():
    """Vécu à l'écran, et c'est le seul bug que les tests n'ont pas attrapé.

    Le nœud d'envoi rendait un `AIMessage` portant « L'utilisateur n'a pas
    envoyé le mail et demande : fais un peu plus long ». Deux conséquences :

      - le TUI diffuse les `AIMessage`, donc la phrase a été AFFICHÉE telle
        quelle, comme si l'assistant s'adressait à l'utilisateur ;
      - le modèle a relu SON PROPRE tour lui annonçant une demande, au lieu de
        la recevoir. Il a répondu par un menu numéroté au lieu de refaire le
        brouillon.

    Une décision prise dans un questionnaire est une entrée de l'utilisateur —
    recueillie autrement qu'au clavier, mais la sienne.
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from src.orchestrator import confirmation, envoi, revision

    for module in (envoi, revision, confirmation):
        assert isinstance(module.note_pour_le_modele("x"), HumanMessage), (
            f"{module.__name__} renvoie ses décisions comme un message d'assistant")
        assert not isinstance(module.note_pour_le_modele("x"), AIMessage)


def test_un_refus_dit_au_modele_QUOI_FAIRE_pas_seulement_ce_qui_s_est_passe():
    """Constater ne suffit pas. Face à « l'utilisateur demande X », le modèle a
    redemandé quoi faire — il lui manquait l'ordre, pas l'information."""
    import json
    from typing import TypedDict

    from langchain_core.messages import ToolMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, START, StateGraph

    from src.agents.shell import autorisation
    from src.orchestrator.confirmation import NON, confirmer

    class Etat(TypedDict):
        messages: list

    autorisation.reinitialiser()
    g = StateGraph(Etat)
    g.add_node("c", confirmer)
    g.add_edge(START, "c")
    g.add_edge("c", END)
    app = g.compile(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "consigne"}}

    demande = ToolMessage(
        content=json.dumps({"status": "requires_confirmation",
                            "command": "rm -rf /tmp/x", "reason": "destructive"}),
        tool_call_id="tc", name="shell_run")
    app.invoke({"messages": [demande]}, cfg)
    finale = app.invoke(Command(resume=[NON]), cfg)

    texte = finale["messages"][-1].content.lower()
    assert "refus" in texte, "le fait doit être dit"
    assert "relance pas" in texte or "propose" in texte, (
        "sans consigne, le modèle constate et redemande quoi faire")


def test_aucun_outil_n_interrompt_le_graphe():
    """Un outil est une unité ATOMIQUE : `interrupt()` appelé depuis un outil
    rejoue tout ce que l'outil a fait avant.

    Pour `run_coding_agent`, cela voudrait dire quarante appels LLM et des
    fichiers déjà écrits, refaits de zéro. Mesuré sur un graphe jouet : un outil
    qui interrompt s'exécute DEUX fois ; le même travail suivi d'un nœud qui
    interrompt s'exécute UNE fois.

    Le specialist respecte la règle sans le dire — il empile dans
    `pending_changes` et rend la main. Ce test rend la règle explicite, pour que
    le prochain qui voudra « juste poser une petite question depuis l'outil » se
    heurte à un échec plutôt qu'à un bug de production.
    """
    import pathlib

    racine = pathlib.Path(__file__).resolve().parents[1] / "src"
    fautifs: list[str] = []
    for fichier in racine.rglob("*.py"):
        # Les nœuds du graphe ONT le droit — c'est leur rôle.
        if fichier.parent.name == "orchestrator" and fichier.stem in (
                "hitl", "clarification", "confirmation", "revision", "envoi"):
            continue
        texte = fichier.read_text(encoding="utf-8", errors="replace")
        if "@tool(" not in texte:
            continue
        if "interrupt(" in texte or "hitl import" in texte or "demander(" in texte:
            fautifs.append(str(fichier.relative_to(racine)))

    assert not fautifs, (
        "des modules exposant des outils interrompent le graphe — leur travail "
        f"sera rejoué à chaque reprise : {fautifs}")
