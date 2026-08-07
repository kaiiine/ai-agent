"""Internet enrichit, Internet ne calcule pas.

Une blessure annoncée par l'ATP est une information réelle et utile à lire. La
transformer en ajustement de probabilité demanderait de savoir DE COMBIEN — ce
qu'aucune page web ne dit. Entre les deux il n'y a pas un petit pas mais un
modèle entier, avec sa validation walk-forward.

Ces tests verrouillent la frontière dans les deux sens : la couche produit bien
des faits exploitables, et rien de ce qu'elle produit ne peut atteindre une
probabilité, une EV, un edge ou une mise.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.enrichment.enrich import (
    DECLENCHEURS,
    EnrichmentCache,
    enrich_event,
    should_enrich,
)
from src.agents.quant.enrichment.features import (
    FEATURE_TYPES,
    INFORMATIVE,
    InternetFeature,
    make,
)
from src.agents.quant.enrichment.sources import confidence_for, sort_by_authority

_MAINTENANT = datetime(2026, 8, 7, 12, tzinfo=timezone.utc)


def _resultat(url="https://www.atptour.com/en/news/x", titre="ATP", texte="Injury"):
    return [{"url": url, "title": titre, "content": texte}]


# ══ La frontière : jamais quantitatif ════════════════════════════════════════
def test_une_feature_ne_peut_pas_etre_declaree_exploitable():
    """Le verrou central. Le jour où un modèle exploitera une feature Internet,
    ce sera une modification consciente accompagnée de sa validation — pas un
    champ passé en douce."""
    with pytest.raises(ValueError, match="modèle validé"):
        InternetFeature(
            feature_type="INJURY", value="x", source="ATP",
            url="https://atptour.com", retrieved_at=_MAINTENANT,
            usage="QUANTITATIVE")


def test_toute_feature_produite_est_informative():
    f = make("INJURY", "blessé", source="ATP", url="https://www.atptour.com/x")

    assert f.usage == INFORMATIVE


def test_un_type_de_feature_hors_contrat_est_refuse():
    """L'ensemble est fermé : un type non prévu doit être ajouté consciemment,
    pas apparaître parce qu'une recherche a rendu autre chose."""
    with pytest.raises(ValueError, match="hors contrat"):
        make("PROBABILITE", "0.62", source="blog", url="https://x.example")


def test_aucun_type_de_feature_ne_designe_une_grandeur_de_decision():
    """Le contrat lui-même ne doit contenir aucun nom qui inviterait à y ranger
    une probabilité, une cote ou une mise."""
    interdits = ("PROBABILITY", "PROBA", "ODDS", "EV", "EDGE", "STAKE", "KELLY",
                 "FAIR", "PREDICTION")
    for nom in FEATURE_TYPES:
        assert not any(mot in nom.upper() for mot in interdits), nom


