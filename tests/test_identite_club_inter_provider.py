"""Un même club, deux providers, une seule identité canonique.

football-data.org appelle `AFC Ajax` ce qu'api-sports nomme `Ajax`. Sans
rapprochement, la fusion des deux historiques de Ligue des Champions n'appariait
que 14 doublons sur 1 210 rencontres : concaténer aurait doublé l'échantillon et
fait franchir `min_sample_size` par duplication.

MESURÉ sur les référentiels réels (63 clubs football-data.org, 145 api-sports) :
50 VERIFIED, 0 AMBIGUOUS, 13 UNRESOLVED. Le dédoublonnage passe alors de 14 à
238 doublons appariés, et fait apparaître 3 conflits réels — api-sports rapporte
le score réglementaire là où football-data.org compte les tirs au but.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.agents.quant.gateway.core.club_identity_resolution import (
    SIGNAUX_MIN,
    ClubIdentityRegistry,
    ProviderTeam,
    ResolutionStatus,
    construire_registre,
    nom_canonique,
    resoudre,
    resume,
)

AJAX_FDO = ProviderTeam("football_data_org", "678", "AFC Ajax", "AJA",
                        "Netherlands", 1900, "Johan Cruijff ArenA")
AJAX_APS = ProviderTeam("api_sports", "194", "Ajax", "AJA",
                        "Netherlands", 1900, "Johan Cruijff ArenA")


def _canon(team: ProviderTeam) -> str:
    return f"team:football:nld:{nom_canonique(team.name)}"


# ── Même club, deux identifiants provider ──────────────────────────────────

def test_un_meme_club_converge_vers_une_seule_identite():
    registre = construire_registre(resoudre([AJAX_FDO], [AJAX_APS]), _canon)

    assert registre.canonical_for("football_data_org", "678") == \
           registre.canonical_for("api_sports", "194")


def test_un_alias_de_nom_ne_cree_jamais_une_nouvelle_equipe():
    """`Ajax`, `AFC Ajax`, `Ajax Amsterdam` : le nom est un alias, pas l'identité."""
    registre = construire_registre(resoudre([AJAX_FDO], [AJAX_APS]), _canon)
    canonique = registre.canonical_for("api_sports", "194")

    assert len(registre) == 2                      # deux alias, une identité
    assert set(registre.aliases_of(canonique)) == {"AFC Ajax", "Ajax"}


def test_le_pays_prouve_remplace_un_scope_inconnu():
    """`team:football:unk:ajax` ne doit pas survivre quand la nation est connue."""
    resolution = resoudre([AJAX_FDO], [AJAX_APS])[0]

    assert resolution.status is ResolutionStatus.VERIFIED
    assert "unk" not in _canon(resolution.left)


def test_les_signaux_retenus_sont_rapportes():
    """Une correspondance sans preuve consultable ne s'audite pas."""
    resolution = resoudre([AJAX_FDO], [AJAX_APS])[0]

    assert len(resolution.signals) >= SIGNAUX_MIN
    assert set(resolution.signals) <= {"code", "founded", "venue", "nom"}


# ── Ce qui n'est pas prouvé ne passe pas ───────────────────────────────────

def test_un_seul_signal_commun_ne_suffit_pas():
    """Deux clubs d'un même pays partagent souvent une année de fondation."""
    seul = ProviderTeam("api_sports", "999", "Autre Club", None, "Netherlands", 1900, None)

    assert resoudre([AJAX_FDO], [seul])[0].status is ResolutionStatus.UNRESOLVED


def test_deux_candidats_egaux_restent_AMBIGUOUS():
    """AMBIGUOUS n'est pas UNRESOLVED : plusieurs candidats se disputent le
    rapprochement, et c'est un humain qui doit trancher."""
    jumeau_a = ProviderTeam("api_sports", "1", "Ajax", "AJA", "Netherlands", 1900, None)
    jumeau_b = ProviderTeam("api_sports", "2", "Ajax", "AJA", "Netherlands", 1900, None)

    resolution = resoudre([AJAX_FDO], [jumeau_a, jumeau_b])[0]

    assert resolution.status is ResolutionStatus.AMBIGUOUS
    assert set(resolution.candidates) == {"1", "2"}


def test_deux_clubs_visant_la_meme_cible_sont_AMBIGUOUS():
    """Une correspondance 1:n n'est pas une correspondance, quel que soit le sens."""
    frere = ProviderTeam("football_data_org", "679", "Ajax", "AJA",
                         "Netherlands", 1900, "Johan Cruijff ArenA")

    statuts = {r.status for r in resoudre([AJAX_FDO, frere], [AJAX_APS])}

    assert statuts == {ResolutionStatus.AMBIGUOUS}


def test_un_pays_different_empeche_tout_rapprochement():
    """Chaque signal est ancré au pays : sans lui, deux homonymes fusionneraient."""
    homonyme = ProviderTeam("api_sports", "500", "Ajax", "AJA", "England", 1900,
                            "Johan Cruijff ArenA")

    assert resoudre([AJAX_FDO], [homonyme])[0].status is ResolutionStatus.UNRESOLVED


