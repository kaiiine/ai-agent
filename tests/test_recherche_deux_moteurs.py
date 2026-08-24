"""Deux moteurs plutôt qu'un — et des places réservées au second.

DuckDuckGo était installé, sans clé, et ne se déclenchait qu'en dessous de trois
résultats Tavily. Mesuré sur quatre requêtes réelles : ZÉRO fois. La couverture
d'un second moteur était payée sans être utilisée.

Le rendre systématique ne suffisait pas. Première version mesurée, coupe à
`max_results` après fusion : 27 → 29 domaines seulement, et DuckDuckGo n'entrait
que sur la requête où Tavily avait rendu moins de dix résultats. Tavily remplit
les dix places, le second moteur arrive derrière et tombe hors de la coupe.

Avec des places réservées : 27 → 33 domaines (+11 nouveaux, −5 perdus). Les
perdus sont les rangs 8 à 10 de Tavily, échangés contre les trois premiers de
DuckDuckGo — de la diversité contre de la profondeur marginale. Le gain est
aussi qualitatif : sur « LangGraph checkpointer postgres », le second moteur
apporte `langchain-ai.github.io` et `pypi.org`, que Tavily manquait.

Ces tests ne touchent pas le réseau : ils portent sur la fusion, qui est la
partie où la logique vit.
"""
import pytest

from src.agents.search import tools as recherche


# ── Le dédoublonnage ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("a, b", [
    ("https://www.ibm.com/page/", "http://ibm.com/page"),
    ("https://x.dev/a/", "https://x.dev/a"),
    ("https://WWW.Example.COM/Doc", "https://example.com/Doc"),
])
def test_deux_url_de_la_meme_page_ont_la_meme_cle(a, b):
    """Deux moteurs rendent la même page sous des formes différentes ; comparer
    les chaînes brutes compterait deux sources là où il n'y en a qu'une."""
    assert recherche._cle_url(a) == recherche._cle_url(b)


def test_deux_pages_distinctes_gardent_des_cles_distinctes():
    assert recherche._cle_url("https://x.dev/a") != recherche._cle_url("https://x.dev/b")


def test_une_url_illisible_ne_leve_pas():
    recherche._cle_url("pas une url du tout")


# ── La fusion ─────────────────────────────────────────────────────────────────
def _faux(source: str, n: int, prefixe: str):
    return [{"title": f"{prefixe}{i}", "url": f"https://{prefixe}{i}.dev/x",
             "content": "", "score": 1.0 if source != "duckduckgo" else 0.0,
             **({"_source": "duckduckgo"} if source == "duckduckgo" else {})}
            for i in range(n)]


def _fusionner(tavily, ddg, max_results=10):
    """Rejoue la fusion telle que `web_research_report` la fait."""
    results = tavily + ddg
    vus, uniques = set(), []
    for r in results:
        cle = recherche._cle_url(r.get("url", ""))
        if cle and cle not in vus:
            vus.add(cle)
            uniques.append(r)
    part = max(2, max_results // 3)
    premiers = [r for r in uniques if r.get("_source") != "duckduckgo"]
    seconds = [r for r in uniques if r.get("_source") == "duckduckgo"]
    retenus = premiers[:max_results - part] + seconds[:part]
    if len(retenus) < max_results:
        deja = {id(r) for r in retenus}
        retenus += [r for r in premiers + seconds if id(r) not in deja][:max_results - len(retenus)]
    return retenus[:max_results]


def test_le_second_moteur_obtient_des_places_meme_si_le_premier_remplit_tout():
    """Le défaut de la première version : Tavily rendait dix résultats, la coupe
    tombait à dix, et DuckDuckGo n'entrait jamais."""
    res = _fusionner(_faux("tavily", 10, "t"), _faux("duckduckgo", 10, "d"))

    assert sum(1 for r in res if r.get("_source") == "duckduckgo") >= 2


def test_le_premier_moteur_garde_la_majorite():
    """On réserve, on ne cède pas la main : Tavily porte le score et le contenu
    markdown complet, DuckDuckGo un simple extrait."""
    res = _fusionner(_faux("tavily", 10, "t"), _faux("duckduckgo", 10, "d"))

    assert sum(1 for r in res if r.get("_source") != "duckduckgo") > len(res) // 2


def test_le_total_reste_borne():
    """Sans borne, le rapport grossit et chasse la réponse hors de l'écran."""
    assert len(_fusionner(_faux("tavily", 20, "t"), _faux("duckduckgo", 20, "d"))) == 10


def test_les_places_reservees_sont_rendues_si_le_second_n_a_rien():
    """Réserver ne doit pas gaspiller : sans apport DuckDuckGo, Tavily reprend
    les places."""
    res = _fusionner(_faux("tavily", 10, "t"), [])

    assert len(res) == 10


def test_un_doublon_entre_moteurs_ne_compte_qu_une_fois():
    tavily = [{"title": "A", "url": "https://www.ibm.com/doc/", "score": 1.0}]
    ddg = [{"title": "A", "url": "http://ibm.com/doc", "score": 0.0, "_source": "duckduckgo"}]

    assert len(_fusionner(tavily, ddg)) == 1


def test_la_version_du_premier_moteur_gagne_sur_un_doublon():
    """Elle porte un score et le markdown complet ; celle de DuckDuckGo n'a
    qu'un extrait."""
    tavily = [{"title": "A", "url": "https://www.ibm.com/doc/", "score": 0.9}]
    ddg = [{"title": "A", "url": "http://ibm.com/doc", "score": 0.0, "_source": "duckduckgo"}]

    assert _fusionner(tavily, ddg)[0].get("_source") != "duckduckgo"


# ── Le déclenchement ──────────────────────────────────────────────────────────
def test_duckduckgo_n_est_plus_conditionnel():
    """Le garde `if len(results) < 3` le rendait presque toujours inutile."""
    import inspect

    # `.func` : l'objet exposé est un outil décoré, pas la fonction.
    source = inspect.getsource(recherche.web_research_report.func)

    assert "if len(results) < 3" not in source
    assert "DDGS()" in source


def test_la_troncature_arrive_apres_la_fusion():
    """Couper avant, c'est garder dix résultats Tavily puis en empiler dix
    autres — et perdre le second moteur à la coupe suivante."""
    import inspect

    # `.func` : l'objet exposé est un outil décoré, pas la fonction.
    source = inspect.getsource(recherche.web_research_report.func)
    tri = source.index("sorted(results, key=_score")
    ddg = source.index("DDGS()")

    assert tri < ddg, "le tri doit précéder la fusion"
    assert "[:max_results]" not in source[tri:ddg], "et ne pas tronquer avant elle"