def test_la_couche_n_importe_rien_du_moteur_de_decision():
    """Preuve structurelle : le module d'enrichissement ne connaît ni l'Advisor,
    ni le value engine, ni les modèles. Il ne PEUT donc pas les influencer."""
    import ast
    import pathlib

    paquet = pathlib.Path("src/agents/quant/enrichment")
    for fichier in paquet.rglob("*.py"):
        arbre = ast.parse(fichier.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            noms = []
            if isinstance(noeud, ast.ImportFrom):
                noms = [noeud.module or ""]
            elif isinstance(noeud, ast.Import):
                noms = [a.name for a in noeud.names]
            for nom in noms:
                for interdit in ("advisor", "value_engine", "betting_engine.sports",
                                 "market_models", "live_evaluation"):
                    assert interdit not in nom, f"{fichier.name} importe {nom}"


def test_le_moteur_de_decision_ignore_la_couche_internet():
    """Le sens inverse : aucun module de décision n'importe l'enrichissement."""
    import pathlib

    racine = pathlib.Path("src/agents/quant")
    coupables = [
        str(f) for f in racine.rglob("*.py")
        if "enrichment" not in str(f)
        and "quant.enrichment" in f.read_text(encoding="utf-8")
        and "conversation" not in str(f)
    ]

    assert not coupables, f"le moteur importe l'enrichissement : {coupables}"


# ══ Déclenchement ciblé, jamais systématique ═════════════════════════════════
@pytest.mark.parametrize("blocage", sorted(DECLENCHEURS))
def test_chaque_blocage_declare_declenche(blocage):
    assert should_enrich([blocage])


@pytest.mark.parametrize("blocage", [
    "EVENT_NOT_RESOLVED", "SPORT_NOT_SUPPORTED", "MARKET_CANONICALIZATION_FAILED",
    "EXPERIMENTAL_REVIEW_ONLY", "LOW_DATA_QUALITY",
])
def test_un_blocage_que_le_web_ne_peut_pas_expliquer_ne_declenche_pas(blocage):
    """Un sport non enregistré ou un marché non canonicalisable sont des manques
    de NOTRE référentiel. Chercher sur le web n'y répondrait pas, et brûlerait du
    quota pour rien."""
    assert not should_enrich([blocage])


def test_sans_blocage_aucune_recherche_n_est_lancee():
    appels = []

    def recherche(requete, domaines):
        appels.append(requete)
        return _resultat()

    resultat = enrich_event(sport="tennis", sujet="X", blockers=[],
                            recherche=recherche, cache=EnrichmentCache())

    assert resultat == () and appels == []


def test_aucune_requete_generique_n_est_emise():
    """Une requête vague rend des articles d'opinion, promus ensuite en
    « information ». Chaque requête doit nommer son sujet et son type."""
    requetes = []

    def recherche(requete, domaines):
        requetes.append(requete)
        return []

    enrich_event(sport="tennis", sujet="Ruud C.", competition="ATP Montréal",
                 blockers=["INSUFFICIENT_FEATURES"], recherche=recherche,
                 cache=EnrichmentCache())

    assert requetes
    for requete in requetes:
        assert "Ruud C." in requete or "ATP Montréal" in requete
        assert len(requete.split()) >= 4


def test_un_sport_sans_requete_declaree_ne_cherche_rien():
    """Le volley n'a pas de source officielle déclarée : ne rien chercher vaut
    mieux que chercher mal."""
    assert enrich_event(sport="volleyball", sujet="X",
                        blockers=["INSUFFICIENT_FEATURES"],
                        recherche=lambda q, d: _resultat(),
                        cache=EnrichmentCache()) == ()


# ══ Hiérarchie des sources ═══════════════════════════════════════════════════
@pytest.mark.parametrize("url,attendu", [
    ("https://www.atptour.com/en/news/x", "OFFICIAL"),
    ("https://www.wtatennis.com/news/x", "OFFICIAL"),
    ("https://www.itftennis.com/x", "OFFICIAL"),
    ("https://www.reuters.com/sport/x", "REPUTABLE"),
    ("https://paris-sportifs-blog.example/x", "UNVERIFIED"),
])
def test_l_autorite_de_la_source_est_lue_sur_le_domaine(url, attendu):
    assert confidence_for(url, "tennis") == attendu


def test_un_fait_officiel_ancien_prime_sur_une_rumeur_recente():
    officiel = make("INJURY", "forfait", source="ATP",
                    url="https://www.atptour.com/x", confidence="OFFICIAL",
                    retrieved_at=_MAINTENANT - timedelta(days=1))
    rumeur = make("INJURY", "peut-être blessé", source="blog",
                  url="https://x.example/y", confidence="UNVERIFIED",
                  retrieved_at=_MAINTENANT)

    assert sort_by_authority([rumeur, officiel])[0] is officiel


def test_le_sport_borne_les_domaines_officiels():
    """`nba.com` est officiel pour le basket, pas pour le tennis — sans quoi
    n'importe quelle fédération authentifierait n'importe quel sport."""
    assert confidence_for("https://www.nba.com/x", "basketball") == "OFFICIAL"
    assert confidence_for("https://www.nba.com/x", "tennis") == "UNVERIFIED"


# ══ Cache ════════════════════════════════════════════════════════════════════
def test_la_meme_recherche_n_est_pas_relancee():
    appels = []

    def recherche(requete, domaines):
        appels.append(requete)
        return _resultat()

    cache = EnrichmentCache()
    args = dict(sport="tennis", sujet="Ruud C.", blockers=["INSUFFICIENT_FEATURES"],
                recherche=recherche, cache=cache)
    premier = enrich_event(**args)
    second = enrich_event(**args)

    assert premier == second
    assert len(appels) == 5          # une passe, pas deux
    assert len(cache) == 1


def test_le_cache_expire():
    cache = EnrichmentCache(ttl_seconds=-1)      # déjà périmé
    appels = []

    def recherche(requete, domaines):
        appels.append(requete)
        return _resultat()

    args = dict(sport="tennis", sujet="X", blockers=["INSUFFICIENT_FEATURES"],
                recherche=recherche, cache=cache)
    enrich_event(**args)
    enrich_event(**args)

    assert len(appels) == 10         # deux passes : le cache n'a rien retenu


def test_une_recherche_qui_echoue_ne_casse_pas_le_run():
    """L'enrichissement est un bonus. S'il tombe, la réponse structurée reste."""
    def recherche(requete, domaines):
        raise RuntimeError("réseau indisponible")

    assert enrich_event(sport="tennis", sujet="X",
                        blockers=["INSUFFICIENT_FEATURES"],
                        recherche=recherche, cache=EnrichmentCache()) == ()
