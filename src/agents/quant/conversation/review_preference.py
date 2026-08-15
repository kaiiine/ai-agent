"""La préférence de probabilité de l'utilisateur — appliquée à l'AFFICHAGE seul.

« Je veux environ 90 % de chances » est une demande légitime, et le produit y
répondait en ne montrant rien : le classement de revue ordonne par borne basse
d'edge, si bien que les candidats les plus probables restaient invisibles derrière
des cotes longues à forte espérance. L'utilisateur devait alors reformuler sa
demande à la baisse pour obtenir le droit de voir quoi que ce soit.

Trois règles portent tout ce module, et chacune est refusable si on la tait :

1. LA COMPARAISON SE FAIT SUR `probability_low`, JAMAIS SUR `fair_probability`.
   Qui dit « 90 % » demande une garantie. `fair_probability` est une estimation
   ponctuelle : la substituer reviendrait à répondre « oui » à une question de
   prudence avec un chiffre qui n'en porte aucune. Un candidat dont la borne
   basse n'est pas mesurée n'atteint donc AUCUN seuil — il n'échoue pas, il n'est
   pas comparable, et c'est dit comme tel.

2. LA PRÉFÉRENCE NE FILTRE RIEN. Elle partitionne et ordonne. Un candidat sous le
   seuil reste montré, dans sa propre section : « aucun candidat n'atteint 90 % »
   suivi du silence serait la même impasse qu'avant.

3. AUCUN SEUIL DU MOTEUR N'EST TOUCHÉ. Atteindre la préférence ne rend rien
   misable, et ne la pas atteindre ne rend rien plus interdit. La maturité, la
   qualité de données, l'EV et la politique d'éligibilité décident seules — ce
   module n'a aucun droit sur elles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

#: « environ 90 % de chances », « 90% de probabilité », « au moins 85 % ».
_POURCENTAGE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_MOTS_PROBABILITE = ("chance", "probabilit", "sûr", "sur de", "certitude", "fiab")


def cible_depuis_texte(texte: str | None) -> Decimal | None:
    """La probabilité demandée, si l'utilisateur en a exprimé une.

    Un pourcentage seul ne suffit pas : « mise 10 % de ma bankroll » en contient
    un et ne demande aucune probabilité. Il faut que la phrase parle de chances,
    de probabilité ou de fiabilité.
    """
    if not texte:
        return None
    minuscules = texte.lower()
    if not any(mot in minuscules for mot in _MOTS_PROBABILITE):
        return None
    trouve = _POURCENTAGE.search(minuscules)
    if not trouve:
        return None
    try:
        valeur = Decimal(trouve.group(1).replace(",", ".")) / Decimal(100)
    except (InvalidOperation, ValueError):
        return None
    return valeur if Decimal(0) < valeur <= Decimal(1) else None


# ══ Objectif de cote / multiplicateur ═══════════════════════════════════════
#: Tolérance appliquée quand l'utilisateur vise une cote sans borner lui-même.
#: ±15 % relatif : « x2 » retient 1,70 à 2,30. Une tolérance nulle ne retiendrait
#: presque rien — les cotes réelles tombent rarement sur un rond — et une
#: tolérance large ferait passer x1,5 pour un x2. La valeur est NOMMÉE et
#: affichée : une préférence silencieuse serait indistinguable d'un filtre caché.
TOLERANCE_PAR_DEFAUT = Decimal("0.15")

#: « x2 », « X 2,5 », « fois 3 ».
_MULTIPLICATEUR = re.compile(r"(?:\bx\s*|\bfois\s+)(\d+(?:[.,]\d+)?)\b")
#: « entre 1.8 et 2.2 ».
_INTERVALLE = re.compile(r"entre\s+(\d+(?:[.,]\d+)?)\s+(?:et|à)\s+(\d+(?:[.,]\d+)?)")
#: « autour de 2 de cote », « cote de 2,10 », « une cote proche de 3 ».
_COTE_NOMMEE = re.compile(
    r"(?:cote[s]?\s+(?:de\s+|à\s+|vers\s+|autour\s+de\s+|proche\s+de\s+|environ\s+)?"
    r"(\d+(?:[.,]\d+)?)"
    r"|(?:autour\s+de|environ|vers|proche\s+de|viser)\s+(\d+(?:[.,]\d+)?)\s*(?:de\s+)?cote)")
#: « doubler », « tripler », « quadrupler » — un multiplicateur dit en toutes lettres.
_VERBES_MULTIPLICATEURS = {"doubl": Decimal(2), "tripl": Decimal(3),
                           "quadrupl": Decimal(4)}
#: Marque l'imprécision assumée. Sans elle la cible reste une cible, avec la même
#: tolérance : ce mot ne change pas le calcul, il dit que l'utilisateur le savait.
_APPROXIMATIF = ("environ", "autour", "à peu près", "approximativement", "~", "≈")


@dataclass(frozen=True)
class TargetOddsPreference:
    """L'objectif de cote demandé, sous forme structurée.

    Existe pour que « je veux faire x2 » cesse d'être interprété librement par la
    couche de langage. Un multiplicateur est une contrainte de PRIX, pas de
    probabilité : les deux se contredisent souvent, et c'est précisément pour
    pouvoir le DIRE qu'il faut les porter séparément.

    `target_odds` sert au classement par proximité ; `min_odds`/`max_odds`
    décident de l'appartenance. Un intervalle explicite (« entre 1,8 et 2,2 »)
    renseigne les trois : la cible devient le milieu, uniquement pour ordonner.
    """

    target_odds: Decimal | None = None
    tolerance: Decimal | None = None          # relative : 0.15 = ±15 %
    min_odds: Decimal | None = None
    max_odds: Decimal | None = None
    source_text: str = ""
    #: Vrai quand l'utilisateur a lui-même énoncé les bornes.
    bornes_explicites: bool = False

    @property
    def borne_basse(self) -> Decimal | None:
        if self.min_odds is not None:
            return self.min_odds
        if self.target_odds is None or self.tolerance is None:
            return None
        return self.target_odds * (Decimal(1) - self.tolerance)

    @property
    def borne_haute(self) -> Decimal | None:
        if self.max_odds is not None:
            return self.max_odds
        if self.target_odds is None or self.tolerance is None:
            return None
        return self.target_odds * (Decimal(1) + self.tolerance)

    def contient(self, odds: Any) -> bool:
        """La cote tombe-t-elle dans la fourchette ? Une cote absente n'y est
        jamais : on ne suppose pas qu'un prix inconnu convient."""
        valeur = _en_decimal(odds)
        basse, haute = self.borne_basse, self.borne_haute
        if valeur is None or basse is None or haute is None:
            return False
        return basse <= valeur <= haute

    def ecart(self, odds: Any) -> Decimal | None:
        """|cote − cible|, pour ordonner par proximité. `None` si non mesurable."""
        valeur = _en_decimal(odds)
        if valeur is None or self.target_odds is None:
            return None
        return abs(valeur - self.target_odds)

    def describe(self) -> str:
        if self.target_odds is None:
            return "aucun objectif de cote"
        basse, haute = self.borne_basse, self.borne_haute
        fourchette = (f" (fourchette retenue {basse:.2f} – {haute:.2f}"
                      f"{', bornes données' if self.bornes_explicites else ''})"
                      if basse is not None and haute is not None else "")
        return f"cote visée {self.target_odds:.2f}{fourchette}"


