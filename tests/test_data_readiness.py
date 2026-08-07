"""Fraîcheur et couverture — mesurées pour de vrai, ou déclarées non mesurables.

Le rapport de la vague précédente annonçait « FRESHNESS_UNKNOWN généralisé ». La
mesure a montré autre chose : deux causes distinctes produisaient le même
symptôme, et une troisième affirmation du rapport était simplement fausse.

  1. `gateway.data_freshness` codait `sport="football"` en dur. Pour une
     compétition de baseball, elle allait chercher des données de football,
     obtenait NoDataAvailableError et rendait `None` — la fraîcheur devenait
     « inconnue » pour un motif faux.

  2. Un `degraded=True` était traité comme une absence de mesure. Or il dit que
     la BASE est plus faible (`fetched_at` au lieu de `published_time`), pas que
     la mesure manque. Les confondre transformait une fraîcheur mesurée à 0,0001
     — donc une donnée manifestement périmée — en « inconnue », c'est-à-dire en
     un doute plus favorable que la mesure elle-même.

Ces tests portent sur le CONTRAT, pas sur un sport : c'est ce qui les rend
valides pour les schémas 2-way comme 3-way.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.betting_engine.live_evaluation import (
    LiveEvaluationStatus as S,
)

#: MÊME instant que le harnais live réutilisé plus bas : une date locale
#: décalerait toutes les fraîcheurs relatives sans que le test ne le dise.
from tests.test_live_evaluation import _DECISION  # noqa: E402


# ══ §2 — Le sport vient de l'identifiant, jamais d'un défaut ═════════════════
@pytest.mark.parametrize("competition,sport", [
    ("competition:football:fra:ligue1", "football"),
    ("competition:baseball:usa:mlb", "baseball"),
    ("competition:tennis:atp:tour", "tennis"),
    ("competition:hockey:usa:nhl", "hockey"),
])
def test_le_sport_est_lu_sur_l_identifiant_de_competition(competition, sport):
    from src.agents.quant.gateway.gateway import _sport_of

    assert _sport_of(competition) == sport


@pytest.mark.parametrize("identifiant", ["", "bidon", "team:football:psg", "competition"])
def test_un_identifiant_non_canonique_ne_donne_aucun_sport(identifiant):
    """On ne devine pas un sport : un identifiant hors forme rend `None`, et la
    fraîcheur sera honnêtement non mesurable."""
    from src.agents.quant.gateway.gateway import _sport_of

    assert _sport_of(identifiant) is None


def test_un_sport_non_couvert_par_la_gateway_rend_none_sans_lever():
    """Les six sports non-football n'ont aucun module Gateway. Le dire par `None`
    est correct ; aller chercher des données de FOOTBALL pour eux ne l'était
    pas."""
    from src.agents.quant.gateway import gateway

    assert gateway.data_freshness("competition:baseball:usa:mlb", "2026") is None


# ══ §3 — degraded ≠ non mesurable ════════════════════════════════════════════
def _resultat(freshness):
    """Le harnais live existant, avec la fraîcheur qu'on veut éprouver. On
    réutilise sa Gateway complète : construire la nôtre reviendrait à réimplémenter
    `recent_form` et `standings_strength` pour tester la fraîcheur."""
    from tests.test_live_evaluation import _FreshGateway, _run

    return _run(_FreshGateway(freshness))


def _mesure(score, effective, *, degraded):
    from src.agents.quant.gateway.gateway import DataFreshness

    return DataFreshness(
        freshness_score=score, effective_time=effective,
        basis="fetched_at" if degraded else "published_time",
        degraded=degraded, stale=False)


def test_une_mesure_degradee_est_propagee_et_signalee():
    """Le cœur du correctif : la base est faible, la mesure existe. On propage le
    score ET on signale la dégradation — l'un sans l'autre ment dans un sens ou
    dans l'autre."""
    from src.agents.quant.betting_engine.live_evaluation import _FRESHNESS_DEGRADED

    res = _resultat(_mesure(0.42, _DECISION - timedelta(hours=1), degraded=True))

    assert res.status is S.EVALUATED
    assert res.freshness_score == 0.42
    assert _FRESHNESS_DEGRADED in res.warnings


