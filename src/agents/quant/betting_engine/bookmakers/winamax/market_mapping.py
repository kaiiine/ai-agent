"""Libellés/types de marché Winamax bruts -> vocabulaire canonique `MarketType`.

On ne canonise que ce qui est explicitement observé dans le snapshot réel
(règle sûre carto #3, cf. §6 « Combinaisons de types de marchés observées ») ;
tout le reste est `UNMAPPED` (règle sûre #5), jamais deviné.
"""

from __future__ import annotations

from ..protocol import MarketType

# Marchés « qui gagne le match » observés (betTypeName, template) :
#   ("Résultat", "3way")  -> foot / rugby XIII : 1 / x / 2
#   ("Résultat", "2way")  -> baseball (marketId 251)
#   ("Vainqueur", "2way") -> tennis, tennis de table, baseball : 1 / 2
_MATCH_WINNER = frozenset({
    ("Résultat", "3way"),
    ("Résultat", "2way"),
    ("Vainqueur", "2way"),
})

# Vainqueur d'une épreuve listée (F1, cyclisme, golf) : liste de compétiteurs SUR
# UN ÉVÉNEMENT QUE LA SOURCE DÉCLARE OUTRIGHT. Les trois conditions comptent.
_OUTRIGHT = frozenset({
    ("Vainqueur", "ListOdd"),
})


def map_market(bet_type_name: str, template: str, *, is_outright: bool = False) -> MarketType:
    """(betTypeName, template) bruts -> `MarketType`. `UNMAPPED` si indémontrable.

    LE TEMPLATE SEUL NE PROUVE RIEN, et la capture réelle l'a établi. La règle
    précédente renvoyait `OUTRIGHT_WINNER` pour TOUT `ListOdd` : sur 1 263
    marchés `ListOdd` observés (29 sports, 98 événements), **33** sont des
    vainqueurs d'épreuve. Les 1 230 autres sont des marqueurs, des « Résultat et
    nombre de buts », des « Mi-temps/Fin de match », des listes de props joueurs —
    97,4 % de classifications fausses.

    Ce qui se démontre : les 33 vainqueurs d'épreuve sont TOUS portés par un
    événement que la source elle-même marque `isOutright`, et le marché s'appelle
    « Vainqueur ». Le drapeau vient du bookmaker, ce n'est pas une déduction de
    notre part ; c'est ce qui autorise à nommer la famille.

    `is_outright` vaut `False` par défaut, et ce défaut est sûr : un appelant qui
    ne connaît pas le drapeau obtient `UNMAPPED`, jamais un outright supposé. Une
    classification inconnue est préférable à une classification fausse.

    Le chemin `MATCH_WINNER` est inchangé : mêmes trois couples, même priorité.
    """
    key = (bet_type_name, template)
    if key in _MATCH_WINNER:
        return MarketType.MATCH_WINNER
    if is_outright and key in _OUTRIGHT:
        return MarketType.OUTRIGHT_WINNER
    return MarketType.UNMAPPED


def map_selection_code(code: str) -> str:
    """Code de sélection Winamax -> **slot** canonique (pas un rôle).

    "1"/"2" = premier/second compétiteur dans l'ordre d'affichage brut ; "x" =
    match nul. La traduction slot -> rôle (home/away...) est faite ailleurs par
    le `ParticipantRoleResolver` — ici on ne suppose aucune sémantique domicile.
    """
    normalized = (code or "").strip().lower()
    if normalized == "1":
        return "slot_1"
    if normalized == "2":
        return "slot_2"
    if normalized == "x":
        return "draw"
    return "UNMAPPED"


# ---------------------------------------------------------------------------
# Cotes boostées — DIFFÉRÉ en Vague 2 (PRD §11 + §4.4 + ADR-017). Rien ici n'est
# actif tant que la Vague 2 n'est pas ouverte ; notes de conception à honorer :
#
# Détection : événement sous `sportId 100000` (catégorie « Cotes boostées »),
#   relié au vrai sport via `categories[categoryId].boostedOddSportId`.
#
# max_stake : ce N'EST PAS une clé JSON structurée. C'est du PARSING de texte
#   libre du champ `tournaments[tournamentId].warning` (confirmé présent dans le
#   snapshot réel, carto §13 : 7 occurrences) — ex. « Paris non combinables.
#   \nMise maximale de 20 € pour les Cotes Boostées et 10 € pour les Grosses
#   Cotes Boostées » (foot ; 50 € baseball). Un même warning mêle plusieurs
#   plafonds par catégorie de boost : vrai travail de parsing à écrire quand la
#   Vague 2 s'ouvre — pas une simple lecture de clé.
#
# max_payout : champ PRÉVU par le PRD (§5.3) mais JAMAIS peuplé à ce jour —
#   aucune preuve de source dans le snapshot réel. (Les valeurs 100000/1000000
#   vues ailleurs relèvent d'une autre feature, pas d'un plafond d'offre.) Il
#   reste `Optional`/`None` par défaut sur `RawSelection` : AUCUNE extraction.
#
# Contrainte associée : les cotes boostées sont « Paris non combinables » — à
# intégrer côté `portfolio/` (Vague 2), pas ici.
# ---------------------------------------------------------------------------
