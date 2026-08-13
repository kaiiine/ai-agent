"""Un même club, deux providers, une seule identité canonique.

football-data.org appelle `AFC Ajax` ce qu'api-sports nomme `Ajax`. Sans
rapprochement, la fusion des deux historiques de Ligue des Champions n'appariait
que 14 doublons sur 1 210 rencontres : concaténer aurait doublé l'échantillon et
fait franchir `min_sample_size` par duplication — un critère de maturité franchi
ainsi est pire qu'un critère non franchi.

DÉTERMINISTE, JAMAIS PROBABILISTE. Aucune distance de chaîne, aucun score de
ressemblance : deux clubs différents portent souvent des noms proches, et un
rapprochement flou se tromperait silencieusement, au milieu d'un benchmark qui
aurait l'air normal. On rapproche sur des FAITS comparables — code club, année de
fondation, stade, pays — et le nom n'est jamais un signal seul.

DEUX SIGNAUX CONCORDANTS, ET UNICITÉ DANS LES DEUX SENS. Un seul fait commun ne
prouve rien (deux clubs d'un même pays peuvent partager une année de fondation) ;
une correspondance qui n'est pas 1:1 n'est pas une correspondance.

TROIS VERDICTS, PAS DEUX. `AMBIGUOUS` n'est pas `UNRESOLVED` : le premier dit que
plusieurs candidats se disputent le rapprochement — un humain doit trancher — le
second qu'aucun ne se présente. Les confondre ferait passer un choix pour une
absence.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

#: Signaux exigés pour qu'un rapprochement soit VERIFIED. Le nom compte parmi
#: eux, jamais à lui seul : c'est la règle qui interdit le rapprochement flou.
SIGNAUX_MIN = 2


class ResolutionStatus(str, Enum):
    VERIFIED = "VERIFIED"        # ≥2 signaux concordants, correspondance 1:1
    AMBIGUOUS = "AMBIGUOUS"      # plusieurs candidats se disputent le rapprochement
    UNRESOLVED = "UNRESOLVED"    # aucun candidat suffisamment étayé


@dataclass(frozen=True)
class ProviderTeam:
    """Ce qu'un provider dit d'un club. Aucun champ n'est obligatoire sauf l'id."""

    provider: str
    provider_id: str
    name: str
    code: str | None = None          # `tla` chez football-data.org, `code` chez api-sports
    country: str | None = None
    founded: int | None = None
    venue: str | None = None


@dataclass(frozen=True)
class Resolution:
    status: ResolutionStatus
    left: ProviderTeam
    right: ProviderTeam | None = None
    signals: tuple[str, ...] = ()
    candidates: tuple[str, ...] = ()      # ids adverses en compétition, si AMBIGUOUS
    detail: str = ""


@dataclass
class ClubIdentityRegistry:
    """`provider:id` -> identité canonique. Une entrée n'existe que si prouvée."""

    par_alias: dict[str, str] = field(default_factory=dict)
    #: identité canonique -> variantes de nom rencontrées. Le nom est un ALIAS,
    #: jamais l'identité : `Ajax`, `AFC Ajax` et `Ajax Amsterdam` coexistent.
    noms: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def declare(self, canonical_id: str, team: ProviderTeam) -> None:
        self.par_alias[f"{team.provider}:{team.provider_id}"] = canonical_id
        self.noms[canonical_id].add(team.name)

    def canonical_for(self, provider: str, provider_id: str) -> str | None:
        return self.par_alias.get(f"{provider}:{provider_id}")

    def aliases_of(self, canonical_id: str) -> tuple[str, ...]:
        return tuple(sorted(self.noms.get(canonical_id, ())))

    def __len__(self) -> int:
        return len(self.par_alias)


# ── Normalisation : canonisation exacte, jamais approximation ────────────────