def test_une_mesure_fiable_est_propagee_sans_avertissement():
    from src.agents.quant.betting_engine.live_evaluation import _FRESHNESS_DEGRADED

    res = _resultat(_mesure(0.95, _DECISION - timedelta(minutes=5), degraded=False))

    assert res.freshness_score == 0.95
    assert _FRESHNESS_DEGRADED not in res.warnings


def test_une_absence_de_donnee_reste_non_mesurable():
    """`None` veut dire qu'aucun horodatage n'est exploitable. Le contrat interdit
    d'en faire un zéro comme d'en faire une fraîcheur."""
    assert _resultat(None).freshness_score is None


def test_un_horodatage_absent_reste_non_mesurable():
    assert _resultat(_mesure(0.9, None, degraded=False)).freshness_score is None


def test_une_donnee_trop_ancienne_est_refusee_meme_avec_base_degradee():
    """Une base faible ne dispense pas du contrôle d'ancienneté — c'est même le
    cas où il sert le plus."""
    res = _resultat(_mesure(0.0001, _DECISION - timedelta(days=30), degraded=True))

    assert res.status is S.DATA_TOO_STALE


# ══ §1-4 — `dataset_recency` ne se confond jamais avec la freshness live ═════
def _recency(dates, as_of):
    from src.agents.quant.betting_engine.dataset_recency import measure

    return measure(dates, source="corpus", as_of=as_of)


def test_un_corpus_ancien_avec_une_cote_fraiche_donne_deux_verdicts_opposes():
    """Le cas qui justifie la séparation. Les fondre ferait qu'un corpus arrêté
    en 2023 rendrait « périmée » une cote observée il y a cinq minutes."""
    from src.agents.quant.betting_engine.dataset_recency import MEASURABLE

    res = _resultat(_mesure(0.95, _DECISION - timedelta(minutes=5), degraded=False))
    corpus = _recency([_DECISION - timedelta(days=900)], _DECISION)

    assert res.freshness_score == 0.95                     # la donnée live est fraîche
    assert corpus.status == MEASURABLE and corpus.age_days == 900   # le corpus, non


def test_un_corpus_recent_sans_donnee_live_laisse_la_freshness_inconnue():
    """L'inverse : un corpus à jour ne rend pas fraîche une donnée live absente.
    `freshness_score = None` reste la seule réponse honnête."""
    from src.agents.quant.betting_engine.dataset_recency import MEASURABLE

    res = _resultat(None)
    corpus = _recency([_DECISION - timedelta(days=2)], _DECISION)

    assert res.freshness_score is None
    assert corpus.status == MEASURABLE and corpus.age_days == 2


def test_un_corpus_ancien_ne_declenche_jamais_data_too_stale():
    """Tant qu'aucune politique de récence de corpus n'existe, l'ancienneté du
    dataset ne rejette rien. Ce test tombera le jour où quelqu'un branchera la
    récence sur le gate de staleness — c'est exactement son rôle."""
    res = _resultat(_mesure(0.95, _DECISION - timedelta(minutes=5), degraded=False))

    assert res.status is S.EVALUATED


def test_la_recence_de_corpus_n_alimente_jamais_le_candidat():
    """Preuve structurelle : ni l'adaptateur ni le générateur de candidats ne
    connaissent `dataset_recency`. Le lien ne peut donc pas exister par accident."""
    import inspect

    from src.agents.quant.advisor.candidate_generation import generator
    from src.agents.quant.advisor.input_adapter import betting_engine_adapter

    for module in (betting_engine_adapter, generator):
        assert "dataset_recency" not in inspect.getsource(module)