def _en_decimal(valeur: Any) -> Decimal | None:
    if valeur is None:
        return None
    try:
        return Decimal(str(valeur))
    except (InvalidOperation, ValueError):
        return None


def objectif_de_cote(texte: str | None) -> TargetOddsPreference | None:
    """L'objectif de cote, si l'utilisateur en a exprimé un.

    NE CONFOND JAMAIS UN MONTANT AVEC UNE COTE. « doubler 10 € » vise x2, pas
    x10 : le montant est reconnu et écarté, et un nombre suivi d'un symbole
    monétaire ne peut jamais devenir une cible. Sans cette règle, une bankroll
    de 10 € produisait un objectif de cote 10.
    """
    if not texte:
        return None
    brut = texte.strip()
    minuscules = brut.lower()

    # Les montants sont neutralisés AVANT toute recherche de nombre.
    sans_montants = re.sub(r"\d+(?:[.,]\d+)?\s*(?:€|eur\b|euros?\b)", " ", minuscules)

    # 1. Intervalle explicite — la forme la plus précise l'emporte.
    intervalle = _INTERVALLE.search(sans_montants)
    if intervalle:
        basse = _en_decimal(intervalle.group(1).replace(",", "."))
        haute = _en_decimal(intervalle.group(2).replace(",", "."))
        if basse and haute and Decimal(1) < basse <= haute:
            return TargetOddsPreference(
                target_odds=(basse + haute) / Decimal(2),
                min_odds=basse, max_odds=haute, source_text=brut,
                bornes_explicites=True)

    # 2. Multiplicateur : « x2 », « fois 3 ».
    cible = None
    multiplicateur = _MULTIPLICATEUR.search(sans_montants)
    if multiplicateur:
        cible = _en_decimal(multiplicateur.group(1).replace(",", "."))

    # 3. Cote nommée : « autour de 2 de cote », « cote de 2,10 ».
    if cible is None:
        nommee = _COTE_NOMMEE.search(sans_montants)
        if nommee:
            cible = _en_decimal((nommee.group(1) or nommee.group(2)).replace(",", "."))

    # 4. Verbe multiplicateur : « doubler », « tripler ».
    if cible is None:
        for racine, valeur in _VERBES_MULTIPLICATEURS.items():
            if racine in sans_montants:
                cible = valeur
                break

    if cible is None or cible <= Decimal(1):
        return None                     # une cote <= 1 ne paie rien
    return TargetOddsPreference(target_odds=cible, tolerance=TOLERANCE_PAR_DEFAUT,
                                source_text=brut)