def _plat(valeur: str | None) -> str:
    if not valeur:
        return ""
    sans_accent = "".join(c for c in unicodedata.normalize("NFD", valeur)
                          if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", sans_accent.lower())


#: Affixes de forme juridique/sportive, sans valeur distinctive. Les retirer est
#: une CANONISATION (règle fixe, réversible en lecture), pas un rapprochement
#: approximatif : « Ajax » et « AFC Ajax » deviennent la même chaîne exacte.
_AFFIXES = ("fc", "afc", "cf", "sc", "ac", "as", "sv", "vf", "vfb", "vfl", "bv",
            "sk", "fk", "nk", "hnk", "gnk", "ss", "ssc", "us", "rc", "rcd", "cd",
            "ca", "club", "cp", "sl", "sd", "bsc", "tsg", "rb", "psv", "spor")


def nom_canonique(nom: str | None) -> str:
    """Nom réduit à sa part distinctive. Un ALIAS de plus, jamais une identité."""
    plat = _plat(nom)
    for affixe in sorted(_AFFIXES, key=len, reverse=True):
        if plat.startswith(affixe) and len(plat) > len(affixe) + 2:
            plat = plat[len(affixe):]
        if plat.endswith(affixe) and len(plat) > len(affixe) + 2:
            plat = plat[: -len(affixe)]
    return plat


def _signaux(equipe: ProviderTeam) -> dict[str, tuple]:
    """Faits comparables. Un signal absent n'entre pas — il ne vaut pas « égal »."""
    pays = _plat(equipe.country)
    signaux: dict[str, tuple] = {}
    if pays and equipe.code:
        signaux["code"] = (pays, equipe.code.upper())
    if pays and equipe.founded:
        signaux["founded"] = (pays, int(equipe.founded))
    if pays and equipe.venue:
        signaux["venue"] = (pays, _plat(equipe.venue))
    if pays and nom_canonique(equipe.name):
        signaux["nom"] = (pays, nom_canonique(equipe.name))
    return signaux


def resoudre(gauche: list[ProviderTeam], droite: list[ProviderTeam]) -> list[Resolution]:
    """Rapproche deux référentiels de clubs. Une entrée par club de `gauche`."""
    index: dict[tuple[str, tuple], list[ProviderTeam]] = defaultdict(list)
    for equipe in droite:
        for nom_signal, valeur in _signaux(equipe).items():
            index[(nom_signal, valeur)].append(equipe)

    # Combien de clubs de `gauche` réclament chaque club de `droite` ? Une
    # correspondance 1:n n'est pas une correspondance, quel que soit le sens.
    reclamations: dict[str, int] = defaultdict(int)
    provisoires: dict[str, tuple[ProviderTeam, tuple[str, ...]]] = {}

    for equipe in gauche:
        accords: dict[str, list[str]] = defaultdict(list)
        for nom_signal, valeur in _signaux(equipe).items():
            for candidat in index.get((nom_signal, valeur), ()):
                accords[candidat.provider_id].append(nom_signal)
        retenus = {pid: sigs for pid, sigs in accords.items() if len(sigs) >= SIGNAUX_MIN}
        if len(retenus) == 1:
            pid, sigs = next(iter(retenus.items()))
            cible = next(d for d in droite if d.provider_id == pid)
            provisoires[equipe.provider_id] = (cible, tuple(sorted(sigs)))
            reclamations[pid] += 1

    resolutions: list[Resolution] = []
    for equipe in gauche:
        accords: dict[str, list[str]] = defaultdict(list)
        for nom_signal, valeur in _signaux(equipe).items():
            for candidat in index.get((nom_signal, valeur), ()):
                accords[candidat.provider_id].append(nom_signal)
        retenus = {pid: sigs for pid, sigs in accords.items() if len(sigs) >= SIGNAUX_MIN}

        if len(retenus) > 1:
            resolutions.append(Resolution(
                ResolutionStatus.AMBIGUOUS, equipe, candidates=tuple(sorted(retenus)),
                detail=f"{len(retenus)} candidats à ≥{SIGNAUX_MIN} signaux concordants"))
            continue
        if not retenus:
            faibles = sorted(accords, key=lambda p: -len(accords[p]))[:3]
            resolutions.append(Resolution(
                ResolutionStatus.UNRESOLVED, equipe, candidates=tuple(faibles),
                detail=(f"aucun candidat à {SIGNAUX_MIN} signaux "
                        f"(meilleur : {len(accords[faibles[0]]) if faibles else 0})")))
            continue

        cible, sigs = provisoires[equipe.provider_id]
        if reclamations[cible.provider_id] > 1:
            # Plusieurs clubs de gauche visent la même cible : aucun n'est prouvé.
            resolutions.append(Resolution(
                ResolutionStatus.AMBIGUOUS, equipe, candidates=(cible.provider_id,),
                detail=f"{reclamations[cible.provider_id]} clubs revendiquent "
                       f"{cible.provider}:{cible.provider_id}"))
            continue
        resolutions.append(Resolution(ResolutionStatus.VERIFIED, equipe, cible, sigs))
    return resolutions


def construire_registre(resolutions, canonical_de) -> ClubIdentityRegistry:
    """Registre d'alias à partir des seules résolutions VERIFIED.

    `canonical_de(team)` rend l'identité canonique d'un club. Les deux alias
    pointent vers la MÊME, sans quoi le club aurait deux identités — exactement
    la dette qu'on répare.
    """
    registre = ClubIdentityRegistry()
    for r in resolutions:
        if r.status is not ResolutionStatus.VERIFIED or r.right is None:
            continue
        canonique = canonical_de(r.left)
        registre.declare(canonique, r.left)
        registre.declare(canonique, r.right)
    return registre


def resume(resolutions) -> dict:
    compte = defaultdict(int)
    for r in resolutions:
        compte[r.status.value] += 1
    return {"total": len(resolutions), **{s.value: compte[s.value] for s in ResolutionStatus}}
