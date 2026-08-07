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
    assert len(cache) == 5           # une entrée PAR REQUÊTE, pas par événement


def test_deux_rencontres_du_meme_tournoi_partagent_le_tableau_et_la_surface():
    """Le tableau et la surface appartiennent au TOURNOI, pas à la rencontre.

    Cachés par sujet, ils étaient re-cherchés pour chacune de ses rencontres :
    trois appels réseau rendaient trois fois la même page. C'est la portée de la
    requête, et non l'événement qui la déclenche, qui doit décider de la clé.
    """
    appels = []

    def recherche(requete, domaines):
        appels.append(requete)
        return _resultat()

    cache = EnrichmentCache()
    commun = dict(competition="ATP Montréal", blockers=["INSUFFICIENT_FEATURES"],
                  recherche=recherche, cache=cache)
    enrich_event(sport="tennis", sujet="Ruud C. – Shelton B.", **commun)
    n_apres_premier = len(appels)
    enrich_event(sport="tennis", sujet="Sinner J. – Alcaraz C.", **commun)

    # 5 requêtes la première fois ; la seconde rencontre ne repaye que ses 3
    # requêtes d'ÉVÉNEMENT — le tableau et la surface sont déjà connus.
    assert n_apres_premier == 5
    assert len(appels) - n_apres_premier == 3
    # « draw » seul matcherait « withdraws » : on cible ce qui n'appartient qu'aux
    # requêtes de tournoi.
    assert not [r for r in appels[n_apres_premier:]
                if "order of play" in r or "surface court" in r]


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


# ══ §9 — L'enrichissement ne déplace AUCUN chiffre de décision ═══════════════
def _run_enrichi(features_par_evenement=None):
    """Le MÊME run, avec et sans enrichissement."""
    from decimal import Decimal

    from src.agents.quant.conversation.constraints import constraints_from_request
    from src.agents.quant.conversation.window import PARIS, resolve_window
    from tests.test_betting_conversation_safety import _evaluation, _run

    maintenant = datetime(2026, 8, 6, 15, 30, tzinfo=PARIS)
    contraintes = constraints_from_request(
        None, bankroll=Decimal("20"), time_window=resolve_window("", maintenant))
    evaluations = [_evaluation(freshness=None), _evaluation(event="e2", freshness=None)]

    sans, _ = _run(contraintes, evaluations)
    avec, _ = _run(contraintes, evaluations,
                   enrich=lambda reponse, sports: features_par_evenement or {
                       "e1": (make("INJURY", "forfait annoncé", source="ATP",
                                   url="https://www.atptour.com/x",
                                   confidence="OFFICIAL"),)})
    return sans, avec


def _chiffres(response):
    """Tout ce qui décide de l'argent."""
    return [
        (e.candidate.event_id, e.candidate.selection, e.status.value,
         str(e.candidate.fair_probability), str(e.candidate.probability_low),
         str(e.candidate.expected_value_mean), str(e.candidate.expected_value_low),
         str(e.candidate.edge_mean), str(e.candidate.edge_low),
         str(e.candidate.bookmaker_odds), tuple(e.policy_reasons))
        for e in response.review_candidates
    ] + [
        (p.portfolio_id, str(p.total_stake), str(p.unallocated_bankroll),
         tuple((str(l.stake), str(l.total_odds), str(l.expected_value)) for l in p.lines))
        for p in response.portfolios
    ]


def test_aucune_probabilite_ni_EV_ni_mise_ne_change_apres_enrichment():
    """La preuve demandée : mêmes entrées, mêmes chiffres, avec ou sans Internet.
    Probabilités, bornes basses, EV, edge, cotes, statuts, raisons, mises et
    bankroll non allouée sont comparés champ à champ."""
    sans, avec = _run_enrichi()

    assert _chiffres(sans.response) == _chiffres(avec.response)
    assert sans.response.outcome == avec.response.outcome
    assert dict(sans.response.rejection_summary) == dict(avec.response.rejection_summary)


def test_l_ordre_de_la_shortlist_ne_change_pas_apres_enrichment():
    """Un candidat enrichi ne remonte pas dans le classement : le tri lit des
    bornes du modèle, pas des faits web."""
    from src.agents.quant.conversation.review_ranking import rank_review

    sans, avec = _run_enrichi()
    ordre = lambda r: [l.candidate.candidate_id
                       for l in rank_review(r.response.review_candidates)]

    assert ordre(sans) == ordre(avec)