@dataclass(frozen=True)
class RevueParPreference:
    """La revue partitionnée par la préférence. Aucun candidat n'est perdu."""

    #: Seuil demandé, ou None si l'utilisateur n'a rien exprimé.
    cible: Decimal | None
    #: `probability_low` mesurée ET >= cible. Classés par borne basse décroissante.
    au_seuil: tuple[Any, ...] = ()
    #: `probability_low` mesurée ET < cible. Ordre du moteur de classement.
    sous_seuil: tuple[Any, ...] = ()
    #: `probability_low` absente : ni au-dessus, ni en dessous — non comparable au
    #: seuil. Les compter évite de les faire passer pour des échecs.
    sans_borne_basse: tuple[Any, ...] = ()

    @property
    def total(self) -> int:
        return len(self.au_seuil) + len(self.sous_seuil) + len(self.sans_borne_basse)

    @property
    def atteint(self) -> bool:
        return bool(self.au_seuil)


def _borne_basse(rang: Any) -> Decimal | None:
    """La borne basse du candidat, quelle que soit la forme du rang."""
    candidat = getattr(rang, "candidate", rang)
    valeur = getattr(candidat, "probability_low", None)
    if valeur is None:
        return None
    try:
        return Decimal(str(valeur))
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class RevueParObjectifs:
    """La revue vue par les DEUX préférences, sans jamais les fondre.

    L'ordre des contraintes est celui du produit, et il n'est pas négociable :
    la probabilité prudente d'abord, la cote ensuite. Fondre les deux en un
    score unique laisserait un prix élevé compenser une probabilité basse — soit
    exactement « fabriquer un x2 » en sacrifiant la prudence demandée.

    D'où trois groupes disjoints plutôt qu'un classement :

    - `A` respecte le seuil de probabilité ET tombe dans la fourchette de cote ;
    - `B` respecte le seuil de probabilité, hors fourchette ;
    - `C` ne respecte pas le seuil — ordonné par proximité à la cote, parce que
      c'est la seule chose qu'il reste à y lire, et jamais présenté comme une
      alternative équivalente.
    """

    seuil_probabilite: Decimal | None = None
    objectif_cote: TargetOddsPreference | None = None
    a_les_deux: tuple[Any, ...] = ()
    b_probabilite_seule: tuple[Any, ...] = ()
    c_sous_le_seuil: tuple[Any, ...] = ()
    sans_borne_basse: tuple[Any, ...] = ()

    @property
    def total(self) -> int:
        return (len(self.a_les_deux) + len(self.b_probabilite_seule)
                + len(self.c_sous_le_seuil) + len(self.sans_borne_basse))

    @property
    def c_proches_de_la_cote(self) -> tuple[Any, ...]:
        """Les candidats sous le seuil qui tombent dans la fourchette de cote."""
        if self.objectif_cote is None:
            return ()
        return tuple(r for r in self.c_sous_le_seuil
                     if self.objectif_cote.contient(
                         getattr(r, "candidate", r).bookmaker_odds))


