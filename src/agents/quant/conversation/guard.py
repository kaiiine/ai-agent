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

# ── Faits sur le monde, hors argent ───────────────────────────────────────────
# Les règles ci-dessus protègent la DÉCISION : mise, EV, combiné, recommandation.
# Elles laissaient passer les faits qui la précèdent — un match, une cote, une
# blessure, la météo, un classement, un provider consulté. Or c'est sur eux que
# se construit la confiance : « Rybakina est blessée » lu dans une réponse d'AXON
# se lit comme une donnée du produit, alors que rien ne l'a vérifié.
#
# Chaque motif exige une assertion CONCRÈTE — un sujet nommé, une heure, un
# nombre. Une phrase d'explication générale n'en contient aucun et passe.

#: « X est blessé », « forfait de Y ». Le participe seul ne suffit pas : il faut
#: un verbe d'état ou une tournure qui ATTRIBUE l'indisponibilité.
_BLESSURE = re.compile(
    r"(?i)("
    r"\b(?:est|sont|serait|seraient|reste|restent)\s+(?:blessée?s?|forfaits?|"
    r"indisponibles?|absente?s?|suspendue?s?|incertaine?s?)\b"
    r"|\bs'est\s+blessée?\b"
    r"|\b(?:blessure|forfait|indisponibilité)\s+(?:de|d'|du|de\s+la)\s*[A-ZÉÈÀ]"
    r"|\bdéclare[rz]?\s+forfait\b"
    r")")

#: Météo annoncée pour une rencontre.
_METEO = re.compile(
    r"(?i)("
    r"\bil\s+(?:va\s+)?(?:pleut|pleuvra|pleuvoir|neige|neigera)\b"
    r"|\b(?:pluie|averses?|vent|chaleur)\s+(?:est|sont)?\s*(?:annoncée?s?|prévue?s?|attendue?s?)"
    r"|\bmétéo\s+(?:annonce|prévoit|indique)"
    r"|\b(?:température|vent)\s+(?:de|à)\s*\d+"
    r")")

#: Classement mondial ou position au tableau.
_CLASSEMENT = re.compile(
    r"(?i)("
    r"\bnum[ée]ro\s+\d+\s+(?:mondial|atp|wta|fifa)"
    r"|\b\d+(?:er|re|e|ème|eme)\s+(?:mondial|au\s+classement)"
    r"|\bclassée?\s+\d+(?:er|re|e|ème|eme)?\b"
    r"|\b(?:atp|wta|fifa)\s*(?:n[°o]|#)\s*\d+"
    r"|\bt[êe]te\s+de\s+s[ée]rie\s+n?[°o]?\s*\d+"
    r")")

#: Consultation d'une source externe nommée. Le produit n'interroge que Winamax
#: et, en informatif seul, la couche d'enrichissement — jamais ces flux-là.
_SOURCE_EXTERNE = re.compile(
    r"(?i)("
    r"\b(?:j'ai|je\s+viens\s+de)\s+(?:vérifié?|consulté?|regardé?|trouvé?|lu)\b"
    r"[^.\n]{0,30}?\b(?:sportradar|opta|flashscore|sofascore|tennis[\s-]*abstract|"
    r"api[\s-]*tennis|goalserve|enetpulse|utr|espn|l'?[ée]quipe|bet365|oddsportal)\b"
    r"|\b(?:d'après|selon)\s+(?:sportradar|opta|flashscore|sofascore|espn|bet365)\b"
    r")")

#: Une rencontre annoncée AVEC son horaire : c'est la forme d'un match inventé.
#: « Nadal a souvent affronté Federer » n'a pas d'horaire et passe.
_FIXTURE = re.compile(
    r"(?i)(?=[^.\n]*\b(?:affronte(?:ra)?|joue\s+contre|rencontre|reçoit|"
    r"se\s+déplace\s+(?:à|chez)|opposée?\s+à|face\s+à|contre)\b)"
    r"[^.\n]*\b(?:\d{1,2}\s*h(?:\d{2})?\b|à\s+\d{1,2}[:h]\d{2}|ce\s+soir|"
    r"cet\s+après[- ]midi|demain|aujourd'hui|ce\s+matin)\b")