def test_les_features_vivent_hors_du_candidat():
    """Structurellement : elles sont rangées dans l'observabilité, pas sur le
    `CandidateBet` que l'Advisor lit. Elles ne PEUVENT donc pas le traverser."""
    _, avec = _run_enrichi()
    candidat = avec.response.review_candidates[0].candidate

    assert not hasattr(candidat, "internet_features")
    assert avec.observability.internet_features
    assert avec.observability.features_for(candidat)


def test_le_rendu_affiche_les_features_sous_un_intitule_distinct():
    from src.agents.quant.conversation.renderer import render

    _, avec = _run_enrichi()
    rendu = render(avec)

    assert "Contexte externe" in rendu
    assert "n'entre dans aucun calcul" in rendu
    assert "forfait annoncé" in rendu
    assert "atptour.com" in rendu


def test_sans_enrichissement_le_rendu_reste_complet():
    """L'absence de réseau ne doit rien retirer d'essentiel."""
    from src.agents.quant.conversation.renderer import render

    sans, _ = _run_enrichi()
    rendu = render(sans)

    assert "Shortlist de revue" in rendu
    assert "Contexte externe" not in rendu


def test_seuls_les_candidats_de_revue_sont_enrichis():
    """Ni les portefeuilles ni les rejetés : un BET a sa décision prise, un
    REJECTED n'a pas à être expliqué par le web."""
    import inspect

    from src.agents.quant.enrichment import enrich as module

    source = inspect.getsource(module.enrich_review_candidates)

    assert "review_candidates" in source
    assert "portfolios" not in source


def test_le_nombre_d_evenements_enrichis_est_borne():
    """Chaque rencontre coûte plusieurs requêtes : enrichir trente candidats
    brûlerait le quota pour un utilisateur qui n'en lira que les premiers."""
    from src.agents.quant.enrichment.enrich import MAX_EVENEMENTS_ENRICHIS

    assert 1 <= MAX_EVENEMENTS_ENRICHIS <= 5


# ══ Qualité d'extraction : une phrase qui parle du sujet, ou rien ════════════
def test_le_texte_de_navigation_n_est_pas_promu_en_information():
    """Tavily rend le texte brut de la page. Sur une page officielle WTA, cela
    comprend le menu, le logo et le palmarès — sourcé, officiel, et sans rapport
    avec la rencontre. L'afficher sous « contexte externe » donnerait l'apparence
    d'une information là où il n'y a qu'une page."""
    bruit = [{"url": "https://www.wtatennis.com/x", "title": "WTA",
              "content": "WTA Logo Go back to the home page. Quick links. "
                         "Past Winners. Show More. Doubles Draw 64."}]

    assert enrich_event(sport="tennis", sujet="Samsonova L.",
                        blockers=["INSUFFICIENT_FEATURES"],
                        recherche=lambda q, d: bruit,
                        cache=EnrichmentCache()) == ()


def test_une_phrase_qui_nomme_le_sujet_est_retenue():
    utile = [{"url": "https://www.wtatennis.com/x", "title": "WTA",
              "content": "Menu. Home. Samsonova has withdrawn from the tournament "
                         "with a right shoulder injury. Past winners."}]

    features = enrich_event(sport="tennis", sujet="Samsonova L.",
                            blockers=["INSUFFICIENT_FEATURES"],
                            recherche=lambda q, d: utile,
                            cache=EnrichmentCache())

    assert features
    assert "withdrawn" in features[0].value
    assert "Past winners" not in features[0].value


# ══ Coût réseau : ce qui est commun n'est cherché qu'une fois ════════════════
def test_le_libelle_de_competition_n_est_jamais_un_identifiant_canonique():
    """La requête émise était littéralement « competition:tennis:wta:tour draw
    order of play » : un identifiant interne envoyé à un moteur de recherche.
    Elle rendait des pages sans rapport, qu'un domaine officiel suffisait ensuite
    à faire passer pour de l'information."""
    from src.agents.quant.enrichment.enrich import _libelle_competition

    assert _libelle_competition("competition:tennis:wta:tour") == "WTA tour"
    assert _libelle_competition("competition:football:fra:ligue_1") == "fra ligue 1"
    assert _libelle_competition("competition:basketball:usa:nba") == "usa NBA"
    for identifiant in ("competition:tennis:atp:tour", "competition:football:eng:pl"):
        assert ":" not in _libelle_competition(identifiant)


