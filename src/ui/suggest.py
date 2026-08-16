"""Suggestion de saisie : la suite probable de la ligne, en gris, jamais imposée.

Tab l'accepte, toute autre frappe l'ignore. Le risque n'est pas d'en manquer une
mais d'en montrer trop : une suggestion permanente devient un bruit qu'on cesse
de lire. Ce module cherche donc d'abord les raisons de se taire — préfixe trop
court, gain dérisoire, contexte du menu de complétion, curseur hors de la fin.

Le classement combine fréquence et récence : une formulation employée souvent
l'emporte sur une frappe unique, mais s'efface passé quelques dizaines de tours.
"""

from __future__ import annotations

from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion

from .completer import completion_context

# En deçà, presque tout l'historique correspond.
_PREFIXE_MIN = 3

# Ce que la suggestion doit AJOUTER pour valoir un affichage.
_GAIN_MIN = 3

# Lignes récentes examinées : borne le coût par frappe.
_FENETRE = 1000

# Poids d'un emploi par tour d'ancienneté — demi-vie ≈ 34 tours.
_DECAY = 0.98


def scores(lignes: list[str]) -> dict[str, float]:
    """Poids de chaque ligne distincte : ses emplois, amortis par l'ancienneté.

    `lignes` est ordonnée du plus ancien au plus récent, comme l'historique de
    prompt_toolkit.
    """
    recentes = lignes[-_FENETRE:]
    total = len(recentes)
    poids: dict[str, float] = {}
    for position, ligne in enumerate(recentes):
        anciennete = total - 1 - position
        poids[ligne] = poids.get(ligne, 0.0) + _DECAY ** anciennete
    return poids


def meilleure_suite(texte: str, lignes: list[str]) -> str | None:
    """La fin de ligne à proposer pour ce début de texte, ou `None` pour se taire.

    Fonction pure : c'est elle qui porte toute la décision, et elle se teste sans
    terminal.
    """
    if len(texte) < _PREFIXE_MIN or "\n" in texte:
        return None
    if completion_context(texte):
        return None

    debut = texte.lower()
    poids = scores(lignes)
    candidates = [
        ligne for ligne in poids
        if len(ligne) - len(texte) >= _GAIN_MIN and ligne.lower().startswith(debut)
    ]
    if not candidates:
        return None

    # À poids égal, la plus courte : c'est la moins engageante des deux.
    retenue = max(candidates, key=lambda ligne: (poids[ligne], -len(ligne)))
    return retenue[len(texte):]


class HistorySuggest(AutoSuggest):
    """Adaptateur prompt_toolkit — il ne décide rien, il branche `meilleure_suite`.

    Appelé à chaque frappe : l'index de poids est reconstruit tant que
    l'historique change, ce qui reste de l'ordre de la milliseconde sur la
    fenêtre bornée ci-dessus.
    """

    def get_suggestion(self, buffer, document) -> Suggestion | None:
        if not document.is_cursor_at_the_end:
            return None
        try:
            lignes = buffer.history.get_strings()
        except Exception:      # noqa: BLE001 — une suggestion ne casse jamais la saisie
            return None
        suite = meilleure_suite(document.text, lignes)
        return None if suite is None else Suggestion(suite)