#: Une probabilité ATTRIBUÉE à un compétiteur, par opposition à l'illustration
#: d'une règle (« une cote de 1.50 correspond à 66 % » n'attribue rien).
_PROBA_ATTRIBUEE = re.compile(
    r"(?i)("
    r"\b(?:je\s+(?:donne|estime|table\s+sur)|j'estime)\b[^.\n]{0,40}?\d+(?:[.,]\d+)?\s*%"
    r"|\d+(?:[.,]\d+)?\s*%\s+de\s+(?:chances|probabilité)"
    r"|\b(?:ses|leurs)\s+chances\s+(?:sont|s'élèvent)\b[^.\n]{0,20}?\d+(?:[.,]\d+)?\s*%"
    r")")

#: Une cote ATTRIBUÉE à un bookmaker nommé — donc présentée comme relevée, pas
#: comme un exemple de calcul.
_COTE_ATTRIBUEE = re.compile(
    r"(?i)("
    r"\b(?:winamax|betclic|unibet|pmu|bwin|parions\s*sport|zebet)\b[^.\n]{0,40}?\d+[.,]\d{1,3}"
    r"|\d+[.,]\d{1,3}[^.\n]{0,25}?\b(?:chez|sur)\s+(?:winamax|betclic|unibet|pmu|bwin|zebet)\b"
    r")")

_FAITS_EXTERNES = (
    ("blessure", _BLESSURE), ("météo", _METEO), ("classement", _CLASSEMENT),
    ("source externe", _SOURCE_EXTERNE), ("rencontre", _FIXTURE),
    ("probabilité", _PROBA_ATTRIBUEE), ("cote", _COTE_ATTRIBUEE),
)

#: Une phrase qui NIE, interroge ou se déclare incapable n'affirme rien. Sans ce
#: filtre, « je ne peux pas te dire si elle est blessée » serait bloqué — et le
#: garde supprimerait la seule réponse honnête, exactement ce qu'il doit protéger.
_NON_ASSERTIF = re.compile(
    r"(?i)("
    r"\bn['e]\s*(?:\w+\s+){0,3}?(?:pas|plus|jamais|aucune?)\b"
    r"|\b(?:aucune?|nulle)\s+(?:donnée|information|source|cote|mesure|garantie|idée)"
    r"|\bje\s+ne\s+(?:sais|peux|dispose|dois)"
    r"|\bimpossible\s+de\b|\bsans\s+(?:donnée|source|vérification)"
    r"|\bn'?ai\s+pas\b|\bpas\s+(?:de|d')\s*(?:donnée|information|accès|source)"
    r"|\bsi\s+tu\s+veux\b|\?\s*$"
    r")")


def _faits_sans_source(text: str) -> list[str]:
    """Les faits concrets affirmés, phrase par phrase.

    Le découpage compte : une réponse peut nier dans une phrase et affirmer dans
    la suivante. Évaluer le texte entier laisserait la négation couvrir
    l'affirmation, ce qui est précisément la construction à surveiller.
    """
    trouves: list[str] = []
    for phrase in re.split(r"(?<=[.!?])\s+|\n+", text):
        if not phrase.strip() or _NON_ASSERTIF.search(phrase):
            continue
        for nom, motif in _FAITS_EXTERNES:
            if motif.search(phrase) and nom not in trouves:
                trouves.append(nom)
    return trouves


#: §17 — vocabulaire qui ne peut décrire aucun pari.
_TROMPEUR = re.compile(
    r"(?i)\b("
    r"pari\s+s[ûu]r|s[ûu]r\s+(?:de\s+)?(?:passer|gagner)|quasi[- ]?certain"
    r"|garanti[es]?|sans\s+risque|sans\s+aucun\s+risque|z[ée]ro\s+risque"
    r"|s[ée]curis[ée]|va\s+passer|ne\s+peut\s+pas\s+perdre|banco"
    r"|argent\s+facile|rendement\s+garanti"
    r")\b")

