"""Le journal branché sur la VRAIE région `Live` de `streaming.py`.

Ce fichier existe à cause d'un échec précis. La première tentative remplaçait le
`Live` de `streaming` par une façade maison ; sa méthode `stop()` vidait la zone
au lieu de l'arrêter, et `finalize_live` — qui compte sur un arrêt réel pour
imprimer EN DESSOUS — s'est mise à imprimer par-dessus une région encore vivante.
La réponse s'affichait en double et la saisie suivante devenait invisible.

La leçon tient en une règle, et ces tests la gardent :

    l'animation possède la ligne vivante   → elle seule appelle `live.update`
    le journal possède les lignes finies   → il n'appelle que `console.print`

Un seul peintre par toile. Les tests ci-dessous vérifient donc la cohabitation
avec un `Live` réellement démarré, pas avec un doublon de test — c'est justement
ce que le doublon ne montrait pas.
"""
import io

import pytest
from rich.console import Console
from rich.live import Live
from rich.text import Text

from src.ui.journal import (
    Journal, SortieDirecte, inscrire_resultat, lignes_sources, sources_de,
)


def _console() -> Console:
    return Console(file=io.StringIO(), width=100, force_terminal=True)


def _sortie(console: Console) -> str:
    return console.file.getvalue()


def _ecran(console: Console) -> str:
    """Ce qui reste VISIBLE après rejeu des séquences ANSI d'effacement."""
    from tests.emulateur_terminal import _ecran as _e
    return _e(console)


#: Un rapport de recherche tel que `web_research_report` le produit vraiment —
#: format relu dans `src/agents/search/tools.py`, pas inventé pour le test.
RAPPORT = """# Recherche : dernières versions de LangGraph

## Sources
1. **LangGraph 0.6 release notes** — _github.com · 2026-07-02_
2. **Migrating to LangGraph 0.6** — _langchain.com · 2026-07-10_
3. **What changed in LangGraph** — _blog.langchain.dev_ _(DDG)_
4. **LangGraph checkpointers** — _python.langchain.com_
5. **Discussion #4412** — _github.com_
"""


# ── Lire les sources d'un rapport ─────────────────────────────────────────────
def test_les_domaines_sont_extraits_du_rapport():
    """« Où est-il allé chercher ça ? » est la question qu'on se pose devant une
    recherche web — et à laquelle « ✓ searching » ne répond pas."""
    sources = sources_de(RAPPORT)

    assert [d for d, _ in sources] == [
        "github.com", "langchain.com", "blog.langchain.dev", "python.langchain.com",
    ]


def test_le_titre_accompagne_le_domaine():
    assert sources_de(RAPPORT)[0][1] == "LangGraph 0.6 release notes"


def test_la_liste_est_bornee():
    """Au-delà, les sources chassent la réponse hors de l'écran."""
    assert len(sources_de(RAPPORT)) == 4


def test_un_texte_sans_sources_n_en_invente_pas():
    assert sources_de("exit 0\nrien à signaler") == []


def test_le_reste_est_compte_pas_liste():
    lignes = lignes_sources(sources_de(RAPPORT), total=5)

    assert "et 1 autre(s) source(s)" in lignes[-1].plain


def test_la_derniere_ligne_ferme_l_embranchement():
    """Le coin fermant ne se pose que si plus rien ne suit — sinon il ment."""
    lignes = lignes_sources(sources_de(RAPPORT), total=4)

    assert "╰─" in lignes[-1].plain
    assert all("├─" in l.plain for l in lignes[:-1])


# ── Ce que l'utilisateur voit ─────────────────────────────────────────────────
def test_une_recherche_montre_les_sites_visites():
    console = _console()
    j = Journal(SortieDirecte(console))

    inscrire_resultat(j, "web_research_report", type("M", (), {"content": RAPPORT})())

    ecran = _ecran(console)
    assert "searching" in ecran
    assert "github.com" in ecran and "langchain.com" in ecran