def test_un_corpus_vide_est_non_mesurable_jamais_zero_jour():
    """« Zéro jour d'ancienneté » se lirait comme parfaitement à jour — l'exact
    contraire de ce qu'une absence de données signifie."""
    from src.agents.quant.betting_engine.dataset_recency import NOT_MEASURABLE

    vide = _recency([], _DECISION)

    assert vide.status == NOT_MEASURABLE
    assert vide.age_days is None and vide.last_observation_at is None


def test_chaque_modele_enregistre_expose_sa_recence():
    """Un modèle sans récence mesurable rendrait le diagnostic muet là où il doit
    précisément distinguer « code incomplet » de « données à accumuler »."""
    from src.agents.quant.betting_engine.dataset_recency import MEASURABLE, for_model
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS

    muets = [cle for cle in _ASSESSORS if for_model(cle).status != MEASURABLE]

    assert not muets, f"récence de corpus non mesurable : {muets}"


def test_readiness_affiche_les_deux_grandeurs_separement():
    from src.agents.quant.betting_engine.dataset_recency import for_model
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS, render

    lignes = "\n".join(render(_ASSESSORS["nhl"](), for_model("nhl")))

    assert "freshness live :" in lignes
    assert "dataset :" in lignes


# ══ §16 — Aucun seuil de maturité modifié ════════════════════════════════════
def test_aucun_seuil_de_maturite_n_a_bouge():
    """La mission corrige des MESURES, jamais des barres. Un seuil déplacé ferait
    passer un modèle sans qu'aucune donnée n'ait changé."""
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    p = load_maturity_policy()

    assert p.criteria["min_data_coverage"] == 0.9
    assert p.criteria["min_data_quality"] == 0.8
    assert p.criteria["min_sample_size"] == 500
    assert p.criteria["min_temporal_folds"] == 3
    assert p.criteria["max_calibration_error"] == 0.05
    assert p.criteria["min_clv_events"] == 30


def test_les_criteres_requis_restent_les_memes():
    from src.agents.quant.betting_engine.maturity import load_maturity_policy

    requis = {k for k, v in load_maturity_policy().required_for_support.items() if v}

    assert requis == {
        "max_calibration_error", "measurable_live_freshness", "min_data_coverage",
        "min_data_quality", "min_sample_size", "min_temporal_folds",
        "must_beat_baselines", "positive_clv",
    }


def test_la_maturite_reste_derivee_mecaniquement():
    """Aucun modèle ne devient SUPPORTED par cette wave : les statuts sont dérivés
    des critères, et les critères de données restent ceux qu'on mesure."""
    from src.agents.quant.betting_engine.readiness_cli import _ASSESSORS

    statuts = {cle: _ASSESSORS[cle]().decision.status
               for cle in ("nhl", "atp", "fl1")}

    assert set(statuts.values()) == {"EXPERIMENTAL"}