#: §10 — une borne basse élevée reste une ESTIMATION.
#:
#: « sûr à 90 % », « 90 % certain », « une certitude de 90 % » transforment une
#: probabilité prudente en promesse — exactement le glissement que
#: `probability_low` existe pour empêcher. Motif SÉPARÉ de `_TROMPEUR` parce que
#: ces formes se terminent par `%`, qui n'est pas un caractère de mot : la borne
#: `\b` finale du motif principal ne peut pas s'y appliquer.
#:
#: Le vocabulaire autorisé est « probabilité prudente estimée » — il dit la même
#: grandeur sans promettre l'issue.
_CERTITUDE_CHIFFREE = re.compile(
    r"(?i)("
    r"\d{1,3}\s*%\s*(?:de\s+)?(?:certain|s[ûu]re?s?|garanti|certitude)"
    r"|s[ûu]re?s?\s+à\s+\d{1,3}\s*%"
    r"|certitude\s+(?:de\s+|à\s+)?\d{1,3}\s*%"
    r"|garanti\s+à\s+\d{1,3}\s*%"
    r")")


#: Promesses sur le FONCTIONNEMENT du produit, qu'aucune mesure ne soutient.
#:
#: Catégorie distincte du « pari sûr » : ces phrases ne promettent pas un gain,
#: elles promettent un PROCESSUS — des modèles réentraînés chaque jour, une
#: équipe qui veille, une fenêtre plus courte qui ferait apparaître des paris
#: validés. Relevées sur de vraies réponses, elles sont d'autant plus nocives
#: qu'elles sonnent raisonnables : l'utilisateur attend, ou rétrécit sa demande,
#: pour un résultat que rien ne fera venir.
#:
#: Aucune n'est vraie ici. Les modèles ne se réentraînent pas tout seuls, aucune
#: équipe ne les met à jour, et la maturité dépend du ledger CLV — pas de la
#: largeur de la fenêtre. Une fenêtre plus courte réduit le nombre de candidats,
#: elle n'en promeut aucun.
_PROMESSE_INFONDEE = re.compile(
    r"(?i)("
    r"[ée]quipes?\s+de\s+recherche"
    r"|(?:mod[èe]les?|algorithmes?)\s+(?:sont\s+)?(?:mis\s+à\s+jour|réentraîn\w+|"
    r"actualis\w+)\s+(?:chaque|tous\s+les)\s+jours?"
    r"|mise\s+à\s+jour\s+quotidienne\s+des\s+mod[èe]les"
    r"|(?:limiter|r[ée]duire|restreindre|raccourcir)\s+la\s+fen[êe]tre[^.]{0,60}"
    r"(?:augmente|am[ée]liore|maximise)"
    r"|(?:augmente|am[ée]liore|maximise)[^.]{0,60}(?:trouver|obtenir)\s+"
    r"(?:des\s+)?paris\s+valid[ée]s"
    r"|reviens\s+(?:demain|plus\s+tard)[^.]{0,40}(?:validé|actionnable|misable)"
    # Relevées telles quelles sur de vraies réponses du modèle, toutes fausses :
    # allonger la fenêtre ne promeut aucun candidat (elle en ajoute, tous
    # EXPERIMENTAL) ; aucun rapport de maturité n'est publié quotidiennement ;
    # la bankroll n'entre dans AUCUN critère d'éligibilité, donc l'augmenter ne
    # peut rien rendre misable ; et « surveiller les mises à jour du moteur »
    # promet une évolution que rien ne planifie.
    r"|(?:allonger|étendre|elargir|élargir)\s+la\s+fen[êe]tre[^\n]{0,90}"
    r"(?:faire\s+apparaître|nouvelles?\s+opportunit|répondre|apparaître)"
    r"|rapports?\s+de\s+maturité[^\n]{0,40}(?:publiés?|quotidien)"
    r"|augmenter\s+(?:le\s+|votre\s+|la\s+)?bankroll[^\n]{0,90}"
    r"(?:pourra|permettra|proposer|actionnable|misable)"
    r"|surveiller\s+les\s+mises?\s+à\s+jour\s+du\s+moteur"
    r"|passera\s+le\s+seuil\s+de\s+maturité"
    # Demander à l'utilisateur d'abaisser son exigence pour avoir le DROIT de
    # voir des candidats : le rendu montre déjà les meilleurs sous le seuil, et
    # aucun seuil de probabilité n'a jamais empêché un candidat d'être affiché.
    r"|(?:abaisser|baisser|réduire|reduire|relâcher|relacher|élargir|elargir|"
    r"étendre|etendre)\s+(?:la\s+|le\s+|votre\s+|les\s+)?"
    r"(?:probabilité|seuil|exigence|fourchette|crit[èe]re|contrainte)[^\n]{0,90}"
    r"(?:permettrait|permet|récupérer|recuperer|obtenir|faire\s+apparaître|"
    r"apparaître|opportunit|actionnable|misable)"
    r")")


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
        "trompeur": bool(_TROMPEUR.search(text) or _CERTITUDE_CHIFFREE.search(text)),
        "promesse_infondee": bool(_PROMESSE_INFONDEE.search(text)),
    }