def test_la_requete_devient_la_cible_de_la_ligne():
    """« searching » sans dire QUOI ne vaut guère mieux que
    « thinking » — c'est exactement le reproche fait à l'affichage d'avant."""
    j = Journal()
    inscrire_resultat(j, "web_research_report", type("M", (), {"content": RAPPORT})())

    assert "LangGraph" in j.actions[0].cible


def test_une_recherche_echouee_ne_liste_rien():
    """Il n'y a pas de site visité quand la recherche a échoué : en afficher
    serait affirmer un travail qui n'a pas eu lieu."""
    console = _console()
    j = Journal(SortieDirecte(console))

    inscrire_resultat(j, "web_research_report",
                      type("M", (), {"content": '{"status": "error", "message": "429"}'})())

    assert "github.com" not in _sortie(console)
    assert "429" in _ecran(console)


# ── Cohabitation avec la région vivante ───────────────────────────────────────
def test_les_lignes_survivent_a_l_animation():
    """Le défaut d'origine : l'appel d'outil était POSÉ dans le `Live`, donc
    écrasé par l'image d'animation suivante. On voyait l'outil passer sans
    jamais pouvoir y revenir."""
    console = _console()
    j = Journal(SortieDirecte(console))

    with Live(Text("thinking"), console=console, refresh_per_second=4) as live:
        inscrire_resultat(j, "local_read_file", type("M", (), {"content": "/src/app.tsx"})())
        for _ in range(10):
            live.update(Text("thinking"))     # l'animation repeint sa ligne

    assert "app.tsx" in _ecran(console), "la ligne finie doit rester lisible"


def test_l_animation_ne_s_empile_pas():
    """Le symptôme que l'utilisateur a signalé : `thinking` imprimé en escalier
    au lieu d'être redessiné sur place."""
    console = _console()
    j = Journal(SortieDirecte(console))

    with Live(Text(""), console=console, refresh_per_second=4) as live:
        for i in range(12):
            live.update(Text("thinking"))
            if i == 5:
                inscrire_resultat(j, "shell_run", type("M", (), {"content": "exit 0"})())

    assert _ecran(console).count("thinking") <= 1


def test_le_journal_n_ecrit_jamais_dans_la_region_vivante():
    """La règle structurelle, vérifiée directement : `poser` est sans effet.

    C'est ce qui garantit qu'il n'y a qu'un seul peintre. Si un jour quelqu'un
    rend `poser` actif, ce test tombe avant que l'affichage ne casse chez
    l'utilisateur — l'ordre inverse de ce qui s'est produit.
    """
    console = _console()
    sortie = SortieDirecte(console)

    sortie.poser(Text("ne doit pas sortir"))

    assert "ne doit pas sortir" not in _sortie(console)


def test_dix_outils_donnent_dix_lignes_durables():
    console = _console()
    j = Journal(SortieDirecte(console))

    with Live(Text(""), console=console, refresh_per_second=4) as live:
        for i in range(10):
            inscrire_resultat(j, "local_read_file",
                              type("M", (), {"content": f"/src/f{i}.ts"})())
            live.update(Text("thinking"))

    ecran = _ecran(console)
    for i in range(10):
        assert f"f{i}.ts" in ecran


# ── Robustesse ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("contenu", ["", "   ", "# Recherche :", "1. **" , "─" * 500])
def test_un_rapport_degenere_ne_leve_pas(contenu):
    """Un journal qui casse le tour qu'il raconte serait pire que pas de
    journal."""
    inscrire_resultat(Journal(), "web_research_report",
                      type("M", (), {"content": contenu})())


def test_une_console_hostile_ne_casse_pas_le_tour():
    class Hostile:
        def print(self, *a, **k):
            raise RuntimeError("terminal fermé")

    j = Journal(SortieDirecte(Hostile()))
    inscrire_resultat(j, "shell_run", type("M", (), {"content": "exit 0"})())

    assert len(j.actions) == 1, "l'action est tenue même si l'écran refuse"


# ── Les deux chemins conversationnels, pas un seul ────────────────────────────
#
# Erreur commise et corrigée ici : le journal n'avait été branché que dans
# `_stream_message`, alors que la conversation ordinaire passe par `stream_once`.
# Les tests passaient, et l'écran affichait toujours `web_research_report` brut.
# Un test de comportement ne pouvait pas le voir — il aurait fallu un vrai
# terminal et un vrai modèle. L'appartenance du branchement, elle, se lit.