def test_un_champ_absent_ne_vaut_jamais_egalite():
    """Deux `None` ne prouvent rien — les compter comme un accord fabriquerait
    des correspondances à partir de trous de données."""
    creux_a = ProviderTeam("football_data_org", "1", "Club X", None, "France", None, None)
    creux_b = ProviderTeam("api_sports", "2", "Club Y", None, "France", None, None)

    assert resoudre([creux_a], [creux_b])[0].status is ResolutionStatus.UNRESOLVED


def test_aucun_rapprochement_flou_n_est_utilise():
    """Deux clubs différents portent souvent des noms proches : une distance de
    chaîne se tromperait au milieu d'un benchmark qui aurait l'air normal."""
    import inspect

    from src.agents.quant.gateway.core import club_identity_resolution

    source = inspect.getsource(club_identity_resolution).lower()

    for interdit in ("difflib", "sequencematcher", "levenshtein", "fuzz", "jaro"):
        assert interdit not in source


def test_la_canonisation_du_nom_est_une_regle_fixe_pas_une_approximation():
    """Retirer « AFC » est déterministe et reproductible ; ce n'est pas une
    mesure de ressemblance."""
    assert nom_canonique("AFC Ajax") == nom_canonique("Ajax") == "ajax"
    assert nom_canonique("FC Bayern München") == nom_canonique("Bayern Munchen")
    assert nom_canonique("Arsenal FC") != nom_canonique("Arsenal Sarandi")


def test_le_resume_compte_les_trois_verdicts():
    compte = resume(resoudre([AJAX_FDO], [AJAX_APS]))

    assert compte == {"total": 1, "VERIFIED": 1, "AMBIGUOUS": 0, "UNRESOLVED": 0}


def test_seules_les_resolutions_verifiees_entrent_au_registre():
    inconnu = ProviderTeam("football_data_org", "0", "Club Inconnu", None, "Suisse", None, None)

    registre = construire_registre(resoudre([AJAX_FDO, inconnu], [AJAX_APS]), _canon)

    assert registre.canonical_for("football_data_org", "0") is None
    assert len(registre) == 2


# ── Dédoublonnage des rencontres, après résolution ─────────────────────────

class _M:
    def __init__(self, mid, dom, ext, ko, dh=2, da=1, comp="competition:football:eur:champions_league"):
        self.canonical_match_id, self.league_id, self.season = mid, comp, "2026"
        self.home_team_id, self.away_team_id = dom, ext
        self.kickoff, self.status = ko, "FINISHED"
        self.goals_home, self.goals_away = dh, da


KO = datetime(2026, 9, 17, 19, tzinfo=timezone.utc)


def test_une_rencontre_vue_par_deux_providers_se_dedoublonne():
    from src.agents.quant.betting_engine.acquisition.reconciliation import reconcilier

    r = reconcilier({"fdo": [_M("f1", "team:a", "team:b", KO)],
                     "aps": [_M("a1", "team:a", "team:b", KO + timedelta(hours=1))]})

    assert r.resume["unique_canonical"] == 1
    assert r.resume["duplicates_matched"] == 1


def test_deux_rencontres_repetees_ne_fusionnent_jamais():
    """Aller-retour, ou deux matchs d'une série : même paire, dates éloignées."""
    from src.agents.quant.betting_engine.acquisition.reconciliation import reconcilier

    r = reconcilier({"fdo": [_M("f1", "team:a", "team:b", KO),
                             _M("f2", "team:a", "team:b", KO + timedelta(days=7))]})

    assert r.resume["unique_canonical"] == 2


def test_un_conflit_de_score_exclut_la_rencontre_du_benchmark():
    """RÉEL : api-sports rapporte 1-1 là où football-data.org compte 4-5 après
    tirs au but. Choisir l'un silencieusement fausserait l'issue apprise."""
    from src.agents.quant.betting_engine.acquisition.reconciliation import reconcilier

    r = reconcilier({"fdo": [_M("f1", "team:a", "team:b", KO, dh=4, da=5)],
                     "aps": [_M("a1", "team:a", "team:b", KO, dh=1, da=1)]})

    assert r.resume["conflicts"] == 1
    assert r.resume["unique_canonical"] == 0


# ── Non-régression ─────────────────────────────────────────────────────────

def test_le_referentiel_saisonnier_reste_multi_competition():
    """La résolution d'identité ne doit écraser aucune appartenance domestique."""
    from src.agents.quant.gateway.core.seasonal_membership import (
        SeasonalMembershipRegistry,
    )

    class _Match:
        def __init__(self, comp):
            self.league_id, self.season = comp, "2026"
            self.home_team_id, self.away_team_id = "team:football:fra:psg", "team:x"
            self.kickoff = KO

    registre = SeasonalMembershipRegistry()
    registre.ingest_matches([_Match("competition:football:fra:ligue1"),
                             _Match("competition:football:eur:champions_league")])

    assert len(registre.memberships_of("team:football:fra:psg", "2026")) == 2