# ══ La capacité de fraîcheur est MESURÉE, jamais déclarée ═══════════════════
#: Une compétition par sport modélisé, avec l'identifiant canonique que les
#: modèles utilisent réellement.
_COMPETITIONS_PAR_SPORT = (
    ("competition:football:fra:ligue1", "football"),
    ("competition:basketball:usa:nba", "basketball"),
    ("competition:baseball:usa:mlb", "baseball"),
    ("competition:american_football:usa:nfl", "american_football"),
    ("competition:hockey:usa:nhl", "hockey"),
    ("competition:volleyball:ita:serie_a1", "volleyball"),
    ("competition:tennis:atp:tour", "tennis"),
)
def test_la_capacite_de_fraicheur_suit_ce_que_la_chaine_sait_servir():
    """`measurable_live_freshness` est un critère REQUIS vers SUPPORTED.

    Il était ÉCRIT en littéral dans chaque évaluateur : cinq modèles déclaraient
    PASS sur un critère que leur chemin de décision ne peut pas honorer, et
    n'attendaient plus que la CLV pour être dits SUPPORTED — c'est-à-dire misables.

    Deux formulations plus permissives ont été essayées et rejetées, chacune
    recréant le faux PASS :

    - la présence du sport dans `FALLBACK_ORDER` : brancher les cinq produits
      api-sports y aurait fait entrer cinq sports dont le plan gratuit refuse
      justement la saison en cours ;
    - la couverture au registre : le dataset tennis embarqué y figure en FULL
      pour la saison en cours, et il est bien réel — mais il n'est pas un
      provider de la Gateway, et la chaîne ne peut rien horodater avec lui.

    La question exacte est : la chaîne saurait-elle SERVIR cette donnée
    aujourd'hui ?
    """
    from src.agents.quant.betting_engine.live_coverage import live_freshness_capability
    from src.agents.quant.betting_engine.maturity import (
        FRESHNESS_MEASURABLE,
        FRESHNESS_NOT_MEASURABLE,
    )
    from src.agents.quant.gateway.core.fallback_chain import capable_providers
    from src.agents.quant.gateway.gateway import current_season

    for competition, sport in _COMPETITIONS_PAR_SPORT:
        servants = capable_providers(sport, competition, current_season(), "RESULTS")
        attendu = FRESHNESS_MEASURABLE if servants else FRESHNESS_NOT_MEASURABLE
        assert live_freshness_capability(competition) == attendu, sport


def test_un_dataset_embarque_ne_vaut_pas_une_fraicheur_mesurable():
    """Le cas qui a fait tomber la version précédente. Le corpus tennis est
    couvert FULL à la saison en cours par empreinte de fichier — c'est vrai, et
    ça ne rend pas la fraîcheur mesurable pour autant : aucun provider de la
    Gateway ne sert ce sport, donc rien n'horodate la donnée au point de
    décision. Les deux grandeurs restent distinctes (récence de corpus vs
    fraîcheur live), et c'est exactement le partage à ne pas perdre."""
    from src.agents.quant.betting_engine.live_coverage import live_freshness_capability
    from src.agents.quant.betting_engine.maturity import FRESHNESS_NOT_MEASURABLE
    from src.agents.quant.gateway.gateway import current_season
    from src.agents.quant.gateway.registries.provider_coverage_registry import usable_providers

    tour = "competition:tennis:atp:tour"

    # Une source EST déclarée pour la saison en cours…
    assert usable_providers(tour, current_season(), "RESULTS")
    # …et la fraîcheur live reste pourtant non mesurable.
    assert live_freshness_capability(tour) == FRESHNESS_NOT_MEASURABLE


def test_aucun_evaluateur_ne_code_en_dur_sa_capacite_de_fraicheur():
    """Un critère de maturité qui tient à une constante n'est pas un critère.

    Écrire `FRESHNESS_MEASURABLE` dans un évaluateur revient à s'auto-délivrer le
    PASS : le rapport de readiness affiche alors « freshness live exposée » sans
    que rien ne l'ait vérifié.
    """
    import ast
    import pathlib

    racine = pathlib.Path(__file__).resolve().parent.parent / "src" / "agents" / "quant"
    coupables = []
    for fichier in sorted(racine.rglob("*.py")):
        if fichier.name in ("maturity.py", "live_coverage.py"):
            continue                      # la définition et la mesure elles-mêmes
        for noeud in ast.walk(ast.parse(fichier.read_text())):
            if not isinstance(noeud, ast.keyword) or noeud.arg != "live_freshness_status":
                continue
            if isinstance(noeud.value, ast.Name) and noeud.value.id.startswith("FRESHNESS_"):
                coupables.append(f"{fichier.relative_to(racine)}:{noeud.value.lineno}")
            elif isinstance(noeud.value, ast.Constant):
                coupables.append(f"{fichier.relative_to(racine)}:{noeud.value.lineno}")

    assert not coupables, ("capacité de fraîcheur codée en dur :\n" + "\n".join(coupables))