@pytest.mark.parametrize("fonction", ["stream_once", "_stream_message"])
def test_chaque_chemin_conversationnel_inscrit_ses_actions(fonction):
    import inspect

    from src.ui import streaming

    # Normalisé : le test porte sur le branchement, pas sur la façon dont il
    # est coupé en lignes — c'est le reformatage de l'appel qui l'a fait tomber
    # une première fois, sans qu'aucun comportement n'ait changé.
    source = " ".join(inspect.getsource(getattr(streaming, fonction)).split())

    assert "inscrire_resultat( journal" in source or "inscrire_resultat(journal" in source, (
        f"{fonction} affiche des outils sans les inscrire au journal")


@pytest.mark.parametrize("fonction", ["stream_once", "_stream_message"])
def test_aucun_chemin_ne_pose_l_appel_d_outil_dans_la_region(fonction):
    """La règle qui tient tout : ce qui doit rester ne se pose pas, il s'imprime.

    `tool_call_panel` posé dans le `Live` était écrasé par l'image d'animation
    suivante. Il subsiste pour `run_coding_agent`, qui n'est pas une action
    ponctuelle mais un basculement d'affichage — d'où la tolérance explicite.
    """
    import inspect

    from src.ui import streaming

    source = inspect.getsource(getattr(streaming, fonction))
    poses = [l.strip() for l in source.splitlines()
             if "live.update(tool_call_panel(" in l]

    assert all("run_coding_agent" in l for l in poses), (
        f"{fonction} pose encore un appel d'outil dans la région vivante : {poses}")


@pytest.mark.parametrize("fonction", ["stream_once", "_stream_message"])
def test_l_attente_annonce_l_outil_en_cours(fonction):
    """Sans ça, `stream_once` affichait « thinking » quoi qu'Axon fasse —
    exactement le reproche à l'origine de ce chantier."""
    import inspect

    from src.ui import streaming

    source = inspect.getsource(getattr(streaming, fonction))

    assert 'activity["label"] = verbe(' in source


# ── La cible vient de l'APPEL, pas du résultat ────────────────────────────────
#
# Vu à l'écran : deux appels parallèles de `web_search_news` donnaient deux
# lignes « ✓ searching » rigoureusement indiscernables. Le verbe seul
# ne suffit pas — il faut dire sur QUOI porte chaque appel, et cette information
# n'existe de façon fiable que dans les arguments.

def test_la_cible_est_lue_dans_les_arguments():
    from src.ui.journal import cible_de_l_appel

    assert cible_de_l_appel({"query": "LangGraph 2026"}) == "LangGraph 2026"
    assert cible_de_l_appel({"file_path": "/src/app.tsx"}) == "/src/app.tsx"
    assert cible_de_l_appel({"url": "https://x.dev"}) == "https://x.dev"


def test_un_appel_sans_argument_parlant_n_invente_pas_de_cible():
    from src.ui.journal import cible_de_l_appel

    assert cible_de_l_appel({"max_results": 10}) == ""
    assert cible_de_l_appel(None) == ""
    assert cible_de_l_appel("pas un dict") == ""


def test_la_cible_de_l_appel_prime_sur_celle_du_resultat():
    """L'une est exacte, l'autre est une heuristique de repli."""
    j = Journal()
    inscrire_resultat(j, "web_research_report",
                      type("M", (), {"content": RAPPORT})(),
                      cible_connue="ma requête exacte")

    assert j.actions[0].cible == "ma requête exacte"


def test_deux_appels_du_meme_outil_restent_distinguables():
    """Le défaut exact observé, en une assertion."""
    console = _console()
    j = Journal(SortieDirecte(console))

    inscrire_resultat(j, "web_search_news", type("M", (), {"content": "ok"})(),
                      cible_connue="LangGraph 2026")
    inscrire_resultat(j, "web_search_news", type("M", (), {"content": "ok"})(),
                      cible_connue="LangGraph checkpointers")

    ecran = _ecran(console)
    assert "LangGraph 2026" in ecran and "LangGraph checkpointers" in ecran


