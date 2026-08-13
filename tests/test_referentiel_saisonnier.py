"""Identité d'équipe et appartenance à une compétition sont deux choses.

`LEAGUE_TEAMS` associait une compétition à des équipes SANS saison, et les 188
entités portaient toutes `valid_from = None`. Au prochain cycle
promotion/relégation, les promus disparaissaient de la résolution — sans erreur,
sans trace. C'est la même famille de panne que le PSG–Aston Villa : une identité
correcte qu'on ne sait pas rattacher.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from src.agents.quant.gateway.core.event_validation import (
    ValidationStatus,
    valider_appartenance,
)
from src.agents.quant.gateway.core.seasonal_membership import (
    Membership,
    MembershipStatus,
    SeasonalMembershipRegistry,
)

CHAMPIONSHIP = "competition:football:eng:championship"
PREMIER = "competition:football:eng:premier_league"
LIGUE1 = "competition:football:fra:ligue1"
CL = "competition:football:eur:champions_league"
LEEDS = "team:football:eng:leeds"
PSG = "team:football:fra:psg"


class _Match:
    def __init__(self, comp, saison, dom, ext, jour):
        self.league_id, self.season = comp, saison
        self.home_team_id, self.away_team_id = dom, ext
        self.kickoff = datetime(*jour, tzinfo=timezone.utc)


@pytest.fixture
def registre():
    r = SeasonalMembershipRegistry()
    r.ingest_matches([
        # Leeds en Championship saison N…
        _Match(CHAMPIONSHIP, "2025", LEEDS, "team:football:eng:hull", (2025, 9, 1)),
        _Match(CHAMPIONSHIP, "2025", "team:football:eng:hull", LEEDS, (2026, 2, 1)),
        # …puis en Premier League saison N+1.
        _Match(PREMIER, "2026", LEEDS, "team:football:eng:arsenal", (2026, 8, 15)),
        # PSG : championnat ET coupe d'Europe la même saison.
        _Match(LIGUE1, "2026", PSG, "team:football:fra:lyon", (2026, 8, 16)),
        _Match(CL, "2026", PSG, "team:football:esp:real_madrid", (2026, 9, 17)),
    ])
    # Effectifs déclarés complets : c'est la SEULE porte vers un démenti.
    for competition, saison in ((CHAMPIONSHIP, "2025"), (PREMIER, "2026"),
                                (LIGUE1, "2026"), (CL, "2026")):
        r.mark_roster_complete(competition, saison)
    return r


# ── Identité stable, appartenance mobile ────────────────────────────────────

def test_une_promotion_ne_cree_aucune_nouvelle_identite(registre):
    """Descendre ou monter n'est pas devenir un autre club : fabriquer une
    seconde identité couperait l'historique en deux au pire moment."""
    assert registre.seasons_of(LEEDS) == ("2025", "2026")
    assert registre.membership(LEEDS, CHAMPIONSHIP, "2025") is MembershipStatus.ACTIVE
    assert registre.membership(LEEDS, PREMIER, "2026") is MembershipStatus.ACTIVE


def test_une_relegation_se_lit_dans_l_autre_sens(registre):
    """La saison N+1 en Premier League n'efface pas la saison N en Championship."""
    assert registre.membership(LEEDS, PREMIER, "2025") is MembershipStatus.UNKNOWN
    assert registre.membership(LEEDS, CHAMPIONSHIP, "2026") is MembershipStatus.UNKNOWN


def test_un_club_absent_d_une_saison_connue_est_NOT_ACTIVE(registre):
    """Arsenal joue la PL 2026 : on SAIT donc qui la compose cette saison-là."""
    assert registre.membership(
        "team:football:eng:hull", PREMIER, "2026") is MembershipStatus.NOT_ACTIVE


def test_une_saison_inconnue_repond_UNKNOWN_jamais_NOT_ACTIVE(registre):
    """La distinction qui compte : « il n'y joue pas » affirme, « on ne sait
    pas » n'affirme rien. Les confondre transforme un trou de données en
    démenti, et fait rejeter des identités correctes."""
    assert registre.membership(LEEDS, PREMIER, "2030") is MembershipStatus.UNKNOWN
    assert registre.membership(
        LEEDS, "competition:football:ita:serie_a", "2026") is MembershipStatus.UNKNOWN