def test_les_modeles_sans_provider_portent_le_bloqueur_de_fraicheur():
    """Bout en bout : le verdict de maturité expose le manque, il ne l'absorbe pas."""
    from src.agents.quant.betting_engine.maturity import Verdict
    from src.agents.quant.betting_engine.sports.baseball.moneyline import assess_mlb

    decision = assess_mlb().decision
    critere = next(c for c in decision.criteria if c.name == "measurable_live_freshness")

    assert critere.required
    assert critere.verdict is not Verdict.PASS
    assert decision.status == "EXPERIMENTAL"


# ══ La Gateway reflète les capacités RÉELLES du provider ════════════════════
def test_le_provider_declare_les_six_produits_api_sports():
    """`supported_sports` valait `["football"]`. Sondée, la MÊME clé répond
    HTTP 200 sur les six produits, chacun avec son quota propre : la limite était
    dans le code, pas dans le credential. Le module d'acquisition l'avait déjà
    constaté de son côté — la même limitation vivait à deux endroits et n'avait
    été levée qu'à un seul."""
    from src.agents.quant.gateway.providers.api_sports_provider import ApiSportsProvider

    provider = ApiSportsProvider()

    assert set(provider.supported_sports) == {
        "football", "basketball", "baseball", "american_football",
        "hockey", "volleyball"}
    for sport in provider.supported_sports:
        assert provider.capabilities(sport).fixtures, sport
    # Le classement n'a été sondé qu'en football : ne pas l'annoncer ailleurs.
    assert provider.capabilities("football").standings
    assert not provider.capabilities("hockey").standings
    # Un sport inconnu ne lève pas, il ne promet rien.
    assert not provider.capabilities("curling").fixtures


def test_la_saison_est_traduite_au_format_du_produit():
    """Le basket refuse `2024` et veut `2024-2025`. Sans cette conversion, une
    demande légitime revient vide — et une réponse vide se lit « pas de données »
    alors que c'est la question qui était mal posée."""
    from src.agents.quant.gateway.providers.api_sports_provider import saison_provider

    assert saison_provider("basketball", "2024") == "2024-2025"
    assert saison_provider("basketball", "2024-2025") == "2024-2025"
    assert saison_provider("hockey", "2024") == "2024"
    assert saison_provider("football", "2024") == "2024"


def test_le_plan_gratuit_borne_les_six_produits_a_la_meme_saison():
    """La borne réelle n'est pas le sport, c'est la SAISON. Mesuré le 2026-08-07 :
    2024 répond pour les six produits, 2025+ renvoie HTTP 200, zéro rencontre et
    « Free plans do not have access to this season ». Un refus de plan ressemble à
    une absence de données — d'où l'intérêt de le borner explicitement."""
    from src.agents.quant.gateway.providers.api_sports_provider import ApiSportsProvider

    provider = ApiSportsProvider()
    for sport in provider.supported_sports:
        assert provider.is_available(sport, "2024"), sport
        assert not provider.is_available(sport, "2025"), sport
    # Le format composé du basket ne doit pas faire rater la borne.
    assert provider.is_available("basketball", "2024-2025")
    assert not provider.is_available("basketball", "2025-2026")


def test_chaque_sport_du_moteur_a_son_module_gateway():
    """Un modèle enregistré côté moteur sans module côté Gateway ne peut jamais
    obtenir de fraîcheur : le sport est « non installé » et l'échec se lit
    « aucune donnée »."""
    from src.agents.quant.betting_engine.sports.registry import SPORT_MODULES as MOTEUR
    from src.agents.quant.gateway.sports.registry import SPORT_MODULES as PASSERELLE

    # Le tennis n'a pas de provider Gateway (dataset embarqué) — il est le seul.
    manquants = set(MOTEUR) - set(PASSERELLE) - {"tennis"}

    assert not manquants, f"sports sans module Gateway : {sorted(manquants)}"