@pytest.mark.parametrize("canonical_id", [
    "competition:football:fra:ligue1",
    "competition:football:eng:premier_league",
    "competition:football:bra:serie_a",
])
def test_aucune_competition_domestique_n_a_disparu(canonical_id):
    from src.agents.quant.gateway.registries.competition_registry import COMPETITIONS

    assert canonical_id in COMPETITIONS


# ── Rapprochement par CALENDRIER — la preuve qui ignore les noms ────────────
# Les métadonnées échouent pour des raisons prosaïques : stade rebaptisé
# (`Anoeta` devenu `Reale Arena`), fondation qui diffère d'un an entre providers,
# club monégasque classé « France » chez l'un et « Monaco » chez l'autre.
# Le calendrier ne dépend d'aucune convention d'écriture.

from src.agents.quant.gateway.core.club_identity_resolution import (   # noqa: E402
    RENCONTRES_MIN,
    resoudre_par_calendrier,
)


class _Fixture:
    def __init__(self, dom, ext, jour):
        self.home_team_id, self.away_team_id = dom, ext
        self.kickoff = datetime(2026, 9, jour, 19, tzinfo=timezone.utc)


def _contexte(n=RENCONTRES_MIN):
    """Un club inconnu de chaque côté, affrontant les MÊMES adversaires ancrés."""
    gauche = [_Fixture("G", f"anc{i}", 10 + i) for i in range(n)]
    droite = [_Fixture("D", f"a{i}", 10 + i) for i in range(n)]
    ancres = {**{f"fdo:anc{i}": f"club#{i}" for i in range(n)},
              **{f"aps:a{i}": f"club#{i}" for i in range(n)}}
    inconnu = ProviderTeam("football_data_org", "G", "Peu importe", None, None, None, None)
    cible = ProviderTeam("api_sports", "D", "Nom Différent", None, None, None, None)
    return gauche, droite, ancres, inconnu, cible


def _resoudre(gauche, droite, ancres, restants, cibles):
    return resoudre_par_calendrier(
        restants, cibles, matches_gauche=gauche, matches_droite=droite, ancres=ancres,
        identite_gauche=lambda i: f"fdo:{i}", identite_droite=lambda i: f"aps:{i}")


def test_des_adversaires_communs_prouvent_l_identite_sans_le_nom():
    g, d, anc, inconnu, cible = _contexte()

    resolution = _resoudre(g, d, anc, [inconnu], [cible])[0]

    assert resolution.status is ResolutionStatus.VERIFIED
    assert resolution.signals == ("calendrier",)
    assert resolution.right.provider_id == "D"


def test_trop_peu_de_rencontres_partagees_ne_prouve_rien():
    """Une seule coïncidence de date et d'adversaire n'est pas une identité."""
    g, d, anc, inconnu, cible = _contexte(n=RENCONTRES_MIN - 1)

    assert _resoudre(g, d, anc, [inconnu], [cible])[0].status is ResolutionStatus.UNRESOLVED


def test_seuls_les_adversaires_deja_ancres_comptent():
    """Sans ancre, un rapprochement de proche en proche propagerait la première
    erreur à tout le graphe."""
    g, d, _anc, inconnu, cible = _contexte()

    assert _resoudre(g, d, {}, [inconnu], [cible])[0].status is ResolutionStatus.UNRESOLVED


def test_deux_calendriers_identiques_restent_AMBIGUOUS():
    g, d, anc, inconnu, cible = _contexte()
    jumeau = [_Fixture("D2", f"a{i}", 10 + i) for i in range(RENCONTRES_MIN)]
    autre = ProviderTeam("api_sports", "D2", "Jumeau", None, None, None, None)

    resolution = _resoudre(g, d + jumeau, anc, [inconnu], [cible, autre])[0]

    assert resolution.status is ResolutionStatus.AMBIGUOUS


def test_le_domicile_distingue_l_aller_du_retour():
    """Rapprocher sans le rôle ferait correspondre un aller à un retour."""
    g = [_Fixture("G", f"anc{i}", 10 + i) for i in range(RENCONTRES_MIN)]
    d = [_Fixture(f"a{i}", "D", 10 + i) for i in range(RENCONTRES_MIN)]   # inversé
    anc = {**{f"fdo:anc{i}": f"club#{i}" for i in range(RENCONTRES_MIN)},
           **{f"aps:a{i}": f"club#{i}" for i in range(RENCONTRES_MIN)}}
    inconnu = ProviderTeam("football_data_org", "G", "X", None, None, None, None)
    cible = ProviderTeam("api_sports", "D", "Y", None, None, None, None)

    assert _resoudre(g, d, anc, [inconnu], [cible])[0].status is ResolutionStatus.UNRESOLVED


def test_le_rapprochement_par_calendrier_n_utilise_aucun_nom():
    import inspect

    from src.agents.quant.gateway.core import club_identity_resolution

    source = inspect.getsource(club_identity_resolution.resoudre_par_calendrier)

    assert "name" not in source and "nom_canonique" not in source