#: Identité d'ÉVÉNEMENT citée dans une réponse. Majuscules et `+` inclus : elle
#: porte un horodatage ISO (`…:2026-08-13T20:45:00Z:home=…`), et s'arrêter avant
#: le `T` n'en rapporterait qu'un fragment tronqué.
#:
#: SEULEMENT les événements, et c'est mesuré. Le contrôle a d'abord couvert
#: `competition:`, `team:` et `player:` — il a immédiatement bloqué la sortie
#: LÉGITIME du renderer, qui cite `competition:tennis:atp:tour` et
#: `player:tennis:atp:*`. Ces identités existent, mais dans des registres
#: DISPERSÉS (compétitions football en YAML, joueurs tennis dans le module
#: tennis, équipes NBA ailleurs) : il n'existe aucune source unique de vérité, et
#: une liste blanche incomplète bloque des réponses correctes. Un garde qui
#: censure le vrai est pire que pas de garde.
#:
#: Une identité d'événement, elle, ne vit dans AUCUN registre : elle naît du scan.
#: `evidence.event_ids` en est donc la liste EXHAUSTIVE, et la vérification est
#: exacte — pas heuristique.
_IDENTIFIANT_EVENEMENT = re.compile(r"\bevent:[A-Za-z0-9_.:|=+\-]{3,}")


def identifiants_fabriques(text: str, evidence: BettingResponseEvidence | None) -> list[str]:
    """Identités d'événement citées que le scan courant n'a pas produites.

    Sur un PSG–Aston Villa (compétition européenne, non onboardée), la réponse a
    proposé `event:football:eng:premier_league:…home=psg|away=aston_villa`. Cet
    événement n'a jamais existé, et le PSG ne joue pas en Premier League. Une
    identité inventée ressemble à une preuve : c'est ce qui la rend dangereuse.

    PORTÉE ASSUMÉE : ce contrôle ne voit pas une compétition RÉELLE mal appliquée
    (`competition:football:eng:premier_league` existe bel et bien). Cette
    faute-là est sémantique ; ce sont les libellés de refus et les conseils
    corrigés qui en suppriment l'incitation.
    """
    du_scan = frozenset(getattr(evidence, "event_ids", ()) or ())
    fabriques: list[str] = []
    for brut in _IDENTIFIANT_EVENEMENT.findall(text or ""):
        identifiant = brut.rstrip(".,;:)")
        # Un préfixe ou une troncature d'affichage d'un événement réel reste légitime.
        if any(e.startswith(identifiant) or identifiant.startswith(e) for e in du_scan):
            continue
        if identifiant not in fabriques:
            fabriques.append(identifiant)
    return fabriques


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

    # Avant tout le reste : une identité inventée est une preuve fabriquée. Elle
    # ne dépend pas de l'existence d'une evidence — au contraire, c'est quand le
    # moteur n'a RIEN pu résoudre que la tentation de combler est la plus forte.
    inventes = identifiants_fabriques(text, evidence)
    if inventes:
        return GuardVerdict(False, _identites_inventees(inventes), "FABRICATED_IDENTIFIER")

    # Une promesse sur le fonctionnement du produit est fausse avec preuve comme
    # sans : elle ne parle pas du run, elle parle d'un avenir que rien ne mesure.
    # Elle est donc contrôlée AVANT la séparation par evidence.
    if signaux["promesse_infondee"]:
        return GuardVerdict(False, _promesse_infondee(), "UNFOUNDED_PROCESS_CLAIM")

    if evidence is None:
        if signaux["trompeur"]:
            return GuardVerdict(False, _sans_preuve(signaux), "MISLEADING_LANGUAGE")
        if _asserts_opportunity(signaux):
            return GuardVerdict(False, _sans_preuve(signaux), "NO_STRUCTURED_EVIDENCE")
        if signaux["provenance"] and not prouve:
            return GuardVerdict(False, _sans_preuve(signaux), "FABRICATED_TOOL_CLAIM")
        # Les faits externes ne dépendent PAS de `has_structured_output` : aucun
        # outil hors `betting_recommend` n'en produit, et celui-là fournit une
        # preuve dès qu'il aboutit. Un tour sans preuve n'a donc rien constaté.
        faits = _faits_sans_source(text)
        if faits:
            return GuardVerdict(False, _faits_non_verifies(faits), "UNVERIFIED_EXTERNAL_FACT")
        return _OK

    if signaux["trompeur"]:
        return GuardVerdict(False, _langage_interdit(evidence), "MISLEADING_LANGUAGE")

    actionnable = evidence.recommendation_outcome in ACTIONABLE_OUTCOMES
    if not actionnable and (signaux["mise"] or signaux["recommande"] or signaux["ev_positive"]):
        return GuardVerdict(False, _non_actionnable(evidence), "NON_ACTIONABLE_OUTCOME")

    return _OK