def test_plusieurs_rencontres_du_meme_tournoi_ne_paient_le_tableau_qu_une_fois():
    """Enrichir chaque rencontre dans son propre fil les faisait partir ensemble,
    avant qu'aucune n'ait rempli le cache : les requêtes de tournoi étaient
    émises deux fois. Rassembler les requêtes avant de les lancer supprime la
    course au lieu d'espérer la gagner."""
    from src.agents.quant.enrichment.enrich import enrich_review_candidates

    appels = []

    def recherche(requete, domaines):
        appels.append(requete)
        return []

    sans, _ = _run_enrichi()
    enrich_review_candidates(sans.response, ["tennis"],
                             recherche=recherche, cache=EnrichmentCache())

    assert appels, "aucune requête émise"
    assert len(appels) == len(set(appels)), f"requêtes dupliquées : {appels}"
    tournoi = [r for r in appels if "order of play" in r or "surface court" in r]
    assert len(tournoi) == len(set(tournoi))


def test_les_requetes_sont_menees_de_front():
    """Cinq requêtes à ~2,4 s coûtaient 12 s pour UNE rencontre, sur un pipeline
    qui en prend 3 au total. Le mur doit rester loin sous la somme."""
    import threading
    import time

    simultanees, maximum, verrou = 0, 0, threading.Lock()

    def recherche(requete, domaines):
        nonlocal simultanees, maximum
        with verrou:
            simultanees += 1
            maximum = max(maximum, simultanees)
        time.sleep(0.05)
        with verrou:
            simultanees -= 1
        return []

    enrich_event(sport="tennis", sujet="Ruud C.", competition="ATP Montréal",
                 blockers=["INSUFFICIENT_FEATURES"], recherche=recherche,
                 cache=EnrichmentCache())

    assert maximum >= 2, "les requêtes sont restées séquentielles"


def test_l_ordre_du_rendu_ne_depend_pas_de_l_ordre_d_arrivee_reseau():
    """Deux réponses identiques dans un ordre d'arrivée différent doivent rendre
    la même liste : sinon le même run afficherait deux textes selon le réseau."""
    import time

    pages = {
        "INJURY": {"url": "https://www.atptour.com/a", "title": "ATP",
                   "content": "Ruud C. has withdrawn from the tournament with injury."},
        "RANK": {"url": "https://www.wtatennis.com/b", "title": "WTA",
                 "content": "Ruud C. is currently ranked inside the top ten players."},
    }

    def lente(requete, domaines):
        if "injury" in requete:
            time.sleep(0.15)                     # la première requête répond en dernier
            return [pages["INJURY"]]
        return [pages["RANK"]]

    def rapide(requete, domaines):
        return [pages["INJURY"]] if "injury" in requete else [pages["RANK"]]

    args = dict(sport="tennis", sujet="Ruud C.", competition="ATP Montréal",
                blockers=["INSUFFICIENT_FEATURES"])
    a = enrich_event(**args, recherche=lente, cache=EnrichmentCache())
    b = enrich_event(**args, recherche=rapide, cache=EnrichmentCache())

    assert [(f.feature_type, f.value) for f in a] == [(f.feature_type, f.value) for f in b]


def test_un_cache_injecte_vide_n_est_pas_remplace_par_le_cache_global():
    """`cache = kw.get("cache") or CACHE` remplaçait un cache injecté VIDE par le
    cache global : `EnrichmentCache` définit `__len__`, donc un cache neuf est
    falsy. L'appelant croyait s'isoler et écrivait dans l'état partagé du
    processus — un test remplissait alors le cache d'un autre."""
    from src.agents.quant.enrichment import enrich as module

    propre = EnrichmentCache()
    assert not propre, "un cache vide est bien falsy — c'est tout le piège"

    global_avant = len(module.CACHE)
    sans, _ = _run_enrichi()
    module.enrich_review_candidates(sans.response, ["tennis"],
                                    recherche=lambda q, d: [], cache=propre)

    assert len(propre) > 0, "les résultats ne sont pas allés dans le cache fourni"
    assert len(module.CACHE) == global_avant, "le cache global a été touché"