def plus_proches_de_la_cote(classes: Sequence[Any],
                            objectif: TargetOddsPreference) -> tuple[Any, ...]:
    """Les candidats ordonnés par proximité à la cote visée.

    Vit ICI et non dans la couche de rendu : le résumé n'a pas le droit de
    classer des candidats. Une seconde logique de classement dans l'affichage
    finirait par diverger de celle qui décide, et c'est l'affichage qu'on croirait.
    """
    infini = Decimal("9" * 12)
    return tuple(sorted(
        classes,
        key=lambda r: (objectif.ecart(getattr(r, "candidate", r).bookmaker_odds)
                       if objectif.ecart(
                           getattr(r, "candidate", r).bookmaker_odds) is not None
                       else infini,
                       str(getattr(getattr(r, "candidate", r), "candidate_id", "")))))


def partitionner_par_objectifs(
    classes: Sequence[Any], seuil: Decimal | None,
    objectif: TargetOddsPreference | None,
) -> RevueParObjectifs:
    """Répartit un classement DÉJÀ produit selon les deux préférences.

    Ne re-classe rien et n'écarte rien : chaque candidat entré ressort dans
    exactement un groupe. Seul l'ordre INTERNE des groupes est ajusté, et selon
    la grandeur que le groupe met en avant — probabilité pour A et B, proximité
    à la cote pour C.
    """
    base = partitionner(classes, seuil)
    if objectif is None:
        return RevueParObjectifs(
            seuil_probabilite=seuil, objectif_cote=None,
            b_probabilite_seule=base.au_seuil, c_sous_le_seuil=base.sous_seuil,
            sans_borne_basse=base.sans_borne_basse)

    def _cote(rang: Any):
        return getattr(rang, "candidate", rang).bookmaker_odds

    a = tuple(r for r in base.au_seuil if objectif.contient(_cote(r)))
    b = tuple(r for r in base.au_seuil if not objectif.contient(_cote(r)))

    # C est ordonné par proximité à la cible : c'est ce que l'utilisateur y
    # cherchera. Un écart non mesurable part en fin de liste plutôt que de
    # prendre la place d'un écart mesuré.
    infini = Decimal("9" * 12)
    c = tuple(sorted(
        base.sous_seuil,
        key=lambda r: (objectif.ecart(_cote(r)) if objectif.ecart(_cote(r)) is not None
                       else infini,
                       str(getattr(getattr(r, "candidate", r), "candidate_id", "")))))

    return RevueParObjectifs(
        seuil_probabilite=seuil, objectif_cote=objectif,
        a_les_deux=a, b_probabilite_seule=b, c_sous_le_seuil=c,
        sans_borne_basse=base.sans_borne_basse)


def partitionner(classes: Sequence[Any], cible: Decimal | None) -> RevueParPreference:
    """Partitionne un classement DÉJÀ produit par le moteur structuré.

    L'ordre d'entrée est celui du classement existant (borne basse d'edge, EV,
    qualité, fraîcheur, meilleur marché par rencontre) : ce module ne re-classe
    pas, il regroupe. Seul le groupe `au_seuil` est réordonné, par borne basse
    décroissante — c'est la grandeur que l'utilisateur a nommée.
    """
    lignes = list(classes)
    if cible is None:
        return RevueParPreference(cible=None, sous_seuil=tuple(lignes))

    au_seuil, sous_seuil, sans_borne = [], [], []
    for rang in lignes:
        basse = _borne_basse(rang)
        if basse is None:
            sans_borne.append(rang)
        elif basse >= cible:
            au_seuil.append(rang)
        else:
            sous_seuil.append(rang)

    # Départage TOTAL : deux runs sur le même classement rendent le même ordre.
    au_seuil.sort(key=lambda r: (-(_borne_basse(r) or Decimal(0)),
                                 str(getattr(getattr(r, "candidate", r),
                                             "candidate_id", ""))))
    return RevueParPreference(cible=cible, au_seuil=tuple(au_seuil),
                              sous_seuil=tuple(sous_seuil),
                              sans_borne_basse=tuple(sans_borne))
