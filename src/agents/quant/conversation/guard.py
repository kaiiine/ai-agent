"""Garde de provenance — programmatique, jamais un prompt (§4, §5, §17, §18).

Un prompt demande. Il ne prouve rien, et il ne tient pas quand le modèle a
suffisamment de contexte pour « combler le trou ». Le garde, lui, lit le texte
final produit et le confronte à ce que la chaîne structurée a réellement fait
pendant le tour courant.

Trois interdictions, dans l'ordre où elles se déclenchent :

1. **Affirmation sans preuve.** Une cote, une mise, une EV positive, un « le
   moteur a retourné BET » : sans `BettingResponseEvidence` du tour courant, la
   réponse est remplacée. Le modèle n'est pas discuté, il est court-circuité.
2. **Actionnable sans verdict actionnable.** Une preuve existe mais l'issue n'est
   pas `RECOMMENDED` : aucune mise, aucune procédure de placement. `ABSTAIN`,
   `REVIEW_CANDIDATES`, `NO_OPPORTUNITY` sont terminaux (§6).
3. **Langage trompeur.** « sûr », « garanti », « sans risque » : aucun de ces
   mots ne peut décrire un pari, y compris avec un verdict valide.

Le remplacement conserve ce qui est vrai — l'échec et sa raison — et supprime ce
qui ne l'est pas. Il ne s'excuse pas et n'invente pas de repli.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .evidence import ACTIONABLE_OUTCOMES, BettingResponseEvidence

# ── Signaux ───────────────────────────────────────────────────────────────────
#: Affirmation qu'un outil a tourné ou qu'une donnée vient d'une source.
_PROVENANCE = re.compile(
    r"(?i)("
    r"le moteur (a |m'a )?(retourn|renvoy|indiqu|donn|calcul)"
    r"|(ev_analyze|parlay_analyze|probability_compute|betting_recommend|axon recommend)"
    r"\s*(a|m'a|renvoie|retourne|indique)"
    r"|(?:j'ai|je viens de)\s+(?:re[- ]?)?(?:scann|analys|interrog|récupér|recuper|extrait)"
    r"|(?:re[- ]?scan|rescan)(?:né|ne)?\b"
    r"|(?:cotes?|données|donnees)\s+(?:winamax|extraites?|récupérées?|recuperees?)"
    r"|(?:d'après|selon)\s+(?:le|les)\s+(?:moteur|modèle|modele|cotes)"
    r")")

#: Une cote concrète : « cote 1.55 », « @2,45 », « à 1.90 ». La forme « à 1.90 »
#: est incluse parce que c'est ainsi qu'on parle — « le favori à 1.40 » est une
#: cote, même sans le mot.
_COTE = re.compile(
    r"(?i)(?:\bcote\w*\s*(?:de\s*)?|@\s*|\bodds?\s*|\bà\s+)(\d+[.,]\d{1,3})\b")

#: Une instruction de placement ou de mise chiffrée.
_MISE = re.compile(
    r"(?i)("
    r"\bmise[rz]?\b[^.\n]{0,40}?\d+(?:[.,]\d+)?\s*(?:€|eur)"
    r"|\d+(?:[.,]\d+)?\s*(?:€|eur)[^.\n]{0,25}?\b(?:sur|mise|pari)"
    r"|\bplace[rz]?\b[^.\n]{0,30}?\b(?:pari|mise|ticket)"
    r"|\bouvre[rz]?\s+winamax\b|\bsélectionne[rz]?\s+ce\s+match\b"
    r"|\bmise[rz]?\s+(?:tout|toute\s+la\s+bankroll|l'?intégralité)"
    r")")

#: Une affirmation d'espérance favorable.
_EV_POSITIVE = re.compile(
    r"(?i)(ev\s*(?:est\s*)?(?:positive|>\s*0|de\s*\+)"
    r"|espérance\s+(?:positive|favorable)|esperance\s+positive"
    r"|\bvalue\s*bet\b|\bpari\s+de\s+valeur\b|edge\s+(?:positif|favorable))")

#: Pricing de combiné : une cote totale ou une probabilité jointe est un CALCUL,
#: jamais une donnée observée. Hors Combo Builder, elle suppose une indépendance
#: que rien n'a vérifiée (§14).
_COMBO_PRICING = re.compile(
    r"(?i)(cote\s+(?:totale|combin[ée]e?|du\s+combin[ée])"
    r"|probabilit[ée]\s+(?:combin[ée]e?|jointe)"
    r"|\d+[.,]\d+\s*[x×*]\s*\d+[.,]\d+)")

#: Recommandation explicite d'une sélection.
_RECOMMANDE = re.compile(
    r"(?i)(je\s+(?:te\s+|vous\s+)?(?:recommande|conseille|propose)\s+(?:de\s+)?"
    r"(?:parier|miser|jouer|prendre)"
    r"|\b(?:meilleur|meilleure)s?\s+(?:pari|paris|option|options|sélection|selection|"
    r"sélections|selections|value\s*bets?)\b"
    # « à jouer » seul attraperait « il reste deux matchs à jouer » : on exige que
    # ce soit un PARI qu'on désigne, pas une rencontre au calendrier.
    r"|\b(?:pari|ticket|combin[ée]|s[ée]lection)\s+à\s+jouer\b"
    r"|\bticket\s+(?:conseillé|recommandé)\b)")

#: §17 — vocabulaire qui ne peut décrire aucun pari.
_TROMPEUR = re.compile(
    r"(?i)\b("
    r"pari\s+s[ûu]r|s[ûu]r\s+(?:de\s+)?(?:passer|gagner)|quasi[- ]?certain"
    r"|garanti[es]?|sans\s+risque|sans\s+aucun\s+risque|z[ée]ro\s+risque"
    r"|s[ée]curis[ée]|va\s+passer|ne\s+peut\s+pas\s+perdre|banco"
    r"|argent\s+facile|rendement\s+garanti"
    r")\b")


@dataclass(frozen=True)
class GuardVerdict:
    allowed: bool
    replacement: str | None
    reason: str | None

    @property
    def blocked(self) -> bool:
        return not self.allowed


_OK = GuardVerdict(True, None, None)


def _claims(text: str) -> dict[str, bool]:
    return {
        "provenance": bool(_PROVENANCE.search(text)),
        "cote": bool(_COTE.search(text)),
        "mise": bool(_MISE.search(text)),
        "ev_positive": bool(_EV_POSITIVE.search(text)),
        "combo_pricing": bool(_COMBO_PRICING.search(text)),
        "recommande": bool(_RECOMMANDE.search(text)),
        "trompeur": bool(_TROMPEUR.search(text)),
    }


def _asserts_opportunity(signaux: dict[str, bool]) -> bool:
    """Distingue une AFFIRMATION d'opportunité d'une explication générale.

    « une cote de 1.50 correspond à 66 % » est de la pédagogie et ne doit rien
    déclencher. « cote 1.50, je te conseille de miser 10 € » est une
    recommandation, et exige une preuve. Le seuil est donc la conjonction, pas la
    présence d'un chiffre.
    """
    return (
        signaux["mise"]
        or signaux["ev_positive"]
        or signaux["combo_pricing"]
        # Désigner « le meilleur pari du soir » EST une recommandation, avec ou
        # sans cote à côté. C'est la phrase même que §6 interdit : « le moteur
        # abstient, mais la cote indique quand même un bon favori ».
        or signaux["recommande"]
    )


def enforce(
    text: str,
    evidence: BettingResponseEvidence | None,
    *,
    has_structured_output: bool = False,
) -> GuardVerdict:
    """Confronte le texte final à la preuve du tour courant.

    `has_structured_output` distingue deux absences de preuve. Un tour où
    `ev_analyze` a répondu ABSTAIN n'a produit aucune recommandation, mais il a
    bien fait tourner le moteur : « le moteur a retourné ABSTAIN » y est vrai, et
    le bloquer punirait la seule réponse honnête. Un tour sans aucun appel
    structuré, lui, ne peut rien affirmer du tout.
    """
    if not text or not text.strip():
        return _OK

    signaux = _claims(text)
    prouve = evidence is not None or has_structured_output

    if evidence is None:
        if signaux["trompeur"]:
            return GuardVerdict(False, _sans_preuve(signaux), "MISLEADING_LANGUAGE")
        if _asserts_opportunity(signaux):
            return GuardVerdict(False, _sans_preuve(signaux), "NO_STRUCTURED_EVIDENCE")
        if signaux["provenance"] and not prouve:
            return GuardVerdict(False, _sans_preuve(signaux), "FABRICATED_TOOL_CLAIM")
        return _OK

    if signaux["trompeur"]:
        return GuardVerdict(False, _langage_interdit(evidence), "MISLEADING_LANGUAGE")

    actionnable = evidence.recommendation_outcome in ACTIONABLE_OUTCOMES
    if not actionnable and (signaux["mise"] or signaux["recommande"] or signaux["ev_positive"]):
        return GuardVerdict(False, _non_actionnable(evidence), "NON_ACTIONABLE_OUTCOME")

    return _OK


# ── Remplacements déterministes ───────────────────────────────────────────────
def _sans_preuve(signaux: dict[str, bool]) -> str:
    faits = [nom for nom in ("provenance", "cote", "mise", "ev_positive", "recommande")
             if signaux[nom]]
    return (
        "**DATA_UNAVAILABLE** — réponse bloquée : aucune sortie structurée n'a été "
        "produite pendant ce tour.\n\n"
        "La réponse rédigée contenait des éléments de pari "
        f"({', '.join(faits) or 'affirmations non sourcées'}) sans qu'aucun appel à "
        "`betting_recommend` n'ait abouti. Ces éléments ne provenaient donc d'aucun "
        "scan, d'aucun modèle et d'aucune cote réelle.\n\n"
        "Aucune sélection, aucune cote, aucun horaire et aucune mise ne peuvent être "
        "affichés dans cet état. Relance la demande pour déclencher un scan réel."
    )


def _non_actionnable(evidence: BettingResponseEvidence) -> str:
    return (
        f"**{evidence.recommendation_outcome}** — aucune recommandation actionnable.\n\n"
        f"Le pipeline structuré a tourné (audit `{evidence.audit_id}`, "
        f"{evidence.events_scanned} événements scannés, "
        f"{evidence.events_evaluated} sélections évaluées) et n'a produit "
        "aucun portefeuille misable.\n\n"
        "Aucune mise, aucun montant et aucune procédure de placement ne peuvent "
        "accompagner ce verdict. Une cote basse, un favori ou une probabilité "
        "implicite élevée n'en font pas une opportunité : sans probabilité de "
        "modèle validée, il n'y a pas d'espérance à comparer."
    )


def _langage_interdit(evidence: BettingResponseEvidence) -> str:
    return (
        f"**{evidence.recommendation_outcome}** — réponse reformulée (audit "
        f"`{evidence.audit_id}`).\n\n"
        "La rédaction employait un vocabulaire de certitude (« sûr », « garanti », "
        "« sans risque »…). Aucun pari ne l'est : le modèle produit une probabilité "
        "et une espérance de long terme, jamais une prévision de ce match.\n\n"
        "Reprends le détail chiffré dans la sortie structurée du tour — il est exact, "
        "et il porte son incertitude."
    )