# ── Remplacements déterministes ───────────────────────────────────────────────
def _promesse_infondee() -> str:
    """Remplace la promesse par l'état RÉEL du moteur et de la collecte.

    Le texte dit ce qui débloquerait réellement une mise, parce que c'est
    l'information que la promesse remplaçait — et la seule qui permette à
    l'utilisateur de décider s'il attend ou non.
    """
    return (
        "**Réponse retirée — affirmation non fondée sur le fonctionnement du produit.**\n\n"
        "Ce qui a été affirmé n'est mesuré nulle part. L'état réel :\n\n"
        "- les modèles ne sont pas réentraînés automatiquement, et aucune équipe "
        "ne les met à jour — leur version est figée jusqu'à un déploiement ;\n"
        "- rétrécir la fenêtre ne rend aucun candidat misable : cela réduit le "
        "nombre de rencontres examinées, sans toucher à leur maturité ;\n"
        "- ce qui autorise une mise est la maturité au ledger CLV, laquelle exige "
        "des rencontres indépendantes clôturées ET une borne de confiance "
        "strictement positive. Aucun délai ne l'accorde par défaut.\n\n"
        "Consulte l'état par capacité avec `axon clv-status`."
    )


def _identites_inventees(identifiants: list[str]) -> str:
    liste = "\n".join(f"  · `{i}`" for i in identifiants[:5])
    return (
        "**FABRICATED_IDENTIFIER** — réponse bloquée : elle cite une ou plusieurs "
        "identités d'événement que le scan courant n'a pas produites.\n\n"
        f"{liste}\n\n"
        "Une identité inventée ressemble à une preuve, et envoie chercher un "
        "problème là où il n'est pas. Si une compétition n'est pas onboardée, "
        "c'est cela qu'il faut dire — pas fabriquer l'identifiant qu'elle aurait "
        "si elle l'était."
    )


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


def _faits_non_verifies(faits: list[str]) -> str:
    """Nomme ce qui a été affirmé, sans le répéter.

    Reprendre la phrase d'origine la republierait sous une mise en garde, et une
    blessure inventée reste lisible même précédée d'un avertissement.
    """
    return (
        "**DATA_UNAVAILABLE** — réponse bloquée : aucun outil n'a été appelé "
        "pendant ce tour.\n\n"
        f"La rédaction affirmait des faits ({', '.join(faits)}) qu'aucune source "
        "n'a fournis. AXON ne dispose d'aucun flux de blessures, de météo, de "
        "classements ni de calendrier hors du scan bookmaker : ce qui n'a pas été "
        "scanné pendant ce tour n'a pas été constaté.\n\n"
        "Relance la demande pour déclencher un scan réel. Le contexte externe, "
        "quand il existe, apparaît sous « Contexte externe » avec sa source et "
        "reste informatif : il n'entre dans aucun calcul."
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