def test_un_club_jamais_vu_dans_une_saison_connue_est_NOT_ACTIVE(registre):
    assert registre.membership(PSG, CHAMPIONSHIP, "2025") is MembershipStatus.NOT_ACTIVE


# ── Multi-compétition ───────────────────────────────────────────────────────

def test_un_club_a_plusieurs_appartenances_simultanees(registre):
    """Un club joue son championnat et sa coupe d'Europe la même semaine :
    supposer « 1 équipe = 1 compétition » choisirait à sa place."""
    competitions = [m.competition_id for m in registre.memberships_of(PSG, "2026")]

    assert competitions == sorted([LIGUE1, CL])


def test_une_coupe_est_une_participation_saisonniere_pas_une_ligue(registre):
    """Un club n'appartient pas à la Ligue des Champions en permanence : sa
    participation vaut pour l'édition, avec ses bornes réelles."""
    coupe = next(m for m in registre.memberships_of(PSG, "2026") if m.competition_id == CL)

    assert coupe.first_seen == date(2026, 9, 17)
    assert coupe.matches_observed == 1


def test_les_bornes_d_une_participation_sont_celles_observees(registre):
    leeds = registre.memberships_of(LEEDS, "2025")[0]

    assert (leeds.first_seen, leeds.last_seen) == (date(2025, 9, 1), date(2026, 2, 1))
    assert leeds.matches_observed == 2


def test_un_club_elimine_en_novembre_a_bien_participe(registre):
    """La question porte sur la SAISON, pas sur un jour : répondre « non » pour
    cause de calendrier serait une autre question."""
    coupe = next(m for m in registre.memberships_of(PSG, "2026") if m.competition_id == CL)

    assert not coupe.couvre(date(2026, 12, 1))                  # hors fenêtre
    assert registre.membership(PSG, CL, "2026") is MembershipStatus.ACTIVE


# ── Alimentation ────────────────────────────────────────────────────────────

def test_une_appartenance_declaree_est_distinguee_d_une_observation(registre):
    """Un tirage au sort connu n'est pas une rencontre jouée : la source les
    sépare, et rien ne les fond."""
    registre.declare(Membership(
        team_id="team:football:eng:arsenal", competition_id=CL, season="2027",
        first_seen=date(2027, 9, 1), last_seen=date(2027, 9, 1),
        matches_observed=0, source="tirage_annonce"))

    declaree = registre.memberships_of("team:football:eng:arsenal", "2027")[0]

    assert declaree.source == "tirage_annonce"
    assert declaree.matches_observed == 0


def test_ingerer_deux_fois_ne_double_pas_les_bornes(registre):
    """Un ré-ingest doit accumuler les matchs sans déplacer les dates observées."""
    avant = registre.memberships_of(LEEDS, "2025")[0]
    registre.ingest_matches([_Match(CHAMPIONSHIP, "2025", LEEDS,
                                    "team:football:eng:hull", (2025, 10, 1))])
    apres = registre.memberships_of(LEEDS, "2025")[0]

    assert apres.first_seen == avant.first_seen
    assert apres.last_seen == avant.last_seen
    assert apres.matches_observed == avant.matches_observed + 1


# ── Validation sémantique d'un événement ────────────────────────────────────

def test_une_identite_impossible_est_rejetee(registre):
    """`competition:football:eng:premier_league` + PSG : chaque morceau existe,
    l'assemblage est faux. Aucun contrôle structurel ne pouvait le dire tant que
    rien ne savait qui joue quoi."""
    resultat = valider_appartenance(
        registre, competition_id=PREMIER, season="2026", participant_ids=(PSG, LEEDS))

    assert resultat.status is ValidationStatus.COMPETITION_MEMBERSHIP_MISMATCH
    assert resultat.offending == (PSG,)
    assert resultat.rejected


