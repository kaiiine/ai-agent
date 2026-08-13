"""Récence du CORPUS HISTORIQUE — grandeur DISTINCTE de la fraîcheur live.

Deux questions différentes portaient le même nom :

    freshness_score    la donnée live/provider utilisée AU POINT DE DÉCISION
                       est-elle récente ? (cotes, forme, classement du jour)

    dataset_recency    le corpus historique qui a servi à construire les
                       features s'arrête-t-il quand ?

Un modèle peut très bien reposer sur un dataset arrêté en 2023 tout en évaluant
un match d'aujourd'hui avec des cotes fraîches — et l'inverse. Les fondre sous un
seul champ ferait qu'un dataset ancien rendrait « périmée » une cote observée il
y a trente secondes, ou qu'un dataset récent ferait passer pour fraîche une
donnée live absente.

Cette mesure est donc **observable et auditable, sans seuil**. Elle ne participe
à aucun verdict de maturité et ne remplit jamais `CandidateBet.freshness_score` :
transformer une récence de corpus en fraîcheur de cote serait exactement la
confusion qu'on vient de séparer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

MEASURABLE = "MEASURABLE"
NOT_MEASURABLE = "NOT_MEASURABLE"


@dataclass(frozen=True)
class DatasetRecency:
    """Mesure brute. Aucun score dérivé tant qu'aucune politique ne le justifie —
    un score demanderait une échelle, donc une décision qui n'est pas prise."""

    source: str
    last_observation_at: datetime | None
    age: timedelta | None
    status: str

    @property
    def age_days(self) -> int | None:
        return None if self.age is None else self.age.days

    def describe(self) -> str:
        if self.status != MEASURABLE:
            return f"{self.source} : {NOT_MEASURABLE}"
        return (f"{self.source} : dernière observation "
                f"{self.last_observation_at:%Y-%m-%d} ({self.age_days} jours)")


def measure(
    dates: Iterable[datetime], *, source: str, as_of: datetime | None = None,
) -> DatasetRecency:
    """Récence d'un corpus, depuis les dates de ses observations.

    Un corpus vide, ou dont aucune date n'est exploitable, est NON MESURABLE —
    jamais « ancien de zéro jour », qui se lirait comme parfaitement à jour.
    """
    as_of = as_of or datetime.now(timezone.utc)
    valides = [_aware(d) for d in dates if isinstance(d, datetime)]
    if not valides:
        return DatasetRecency(source, None, None, NOT_MEASURABLE)
    dernier = max(valides)
    return DatasetRecency(source, dernier, as_of - dernier, MEASURABLE)


def _aware(moment: datetime) -> datetime:
    """Un naïf est supposé UTC — les datasets embarqués sont datés en UTC ou en
    date seule. C'est explicite ici plutôt que dispersé dans chaque loader."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


# ── Corpus par modèle ─────────────────────────────────────────────────────────
def _dates_pairwise(loader: Callable) -> Callable[[], list[datetime]]:
    def dates() -> list[datetime]:
        games, _ = loader()
        return [g.tipoff for g in games]
    return dates


def _dates_tennis(tour: str) -> Callable[[], list[datetime]]:
    def dates() -> list[datetime]:
        from .sports.tennis.tennis_data_loader import load_tennis_data
        # `tourney_date` est la date du TOURNOI : la seule date portée par match
        # dans ce corpus. Elle peut être un `date` — on l'élève en datetime
        # plutôt que de l'ignorer.
        return [_as_datetime(m.tourney_date) for m in load_tennis_data(tour).matches]
    return dates


def _dates_corpus(nom_loader: str) -> Callable[[], list[datetime]]:
    """Corpus déjà canonique : le chargeur n'attend pas d'`IdentityResolver`."""
    def dates() -> list[datetime]:
        from .calibration import historical_dataset

        matches, _fp, _n = getattr(historical_dataset, nom_loader)()
        return [_as_datetime(m.kickoff) for m in matches]
    return dates


def _dates_football(nom_loader: str) -> Callable[[], list[datetime]]:
    """Chaque championnat a SON corpus. Les faire tous pointer sur la Ligue 1
    daterait la Serie A par des matchs français."""
    def dates() -> list[datetime]:
        from src.agents.quant.gateway.core.identity_data import TEAMS
        from src.agents.quant.gateway.core.identity_resolver import IdentityResolver

        from .calibration import historical_dataset

        loader = getattr(historical_dataset, nom_loader)
        matches, _fingerprint, _n = loader(IdentityResolver(TEAMS))
        return [_as_datetime(getattr(m, "kickoff", None)) for m in matches]
    return dates


def _as_datetime(valeur) -> datetime | None:
    """`date` -> `datetime` UTC. Un corpus daté au jour n'est pas moins mesurable
    qu'un corpus daté à la seconde ; le refuser perdrait la mesure entière."""
    from datetime import date as _date

    if isinstance(valeur, datetime):
        return valeur
    if isinstance(valeur, _date):
        return datetime(valeur.year, valeur.month, valeur.day, tzinfo=timezone.utc)
    return None