@pytest.mark.parametrize("fonction", ["stream_once", "_stream_message"])
def test_les_cibles_sont_appariees_par_identifiant_d_appel(fonction):
    """Une table indexée par NOM d'outil perdrait l'un des deux appels
    parallèles ; `tool_call_id` les sépare."""
    import inspect

    from src.ui import streaming

    source = inspect.getsource(getattr(streaming, fonction))

    assert 'cibles.pop(getattr(msg, "tool_call_id"' in source, (
        f"{fonction} n'apparie pas les cibles par identifiant d'appel")


def test_un_titre_coupe_le_dit():
    """Sans les points de suspension on lit « …with watso » et on croit à un
    défaut d'affichage plutôt qu'à une coupe voulue — vu à l'écran."""
    long = "Bring your LangGraph Agents to production with watsonx Orchestrate today"
    lignes = lignes_sources([("www.ibm.com", long)], total=1)

    assert lignes[0].plain.rstrip().endswith("…")


def test_un_titre_court_n_est_pas_touche():
    lignes = lignes_sources([("x.dev", "Titre court")], total=1)

    assert lignes[0].plain.rstrip().endswith("Titre court")


# ── Les deux outils de recherche n'ont pas le même format ─────────────────────
#
# Oubli constaté à l'écran : quatre lignes « fetching » issues d'une recherche
# d'actualité, sans la moindre source — le format de `web_search_news` étale sur
# deux lignes ce que `web_research_report` met sur une, et le lecteur ne
# reconnaissait que le second.

ACTUALITES = """# Actualités : intelligence artificielle
_Période : cette semaine · 12 articles_

### 1. OpenAI s'offre le futur plus grand centre de données
_lefigaro.fr · 2026-08-17_
[https://lefigaro.fr/a](https://lefigaro.fr/a)

> Le bail court sur vingt ans.

### 2. Anthropic's annualized revenue surges to $65B
_techcrunch.com · 2026-08-17_
[https://techcrunch.com/b](https://techcrunch.com/b)

### 3. Alibaba Overtakes Google and Meta
_pymnts.com · 2026-08-16_
"""


def test_les_sources_d_une_recherche_d_actualite_sont_lues():
    assert [d for d, _ in sources_de(ACTUALITES)] == [
        "lefigaro.fr", "techcrunch.com", "pymnts.com",
    ]


def test_le_titre_d_une_actualite_accompagne_son_domaine():
    assert sources_de(ACTUALITES)[1][1] == "Anthropic's annualized revenue surges to $65B"


def test_les_deux_formats_donnent_le_meme_genre_de_lignes():
    """Un seul rendu pour les deux : l'utilisateur n'a pas à savoir quel outil a
    servi."""
    for rapport in (RAPPORT, ACTUALITES):
        lignes = lignes_sources(sources_de(rapport), total=9)
        assert lignes and all("─" in l.plain for l in lignes)


def test_une_recherche_d_actualite_montre_ses_sites():
    console = _console()
    j = Journal(SortieDirecte(console))

    inscrire_resultat(j, "web_search_news",
                      type("M", (), {"content": ACTUALITES})())

    ecran = _ecran(console)
    assert "searching" in ecran
    assert "lefigaro.fr" in ecran and "techcrunch.com" in ecran


def test_la_requete_d_une_actualite_devient_la_cible():
    j = Journal()
    inscrire_resultat(j, "web_search_news", type("M", (), {"content": ACTUALITES})())

    assert j.actions[0].cible == "intelligence artificielle"


def test_le_compte_total_ne_confond_pas_les_formats():
    from src.ui.journal import compter_sources

    assert compter_sources(ACTUALITES) == 3
    assert compter_sources(RAPPORT) == 5


def test_un_titre_sans_domaine_ne_produit_pas_de_source():
    """Un « ### 3. Titre » orphelin ne doit pas inventer un domaine."""
    from src.ui.journal import compter_sources

    assert compter_sources("### 1. Un titre seul\n\ndu texte ordinaire") == 0