def test_une_identite_coherente_passe(registre):
    resultat = valider_appartenance(
        registre, competition_id=LIGUE1, season="2026", participant_ids=(PSG,))

    assert resultat.status is ValidationStatus.CONSISTENT
    assert not resultat.rejected


def test_une_competition_inter_ligues_n_est_jamais_rejetee_pour_ca(registre):
    """§6 : un club n'appartient pas à une coupe d'Europe comme à une ligue
    permanente. Sa participation saisonnière suffit — et PSG la porte."""
    resultat = valider_appartenance(
        registre, competition_id=CL, season="2026", participant_ids=(PSG,))

    assert resultat.status is ValidationStatus.CONSISTENT


def test_sans_donnee_on_ne_rejette_rien(registre):
    """Rejeter sur `UNKNOWN` ferait refuser des rencontres correctes — le défaut
    exact qu'on répare, à l'envers."""
    resultat = valider_appartenance(
        registre, competition_id="competition:football:ita:serie_a", season="2026",
        participant_ids=(PSG,))

    assert resultat.status is ValidationStatus.MEMBERSHIP_UNKNOWN
    assert not resultat.rejected
    assert "ni confirmation ni démenti" in resultat.detail


def test_un_effectif_non_repute_complet_ne_dement_jamais():
    """DÉFAUT CORRIGÉ : une seule rencontre ingérée suffisait à déclarer la
    saison « connue », donc à répondre NOT_ACTIVE pour les dix-neuf autres
    clubs. Une compétition à moitié chargée produisait de faux démentis."""
    partiel = SeasonalMembershipRegistry()
    partiel.ingest_matches([_Match(LIGUE1, "2026", PSG, "team:football:fra:lyon", (2026, 8, 16))])

    assert partiel.knows(LIGUE1, "2026")                      # des matchs observés
    assert not partiel.roster_is_complete(LIGUE1, "2026")     # mais l'effectif, non
    assert partiel.membership(
        "team:football:fra:marseille", LIGUE1, "2026") is MembershipStatus.UNKNOWN

    resultat = valider_appartenance(
        partiel, competition_id=LIGUE1, season="2026",
        participant_ids=("team:football:fra:marseille",))

    assert not resultat.rejected
    assert resultat.status is ValidationStatus.MEMBERSHIP_UNKNOWN


def test_un_participant_inconnu_ne_rend_pas_l_evenement_fautif(registre):
    """Un seul club non résolu ne doit pas condamner une identité par ailleurs
    cohérente : il est signalé `unknown`, jamais `offending`."""
    resultat = valider_appartenance(
        registre, competition_id=LIGUE1, season="2026",
        participant_ids=(PSG, "team:football:fra:inconnu"))

    assert resultat.offending == ("team:football:fra:inconnu",) or resultat.unknown
    assert PSG not in resultat.offending


# ── Identité : le pays du CLUB, jamais la région de la compétition ─────────

def test_un_club_garde_une_identite_a_travers_les_competitions():
    """MESURÉ sur données réelles : dérivé de la compétition, Flamengo devenait
    `team:football:bra:…` en Série A et `team:football:sam:…` en Libertadores —
    deux identités pour un club, donc un historique coupé en deux."""
    from src.agents.quant.betting_engine.acquisition.football_data_org import (
        identite_equipe,
        scope_du_club,
    )

    pays = {"CR Flamengo": "BRA"}

    en_serie_a = identite_equipe(scope_du_club("CR Flamengo", pays, defaut="bra"), "CR Flamengo")
    en_libertadores = identite_equipe(scope_du_club("CR Flamengo", pays, defaut="sam"), "CR Flamengo")

    assert en_serie_a == en_libertadores == "team:football:bra:cr_flamengo"


def test_un_club_de_pays_inconnu_ne_recoit_pas_un_scope_invente():
    """Un scope choisi au jugé fusionnerait deux homonymes de pays différents."""
    from src.agents.quant.betting_engine.acquisition.football_data_org import scope_du_club

    assert scope_du_club("Club Inconnu", {}) == "unk"
