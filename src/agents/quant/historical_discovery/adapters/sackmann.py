"""Lecteur des bases tennis Jeff Sackmann / Tennis Abstract (CC BY-NC-SA 4.0).

LICENCE — À LIRE AVANT D'ÉTENDRE L'USAGE. Ces données sont sous
`Creative Commons Attribution-NonCommercial-ShareAlike 4.0`. Trois obligations,
et la deuxième est une VRAIE limite, pas une formalité :

  · Attribution — `ATTRIBUTION` ci-dessous, portée dans la provenance de chaque
    observation et dans l'en-tête de toute fixture produite ;
  · NonCommercial — usage personnel uniquement. Aucune revente, aucun service
    payant, aucune exploitation commerciale, directe ou indirecte ;
  · ShareAlike — toute base DÉRIVÉE qui serait redistribuée devrait l'être sous
    la même licence. Un usage privé ne redistribue rien, donc ne déclenche pas
    cette clause — mais publier le corpus fusionné la déclencherait.

Le dépôt d'origine (`JeffSackmann/tennis_atp`) a été SUPPRIMÉ — HTTP 404 au
2026-08-13. Les données lues ici viennent d'un fork qui porte le texte de licence
en clair. C'est aussi pourquoi elles s'arrêtent en 2018 : personne n'alimente
plus ce miroir.

LA DATE EST CELLE DU TOURNOI, PAS DU MATCH. `tourney_date` vaut pour toutes les
rencontres d'une même épreuve. Utilisée telle quelle, la finale d'un Challenger
du dimanche informerait une prédiction du mercredi précédent — une fuite d'une
semaine, invisible dans les métriques. On décale donc au terme présumé du tournoi
(`DECALAGE_FIN_TOURNOI`) : rien de ce qui s'y joue ne peut informer une décision
antérieure à sa fin. C'est délibérément CONSERVATEUR — au pire on ignore une
information réelle pendant quelques jours, jamais l'inverse.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..evidence import HistoricalMatchEvidence, utcnow

SOURCE = "sackmann"
LICENCE = "CC-BY-NC-SA-4.0"
ATTRIBUTION = ("Tennis databases, files, and algorithms by Jeff Sackmann / "
               "Tennis Abstract, licensed under CC BY-NC-SA 4.0 "
               "(http://creativecommons.org/licenses/by-nc-sa/4.0/)")
MIROIRS = {
    "atp": "https://github.com/stakah/tennis_atp",
}

#: Durée après laquelle un tournoi est réputé terminé. Une semaine couvre un
#: Challenger, un Future et un tournoi ATP ordinaire ; les Grand Chelems durent
#: deux semaines, mais leur tableau final vient de tennis-data.co.uk, qui date
#: chaque rencontre au jour près.
DECALAGE_FIN_TOURNOI = timedelta(days=7)

#: Circuits, tels que Sackmann nomme ses fichiers. Le NIVEAU compte : un modèle
#: qui mélangerait un Future et un Grand Chelem sans le savoir apprendrait une
#: force moyenne sur deux populations sans rapport.
CIRCUITS = {
    "atp_matches_qual_chall_": "challenger_qualifying",
    "atp_matches_futures_": "futures",
    "atp_matches_": "tour",
}

_RE_ANNEE = re.compile(r"(\d{4})\.csv$")


@dataclass(frozen=True)
class ParseResult:
    evidences: tuple[HistoricalMatchEvidence, ...]
    unparsed: tuple[str, ...]
    n_lignes: int
    circuit: str = ""

    @property
    def resume(self) -> dict:
        return {"circuit": self.circuit, "lignes": self.n_lignes,
                "rencontres": len(self.evidences), "non_analysees": len(self.unparsed)}


def circuit_du_fichier(nom: str) -> str | None:
    """Le circuit se lit dans le NOM du fichier, jamais dans son contenu : les
    colonnes sont identiques d'un circuit à l'autre."""
    for prefixe, circuit in sorted(CIRCUITS.items(), key=lambda kv: -len(kv[0])):
        if nom.startswith(prefixe):
            return circuit
    return None


def _entier(v):
    v = (v or "").strip()
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parser(texte: str, *, tour: str, circuit: str, competition_id: str,
           provenance: str, retrieved_at: datetime | None = None) -> ParseResult:
    """CSV Sackmann -> observations historiques.

    L'issue est TOUJOURS `p1` : le format range le vainqueur en premier. Ce n'est
    pas une convention neutre — un modèle entraîné sur ce corpus sans le savoir
    apprendrait « le premier gagne toujours ». Le consommateur doit donc
    mélanger les rôles lui-même, et l'ordre est documenté ici plutôt que
    supposé ailleurs.
    """
    lu_a = retrieved_at or utcnow()
    evidences: list[HistoricalMatchEvidence] = []
    unparsed: list[str] = []
    lignes = list(csv.DictReader(io.StringIO(texte)))

    for r in lignes:
        jour = (r.get("tourney_date") or "").strip()
        gagnant = (r.get("winner_name") or "").strip()
        perdant = (r.get("loser_name") or "").strip()
        if len(jour) != 8 or not jour.isdigit() or not gagnant or not perdant:
            unparsed.append(str(r)[:140])
            continue
        try:
            debut = datetime.strptime(jour, "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            unparsed.append(str(r)[:140])
            continue

        tid = (r.get("tourney_id") or "").strip()
        rnd = (r.get("round") or "").strip()
        evidences.append(HistoricalMatchEvidence(
            sport="tennis", source=SOURCE,
            source_event_id=f"{tid}|{rnd}|{gagnant}|{perdant}",
            competition=competition_id, season=jour[:4],
            participants=(gagnant, perdant),
            scheduled_at=debut + DECALAGE_FIN_TOURNOI,
            status="FINISHED", outcome="p1",
            score=(r.get("score") or "").strip() or None,
            provenance=provenance, license=LICENCE, retrieved_at=lu_a,
            timezone_verified=False,
            sport_specific={
                "tour": tour,
                "circuit": circuit,
                "tourney_id": tid,
                "tourney_name": (r.get("tourney_name") or "").strip() or None,
                "tourney_level": (r.get("tourney_level") or "").strip() or None,
                "surface": (r.get("surface") or "").strip() or None,
                "round": rnd or None,
                "best_of": _entier(r.get("best_of")),
                "winner_id": (r.get("winner_id") or "").strip() or None,
                "loser_id": (r.get("loser_id") or "").strip() or None,
                "winner_rank": _entier(r.get("winner_rank")),
                "loser_rank": _entier(r.get("loser_rank")),
                # La date BRUTE reste lisible : sans elle, le décalage
                # conservateur deviendrait indiscernable d'une vraie date.
                "tourney_date": jour,
                "date_decalee_de_jours": DECALAGE_FIN_TOURNOI.days,
                "attribution": ATTRIBUTION}))

    return ParseResult(tuple(evidences), tuple(unparsed), len(lignes), circuit)


#: Encodages essayés, dans l'ordre. Les fichiers anciens sont en Windows-1252 ;
#: les récents en UTF-8. Décoder « au mieux » avec `errors="replace"` remplacerait
#: les lettres accentuées par des losanges — et deux orthographes d'un même joueur
#: deviendraient deux joueurs. Un fichier qu'aucun encodage ne lit est REFUSÉ.
_ENCODAGES = ("utf-8-sig", "cp1252", "latin-1")


def _decoder(octets: bytes) -> tuple[str, str]:
    for encodage in _ENCODAGES:
        try:
            return octets.decode(encodage), encodage
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(
        "sackmann", octets, 0, 1,
        f"aucun encodage parmi {_ENCODAGES} ne lit ce fichier")


def lire_repertoire(chemin, *, tour: str, competition_id: str,
                    annees=None, circuits=None) -> ParseResult:
    """Tous les CSV Sackmann d'un répertoire LOCAL. Aucun téléchargement ici —
    l'acquisition reste une étape distincte, explicite et auditable."""
    from pathlib import Path

    dossier = Path(chemin)
    evidences: list[HistoricalMatchEvidence] = []
    unparsed: list[str] = []
    lignes = 0
    for fichier in sorted(dossier.glob("*.csv")):
        circuit = circuit_du_fichier(fichier.name)
        if circuit is None or (circuits and circuit not in circuits):
            continue
        m = _RE_ANNEE.search(fichier.name)
        if annees and (m is None or int(m.group(1)) not in annees):
            continue
        texte, _encodage = _decoder(fichier.read_bytes())
        r = parser(texte, tour=tour, circuit=circuit,
                   competition_id=competition_id,
                   provenance=f"{MIROIRS.get(tour, '')}/blob/master/{fichier.name}")
        evidences.extend(r.evidences)
        unparsed.extend(r.unparsed)
        lignes += r.n_lignes
    return ParseResult(tuple(evidences), tuple(unparsed), lignes, "|".join(sorted(circuits or CIRCUITS.values())))