def _providers() -> dict[str, tuple[str, Callable[[], list[datetime]]]]:
    """`clé readiness -> (source, dates)`. Les clés sont celles de
    `readiness_cli._ASSESSORS` : une seule table de noms pour l'utilisateur."""
    from .sports.american_football.moneyline import load_nfl_games
    from .sports.baseball.moneyline import load_mlb_games
    from .sports.basketball.moneyline import load_nba_games
    from .sports.hockey.regulation import load_nhl_regulation
    from .sports.volleyball.moneyline import load_volleyball_games

    return {
        # Le libellé nomme le fichier RÉELLEMENT lu. Il est resté figé sur
        # `nfl_api_sports_games.json` après que le modèle eut basculé sur le
        # corpus backfillé : le rapport de fraîcheur citait alors une source qui
        # n'alimentait plus rien, ce qui est pire qu'une absence de libellé.
        "nfl": ("nfl_backfilled_games.json (api_sports + nflverse)",
                _dates_pairwise(load_nfl_games)),
        "mlb": ("mlb_api_sports_games.json", _dates_pairwise(load_mlb_games)),
        "nba": ("nba_api_sports_games.json", _dates_pairwise(load_nba_games)),
        "nhl": ("nhl_api_sports_games.json", _dates_pairwise(load_nhl_regulation)),
        "volley": ("volley_api_sports_games.json", _dates_pairwise(load_volleyball_games)),
        # Corpus backfillés : la fraîcheur se lit sur le corpus RÉELLEMENT chargé.
        # Sans entrée, le rapport affichait « NOT_MEASURABLE » pour un dataset
        # pourtant daté — un trou d'instrumentation qui ressemble à un trou de données.
        "champions-league": ("cl_backfilled_matches.json (fdo + api_sports + openfootball)",
                             _dates_corpus("load_cl")),
        "europa-league": ("el_backfilled_matches.json (openfootball)",
                          _dates_corpus("load_el")),
        "conference-league": ("conf_backfilled_matches.json (openfootball)",
                              _dates_corpus("load_conf")),
        # « sackmann » était trompeur : le chargeur lit tennis-data.co.uk, pas
        # les CSV Jeff Sackmann — dont les dépôts publics ont d'ailleurs disparu
        # (HTTP 404, vérifié le 2026-08-13). Nommer la vraie source évite de
        # croire couvert le circuit Challenger, qui ne l'est pas.
        "atp": ("tennis_data_atp_2000_2026.csv.gz (tennis-data.co.uk) + "
                "tennis_sackmann_atp_backfill.csv.gz (Sackmann, CC BY-NC-SA 4.0, "
                "Challenger/qualifs jusqu'en 2018)", _dates_tennis("atp")),
        "wta": ("tennis_data_wta_2000_2026.csv.gz (tennis-data.co.uk) + "
                "tennis_kaggle_wta_backfill.csv.gz (Kaggle atpwta-tennis-data v1, "
                "CC BY-NC-SA 4.0, tour/Fed Cup/ITF jusqu'en 2021)",
                _dates_tennis("wta")),
        **{cle: (f"{fichier}_2025_matches.json", _dates_football(loader))
           for cle, fichier, loader in (
               ("fl1", "fl1", "load_fl1_2025"),
               ("serie-a", "sa", "load_sa_2025"),
               ("laliga", "pd", "load_pd_2025"),
               ("bundesliga", "bl1", "load_bl1_2025"),
               ("championship", "elc", "load_elc_2025"),
               ("eredivisie", "ded", "load_ded_2025"),
               ("primeira-liga", "ppl", "load_ppl_2025"),
           )},
    }


def for_model(cle: str, *, as_of: datetime | None = None) -> DatasetRecency:
    """Récence du corpus d'un modèle, ou NON MESURABLE si son corpus n'est pas
    accessible ici. Une erreur de chargement ne fait jamais tomber `readiness` :
    le diagnostic doit rester lisible même quand une source manque."""
    entree = _providers().get(cle)
    if entree is None:
        return DatasetRecency(cle, None, None, NOT_MEASURABLE)
    source, dates = entree
    try:
        return measure(dates(), source=source, as_of=as_of)
    except Exception:   # noqa: BLE001
        return DatasetRecency(source, None, None, NOT_MEASURABLE)