def test_les_espaces_d_identites_sont_distincts_par_produit():
    """api-sports numérote ses équipes séparément par produit : l'équipe 132 du
    basket n'a rien à voir avec l'équipe 132 du hockey. Les confondre
    rattacherait des rencontres à la mauvaise franchise, en silence."""
    from src.agents.quant.betting_engine.sports.registry import all_known_entities
    from src.agents.quant.gateway.sports.pairwise.normalizer import NAMESPACES

    assert len(set(NAMESPACES.values())) == len(NAMESPACES)

    declares = {ns for entite in all_known_entities()
                for ns in getattr(entite, "identities", {})}
    for sport, namespace in NAMESPACES.items():
        assert namespace in declares, f"{sport} : espace {namespace} absent du référentiel"


def test_le_normalizer_lit_les_formes_reelles_des_cinq_produits():
    """Chaque particularité encodée ici a coûté des rencontres perdues avant
    d'être vue : le produit american-football imbrique tout sous `game`,
    `Final/OT` arrive avec `short=None`, le basket range son score sous
    `{"total": …}`. Les payloads ci-dessous reproduisent ces formes."""
    from src.agents.quant.gateway.core.identity_resolver import (
        CanonicalEntity,
        IdentityResolver,
    )
    from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
    from src.agents.quant.gateway.sports.pairwise.normalizer import (
        ApiSportsPairwiseNormalizer,
    )

    resolveur = IdentityResolver([
        CanonicalEntity("team:basketball:usa:a", "A", [], {"api_basketball": "1"}),
        CanonicalEntity("team:basketball:usa:b", "B", [], {"api_basketball": "2"}),
        CanonicalEntity("team:american_football:nfl:a", "A", [], {"api_american_football": "1"}),
        CanonicalEntity("team:american_football:nfl:b", "B", [], {"api_american_football": "2"}),
    ])
    equipes = {"home": {"id": 1}, "away": {"id": 2}}

    # Basket : score imbriqué sous `total`, date ISO à plat.
    basket = [{"id": 9, "date": "2024-03-01T20:00:00+00:00",
               "status": {"short": "FT"}, "teams": equipes,
               "scores": {"home": {"total": 110}, "away": {"total": 98}}}]
    # Football américain : tout sous `game`, statut long uniquement.
    nfl = [{"game": {"id": 7, "date": {"timestamp": 1709323200},
                     "status": {"short": None, "long": "Final/OT"}},
            "teams": equipes, "scores": {"home": {"total": 24}, "away": {"total": 20}}}]

    for sport, brut, attendu in (("basketball", basket, 110), ("american_football", nfl, 24)):
        charge = ApiSportsPairwiseNormalizer(sport).normalize_fixtures(
            RawProviderResponse(payload={"fixtures": brut}, provider="api_sports",
                                fetched_at=_DECISION, request_metadata={}),
            resolveur, "competition:x:y:z", "2024")
        assert len(charge.matches) == 1, sport
        match = charge.matches[0]
        assert match.status == "FINISHED" and match.goals_home == attendu, sport
        assert match.kickoff is not None


def test_une_equipe_inconnue_est_ecartee_jamais_devinee():
    """Un rattachement par proximité de nom rattacherait une rencontre à la
    mauvaise franchise, en silence."""
    from src.agents.quant.gateway.core.identity_resolver import IdentityResolver
    from src.agents.quant.gateway.core.provider_protocol import RawProviderResponse
    from src.agents.quant.gateway.sports.pairwise.normalizer import (
        ApiSportsPairwiseNormalizer,
    )

    charge = ApiSportsPairwiseNormalizer("hockey").normalize_fixtures(
        RawProviderResponse(
            payload={"fixtures": [{"id": 1, "date": "2024-03-01T20:00:00+00:00",
                                   "status": {"short": "FT"},
                                   "teams": {"home": {"id": 999}, "away": {"id": 998}},
                                   "scores": {"home": 3, "away": 2}}]},
            provider="api_sports", fetched_at=_DECISION, request_metadata={}),
        IdentityResolver([]), "competition:hockey:usa:nhl", "2024")

    assert charge.matches == []
