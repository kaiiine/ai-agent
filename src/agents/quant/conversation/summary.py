"""Résumé LISIBLE d'un run — la partie que l'utilisateur lit vraiment.

Le rendu existant est exact et exhaustif : couverture, volumes, matrice de
bloqueurs, provenance, identifiants canoniques. C'est ce qu'il faut pour auditer
une décision, et c'est illisible pour décider quoi faire de vingt euros. Une
réponse qui commence par `**REVIEW_CANDIDATES** — audit
audit:a025678bee4e16e704275690` demande déjà un effort avant d'apprendre quoi
que ce soit.

Ce module ne calcule RIEN. Il lit les mêmes objets du domaine que le rendu
technique, et choisit ce qu'il en montre. En particulier :

- il ne classe pas — l'ordre vient de `rank_review`, seul juge du classement ;
- il ne dérive aucun montant ni aucune probabilité ;
- il n'agrège aucun indicateur de confiance. Moyenner calibration, couverture,
  fraîcheur et CLV donnerait un « 78/100 » qui a l'air d'une mesure et n'en est
  pas une : les composants sont montrés séparément, avec leur nom.

Deux pièges de présentation, tous deux constatés sur une vraie réponse :

- `edge` et `EV` ne racontent pas la même histoire. L'edge compare la probabilité
  du modèle à la probabilité sans marge ; l'EV compare le gain espéré à la cote
  réellement offerte. Un candidat peut afficher un edge positif ET une espérance
  négative — c'est arithmétiquement normal, et « edge +3 % » seul se lit comme
  « pari rentable ». Les deux sont donc nommés en toutes lettres, et une
  espérance négative est dite telle ;
- une absence de résultat web n'est pas une preuve d'absence. Rien ne s'affiche
  quand rien n'a été trouvé — surtout pas « aucune blessure connue ».
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..betting_engine.markets.review_ranking import MATURITE_ACTIONABLE
from .observability import NON_MESURE

#: Ce que l'utilisateur voit en tête. Purement décoratif — aucun sport n'est
#: traité différemment, et un sport absent d'ici s'affiche par son nom.
_EMOJI = {
    "tennis": "🎾", "football": "⚽", "basketball": "🏀", "baseball": "⚾",
    "american_football": "🏈", "hockey": "🏒", "volleyball": "🏐",
}

_LIBELLE_SPORT = {
    "tennis": "Tennis", "football": "Football", "basketball": "Basket",
    "baseball": "Baseball", "american_football": "Football américain",
    "hockey": "Hockey", "volleyball": "Volley",
}

#: Nombre de rencontres détaillées par défaut. Au-delà, la liste cesse d'être une
#: shortlist : trente candidats détaillés ne se lisent pas plus qu'aucun.
TOP_DETAILLE = 3
TOP_LISTE = 5

#: Raisons de l'Advisor traduites. Une raison absente d'ici s'affiche telle
#: quelle : mieux vaut un code brut qu'une phrase inventée qui le trahirait.
_RAISONS = {
    "EXPERIMENTAL_REVIEW_ONLY": "modèle encore EXPERIMENTAL — non validé pour la mise réelle",
    "MODEL_NOT_SUPPORTED": "modèle non validé pour ce marché",
    "FRESHNESS_UNKNOWN": "fraîcheur de la donnée non mesurable",
    "STALE_ODDS": "cote trop ancienne au moment de la décision",
    "LOW_DATA_QUALITY": "qualité des données insuffisante",
    "LOW_WORST_CASE_EV": "espérance au pire cas trop faible",
    "EVENT_ALREADY_STARTED": "rencontre déjà commencée",
    "IDENTITY_CONFLICT": "identité des participants ambiguë",
    "STAKE_LIMIT_TOO_LOW": "limite de mise trop basse chez le bookmaker",
    "BOOSTED_MARKET_NOT_SUPPORTED": "cote boostée — non modélisée",
    "RANKING_MISSING_FRESHNESS": "fraîcheur absente au classement",
    "RANKING_MODEL_NOT_SUPPORTED": "modèle non validé au classement",
    "USER_FILTERED_SPORT": "écarté par ton filtre de sport",
    "USER_FILTERED_COMPETITION": "écarté par ton filtre de compétition",
    "USER_FILTERED_MARKET": "écarté par ton filtre de marché",
}

#: Critères de maturité traduits, pour l'état du modèle.
_CRITERES = {
    "min_sample_size": "taille d'échantillon",
    "min_temporal_folds": "découpage temporel",
    "max_calibration_error": "calibration",
    "must_beat_baselines": "supériorité sur les baselines",
    "min_data_coverage": "couverture des données",
    "min_data_quality": "qualité des données",
    "positive_clv": "CLV (valeur à la clôture)",
    "measurable_live_freshness": "fraîcheur mesurable",
    "max_fold_brier_spread": "stabilité entre périodes",
}


def _pct(value: Decimal | None) -> str:
    return NON_MESURE if value is None else f"{(value * 100).quantize(Decimal('0.01'))} %"


def _points(value: Decimal | None) -> str:
    """Un écart de probabilités s'exprime en POINTS, pas en pourcent.

    « +3 % » sur une probabilité est ambigu : trois pour cent de quoi ? L'edge est
    une différence entre deux probabilités — sa vraie unité est le point.
    """
    if value is None:
        return NON_MESURE
    points = (value * 100).quantize(Decimal("0.01"))
    return f"{'+' if points >= 0 else ''}{points} pts"


def _pct_signe(value: Decimal | None) -> str:
    if value is None:
        return NON_MESURE
    pourcent = (value * 100).quantize(Decimal("0.01"))
    return f"{'+' if pourcent >= 0 else ''}{pourcent} %"


def _roles(candidate: Any) -> dict[str, str]:
    """`{role: canonical_id}` lu sur l'identité de l'événement.

    La clé canonique porte les rôles explicitement
    (`…:player_a=borges_n|player_b=darderi_l`) : c'est le domaine lui-même qui a
    écrit cette correspondance au moment de la résolution. La déduire de l'ordre
    de `participant_ids` reviendrait à la deviner — et à intervertir deux joueurs
    le jour où cet ordre changerait.
    """
    parties = (candidate.event_id or "").split(":")
    if not parties:
        return {}
    par_role: dict[str, str] = {}
    for morceau in parties[-1].split("|"):
        role, _, slug = morceau.partition("=")
        if not slug:
            continue
        for pid in candidate.participant_ids:
            if pid.rsplit(":", 1)[-1] == slug:
                par_role[role] = pid
    return par_role


def selection_lisible(candidate: Any) -> str:
    """Nom humain de la sélection — « Naomi Osaka », jamais « player_b ».

    Le nul n'a pas de participant : il se dit. Une sélection dont le rôle n'est
    pas retrouvé garde son code plutôt que d'emprunter un nom au hasard.
    """
    from .renderer import participant_label

    selection = candidate.selection
    if selection in ("draw", "nul"):
        return "match nul"
    identifiant = _roles(candidate).get(selection)
    if identifiant is None:
        return selection
    return participant_label([identifiant])


def rencontre_lisible(candidate: Any) -> str:
    from .renderer import participant_label
    return participant_label(candidate.participant_ids)


# ── Marchés : dire ce qu'on parie, pas seulement sur qui ─────────────────────
#: Libellés de familles. Un marché absent d'ici s'affiche par son nom canonique :
#: un code brut est lisible par quelqu'un, une paraphrase inventée ne l'est par
#: personne.
_LIBELLE_FAMILLE = {
    "MATCH_WINNER": "Vainqueur",
    "TOTALS": "Nombre de buts",
    "DOUBLE_CHANCE": "Double chance",
    "DRAW_NO_BET": "Vainqueur (remboursé si match nul)",
    "EXACT_SCORE": "Score exact",
    "HANDICAP": "Handicap",
    "OUTRIGHT_WINNER": "Vainqueur de l'épreuve",
}

#: Issues dont le nom ne désigne AUCUN participant : elles se traduisent seules.
#: Celles qui en désignent un passent par `selection_lisible`, qui va chercher le
#: nom canonique — « Naomi Osaka », jamais « player_b ».
_LIBELLE_ISSUE = {
    "over": "PLUS", "under": "MOINS",
    "other": "tout autre score",
}

#: Issues COMPOSITES : elles couvrent plusieurs résultats à la fois, et chacun
#: se dit avec le NOM de l'équipe concernée.
#:
#: « 1N — domicile ou nul » était un code doublé d'une paraphrase de rôle. Sur
#: « Casa Pia AC – Benfica », l'utilisateur devait savoir que Casa Pia reçoit
#: pour comprendre sur qui il parie — et rien à l'écran ne le lui disait. Une
#: sélection qu'on ne peut pas nommer est une sélection qu'on ne peut pas placer.
#:
#: `{0}` = équipe à domicile, `{1}` = équipe à l'extérieur ; les deux sont
#: résolues par le référentiel d'identités via les rôles écrits dans `event_id`.
_ISSUE_COMPOSITE = {
    "home_or_draw": "{0} gagne ou match nul",
    "draw_or_away": "match nul ou {1} gagne",
    "home_or_away": "{0} ou {1} gagne (pas de nul)",
}

#: Rôles DITS EN FRANÇAIS, pour le cas où le participant n'est pas nommable —
#: identité canonique sans rôle encodé, référentiel incomplet. Un rôle est une
#: notion interne : « player_a » demande à l'utilisateur de deviner lequel des
#: deux joueurs c'est, alors que « le premier joueur » ne prétend rien de plus
#: que ce qu'on sait réellement.
_ROLE_SANS_NOM = {
    "home": "l'équipe à domicile", "away": "l'équipe à l'extérieur",
    "player_a": "le premier joueur", "player_b": "le second joueur",
}


def libelle_marche(candidat: Any) -> str:
    """« Plus de 2.5 buts » — la famille ET son paramètre, jamais l'un sans l'autre.

    Une double chance et un Plus/Moins 2,5 affichés tous deux « TOTALS » se
    confondraient ; un Plus/Moins sans sa ligne est un pari qu'on ne peut pas
    placer. Le paramètre vient du marché observé, jamais d'un défaut.
    """
    famille = getattr(candidat.family, "value", str(candidat.family))
    nom = _LIBELLE_FAMILLE.get(famille, famille)
    ligne = (candidat.parameters or {}).get("line")
    if ligne is not None:
        return f"{nom} — seuil {ligne}"
    return nom


def libelle_issue(candidat: Any) -> str:
    """L'issue, dite en clair. Un score exact garde sa forme domicile:extérieur.

    Une issue qui désigne un COMPÉTITEUR passe par le référentiel d'identités :
    « player_a » est un rôle interne, et l'afficher tel quel demande à
    l'utilisateur de savoir lequel des deux joueurs c'est.
    """
    issue = candidat.selection
    if issue in _LIBELLE_ISSUE:
        return _LIBELLE_ISSUE[issue]
    if issue in _ISSUE_COMPOSITE:
        return _issue_composite(candidat, issue)
    if issue in ("draw", "nul"):
        return "match nul"
    if ":" in issue:
        return f"score {issue} (domicile:extérieur)"
    nomme = selection_lisible(candidat)
    return nomme if nomme != issue else _ROLE_SANS_NOM.get(issue, issue)


def _issue_composite(candidat: Any, issue: str) -> str:
    """Une issue qui couvre plusieurs résultats, dite avec les NOMS des équipes.

    Les rôles viennent d'`event_id`, écrit par le domaine au moment de la
    résolution — jamais de l'ordre de `participant_ids`, qui n'est pas un
    contrat et intervertirait deux équipes le jour où il changerait.

    Si un rôle manque, on retombe sur la formulation de rôle plutôt que
    d'emprunter un nom au hasard : « l'équipe à domicile » ne prétend rien de
    plus que ce qu'on sait, un mauvais nom prétend beaucoup trop.
    """
    from .renderer import participant_label

    par_role = _roles(candidat)
    noms = []
    for role in ("home", "away"):
        identifiant = par_role.get(role)
        noms.append(participant_label([identifiant]) if identifiant
                    else _ROLE_SANS_NOM[role])
    return _ISSUE_COMPOSITE[issue].format(*noms)


#: Ce que compte un total, par famille de marché. Sert uniquement à écrire
#: « moins de 2,5 BUTS » plutôt que « MOINS — Nombre de buts — seuil 2.5 ».
_UNITE_DU_TOTAL = {
    "football": "buts", "basketball": "points", "american_football": "points",
    "baseball": "runs", "hockey": "buts", "tennis": "jeux", "volleyball": "points",
}


def pari_lisible(candidat: Any) -> str:
    """Le pari en une phrase placable : sur quoi, et à quelle valeur.

    Existe parce que la composition mécanique « {issue} — {marché} » produisait
    « MOINS — Nombre de buts — seuil 2.5 @ 2.6 », où deux nombres se suivent
    sans que rien ne dise lequel est la ligne et lequel est la cote. Relevé en
    production : une réponse a présenté le seuil 2,5 COMME la cote.

    Les totaux se disent donc « moins de 2,5 buts » ; les handicaps portent leur
    valeur ; le reste garde la forme « issue — marché », déjà sans ambiguïté.
    """
    famille = getattr(candidat.family, "value", str(candidat.family))
    parametres = candidat.parameters or {}
    ligne = parametres.get("line")
    issue = candidat.selection

    if famille in ("TOTALS", "TEAM_TOTALS") and ligne is not None:
        sens = {"over": "plus de", "under": "moins de"}.get(issue)
        if sens:
            unite = _UNITE_DU_TOTAL.get(candidat.sport, "unités")
            camp = parametres.get("side")
            precision = f" pour {camp}" if camp else ""
            return f"{sens} {ligne} {unite}{precision}"

    if famille == "HANDICAP":
        handicap = parametres.get("handicap")
        nomme = libelle_issue(candidat)
        if handicap is not None:
            return f"{nomme} avec handicap {handicap}"

    return f"{libelle_issue(candidat)} — {libelle_marche(candidat)}"


def rencontre_du_candidat(candidat: Any) -> str:
    """Le nom de la rencontre. Le référentiel canonique d'abord ; le libellé du
    bookmaker en repli — il est lisible, mais c'est son orthographe à lui."""
    if getattr(candidat, "participant_ids", ()):
        return rencontre_lisible(candidat)
    return candidat.event_label or candidat.source_event_id


def _flottant_pct(valeur) -> str:
    return NON_MESURE if valeur is None else f"{valeur * 100:.2f} %"


def _flottant_pct_signe(valeur) -> str:
    if valeur is None:
        return NON_MESURE
    return f"{'+' if valeur >= 0 else ''}{valeur * 100:.2f} %"


def population_de_revue(review: Any, cible: Any) -> list[Any]:
    """Les candidats REVUE à considérer — et POURQUOI la population change.

    Sans préférence exprimée, c'est le classement produit : un côté par marché,
    celui au meilleur score. C'est le bon choix pour classer des opportunités.

    Dès qu'une PROBABILITÉ est demandée, cette réduction devient fausse. Elle
    garde le côté au meilleur score, c'est-à-dire orienté espérance : sur « buts
    — seuil 5,5 » le côté conservé est le « Plus » à grosse cote, et le « Moins »
    à 91 % de borne basse — exactement celui demandé — disparaît. Mesuré sur un
    run réel : trois candidats atteignaient 91 %, un seul était affichable.

    Les deux populations sortent du même moteur de classement et des mêmes
    verdicts de politique. Ce qui change est le nombre de côtés retenus, jamais
    un seuil ni un score.
    """
    if review is None:
        return []
    if cible is None:
        return list(review.review)
    return list(getattr(review, "review_tous_cotes", None) or review.review)


def render_compteurs_revue(response: Any, review: Any, cible: Any,
                           *, objectif: Any = None,
                           top: int = TOP_LISTE) -> list[str]:
    """Les quatre nombres qui disent si la réponse tient debout.

    Ils existent parce qu'une sortie sans candidat était indistinguable d'une
    sortie sans candidat À MONTRER : « 0 pari » se lisait « rien à voir » alors
    que le moteur avait produit plus de mille probabilités. Affichés côte à côte,
    `ACTIONABLE: 0` et `REVIEW_ELIGIBLE: 1174` ne peuvent plus se confondre.

    Ils lisent la MÊME population que l'affichage : un compteur qui annonce trois
    candidats au-dessus du seuil pendant que la section n'en montre qu'un est
    précisément le défaut que ces nombres servent à rendre impossible.
    """
    if review is None:
        return []
    from .review_preference import partitionner

    classes = population_de_revue(review, cible)
    partition = partitionner(classes, cible)
    if cible is None:
        affiches = min(top, len(classes))
        au_seuil = NON_MESURE                      # aucun seuil demandé
    else:
        affiches = min(top, len(partition.au_seuil) or len(partition.sous_seuil))
        au_seuil = str(len(partition.au_seuil))

    lignes = [
        "",
        f"ACTIONABLE: {len(response.portfolios)}",
        f"REVIEW_ELIGIBLE: {len(classes)}",
        f"REVIEW >= seuil demandé (probability_low): {au_seuil}",
        f"REVIEW DISPLAYED: {affiches}",
    ]
    if objectif is not None:
        from .review_preference import partitionner_par_objectifs

        p = partitionner_par_objectifs(classes, cible, objectif)
        lignes += [
            f"REVIEW >= seuil ET proche de l'objectif de cote: {len(p.a_les_deux)}",
            f"REVIEW proche de l'objectif mais sous le seuil: "
            f"{len(p.c_proches_de_la_cote)}",
        ]
    return lignes


def _fiche_candidat(r: Any, numero: Any = None) -> list[str]:
    """La fiche COMPLÈTE d'un candidat de revue.

    Tous les champs demandés y sont, y compris ceux qui manquent : une grandeur
    non mesurée s'écrit `NON_MESURE`, jamais un zéro ni une valeur de repli. La
    distinction porte une décision — `freshness=None` veut dire « on ne sait pas
    quand », et l'écrire `0` en ferait « périmé », qui est une autre réponse.
    """
    c = r.candidate
    tete = f"{numero if numero is not None else r.global_rank}. "
    # La ligne de tête porte le PARI COMPLET — sur quoi, à quelle cote — et pas
    # seulement le nom de la rencontre. Une reformulation en aval peut perdre
    # les lignes de détail ; elle ne peut pas perdre le titre. Mesuré : une
    # réponse listait « Casa Pia – Benfica · Double chance · 4.0 » sans jamais
    # dire sur qui, et l'utilisateur ne pouvait pas placer le pari.
    return [
        f"{tete}{rencontre_du_candidat(c)}{_quand(c)}"
        f"  ({_LIBELLE_SPORT.get(c.sport, c.sport)})",
        f"   ▸ PARI : {pari_lisible(c)}  ·  COTE {_valeur_ou_non_mesure(c.bookmaker_odds)}",
        f"   Marché : {libelle_marche(c)}",
        f"   Sélection : {libelle_issue(c)}",
        f"   Cote : {_valeur_ou_non_mesure(c.bookmaker_odds)}",
        f"   Probabilité du modèle (fair) : {_flottant_pct(c.fair_probability)}",
        f"   Probabilité basse mesurée (probability_low) : "
        f"{_flottant_pct(c.probability_low)}",
        f"   Probabilité sans marge (vig_adjusted) : "
        f"{_flottant_pct(c.vig_adjusted_probability)}",
        f"   Edge vs prix sans marge : {_flottant_pct_signe(c.edge)}"
        f"  ·  edge prudent : {_flottant_pct_signe(c.edge_prudent)}",
        f"   EV settlement-aware : {_flottant_pct_signe(c.expected_value)}"
        f"  ·  EV prudente : {_flottant_pct_signe(r.expected_value_low)}",
        f"   Qualité des données : {_valeur_ou_non_mesure(c.data_quality)}"
        f"  ·  Fraîcheur : {_valeur_ou_non_mesure(c.freshness)}",
        f"   Modèle / capacité : {_valeur_ou_non_mesure(c.model_name)} "
        f"({_valeur_ou_non_mesure(c.model_version)})"
        f"  ·  origine de la probabilité : {_valeur_ou_non_mesure(c.probability_origin)}",
        f"   Maturité : {_valeur_ou_non_mesure(c.maturity)}",
        f"   Statut : REVIEW / EXPERIMENTAL — aucune mise autorisée",
        f"   Ce qui empêche ACTIONABLE : {_blocage_actionable(c)}",
        "",
    ]


def _valeur_ou_non_mesure(valeur: Any) -> str:
    """Une absence reste une absence. On n'invente jamais de valeur de repli."""
    return NON_MESURE if valeur is None else str(valeur)


def _blocage_actionable(c: Any) -> str:
    """La raison EXACTE, lue sur le candidat — jamais une raison plausible.

    L'ordre suit celui des portes réellement franchies : la politique
    d'éligibilité s'exprime en premier si elle a parlé, la maturité ensuite.
    """
    if c.abstention_reasons:
        return " ; ".join(str(motif) for motif in c.abstention_reasons)
    if c.maturity and c.maturity != MATURITE_ACTIONABLE:
        return (f"maturité {c.maturity} — le ledger CLV n'a validé aucune décision "
                f"de support pour {_valeur_ou_non_mesure(c.model_version)}")
    return NON_MESURE


def _render_cote_seule(classes, objectif, top: int) -> list[str]:
    """Un objectif de cote SANS seuil de probabilité demandé.

    Le tri est alors par PROBABILITÉ PRUDENTE décroissante, et c'est la seule
    réponse honnête à « des paris quasi sûrs, autour de x2 » : on respecte
    l'objectif de cote, puis on montre les plus probables. Inventer un seuil —
    90 %, par exemple — imposerait une contrainte que personne n'a demandée,
    puis ferait répondre « aucun pari » à une question qui admettait une réponse.
    """
    from .review_preference import les_plus_probables, plus_proches_de_la_cote

    dans = [r for r in classes if objectif.contient(r.candidate.bookmaker_odds)]
    lignes = ["", f"## Les plus probables autour de l'objectif — "
                  f"{objectif.describe()}", ""]
    if dans:
        lignes += [
            f"{len(dans)} candidat(s) dans la fourchette de cote, classés par "
            "probabilité prudente estimée décroissante. Aucun seuil de "
            "probabilité n'a été demandé, et aucun n'est imposé.",
            "",
        ]
        ordonnes = les_plus_probables(dans)
    else:
        lignes += [
            "Aucun candidat évalué ne tombe dans la fourchette de cote. Voici "
            f"les {min(top, len(classes))} plus proches, classés par proximité :",
            "",
        ]
        ordonnes = plus_proches_de_la_cote(classes, objectif)
    for i, r in enumerate(ordonnes[:top], start=1):
        lignes += _fiche_candidat(r, numero=i)
    return lignes


def _render_deux_objectifs(classes, seuil, objectif, top: int) -> list[str]:
    """§9 — les deux préférences, en sections DISJOINTES.

    Le point entier de ce rendu est de ne pas mélanger. Un classement unique
    laisserait une grosse cote compenser une probabilité basse, et rendrait à
    l'utilisateur le « x2 » qu'il demandait en lui retirant, sans le dire, la
    prudence qu'il demandait aussi.
    """
    from .review_preference import partitionner_par_objectifs

    p = partitionner_par_objectifs(classes, seuil, objectif)
    pct = f"{seuil * 100:.0f} %"
    lignes: list[str] = []

    lignes += ["", f"## REVUE — respecte {pct} ET {objectif.describe()}", ""]
    if p.a_les_deux:
        lignes += [f"{len(p.a_les_deux)} candidat(s) satisfont les deux critères. "
                   "Ils restent EXPERIMENTAL — aucune mise n'est autorisée.", ""]
        for i, r in enumerate(p.a_les_deux[:top], start=1):
            lignes += _fiche_candidat(r, numero=i)
    else:
        lignes += [
            "**Aucun candidat ne satisfait simultanément ces deux critères.**",
            "",
            f"Aucun pari évalué ne présente à la fois une probabilité prudente "
            f"estimée ≥ {pct} et une cote dans la fourchette visée. C'est attendu : "
            "une probabilité élevée et une cote élevée sont deux demandes opposées, "
            "et le moteur ne compense pas l'une par l'autre.",
            "",
            "Les deux objectifs sont donc présentés séparément ci-dessous.",
            "",
        ]

    lignes += ["", f"## REVUE — respecte {pct}, mais cote hors objectif", ""]
    if p.b_probabilite_seule:
        for i, r in enumerate(p.b_probabilite_seule[:top], start=1):
            lignes += _fiche_candidat(r, numero=i)
    else:
        lignes += [f"Aucun candidat n'atteint {pct} de probabilité prudente estimée.", ""]

    proches = p.c_proches_de_la_cote or p.c_sous_le_seuil
    lignes += ["", f"## REVUE — proche de l'objectif de cote, mais sous {pct}", ""]
    if proches:
        lignes += ["Ces candidats N'ATTEIGNENT PAS la probabilité demandée. Ils sont "
                   "montrés parce que tu as exprimé un objectif de cote, jamais "
                   "comme un substitut au seuil de probabilité.", ""]
        for i, r in enumerate(proches[:top], start=1):
            lignes += _fiche_candidat(r, numero=i)
    else:
        lignes += ["Aucun candidat évalué dans cette fourchette de cote.", ""]

    if p.sans_borne_basse:
        lignes += [f"{len(p.sans_borne_basse)} candidat(s) sans borne basse mesurée : "
                   "ni au-dessus ni en dessous du seuil, donc non comparables.", ""]
    return lignes


def render_marches_en_revue(review: Any, *, top: int = TOP_LISTE,
                            cible: Any = None, objectif: Any = None) -> list[str]:
    """§8 — les meilleures opportunités TOUS MARCHÉS, explicitement non misables.

    Cette section existe parce que la précédente répondait toujours « qui gagne » :
    c'était le seul marché évalué, donc le seul montrable. Elle affiche désormais
    ce que le modèle sait réellement pricer, et le nomme — le marché, son
    paramètre, l'issue.

    AUCUN NOMBRE N'EST CALCULÉ ICI. Chacun est lu sur le candidat classé, y
    compris l'espérance prudente et l'edge, qui sont des propriétés du domaine et
    non des formules réécrites pour l'affichage.

    `cible` est la probabilité demandée par l'utilisateur. Elle ORDONNE, elle ne
    filtre pas : les candidats sous le seuil restent affichés dans leur propre
    section. Répondre « aucun candidat n'atteint 90 % » puis se taire serait la
    même impasse que de ne rien montrer du tout.
    """
    if review is None:
        return []
    from .review_preference import partitionner

    lignes: list[str] = []
    classes = population_de_revue(review, cible)
    if not classes:
        return lignes

    partition = partitionner(classes, cible)

    if objectif is not None and partition.cible is not None:
        return lignes + _render_deux_objectifs(classes, partition.cible, objectif, top)

    if partition.cible is None:
        if objectif is not None:
            return lignes + _render_cote_seule(classes, objectif, top)
        lignes += ["", "## Meilleures opportunités en revue — NON MISABLES", ""]
        for r in classes[:top]:
            lignes += _fiche_candidat(r)
    elif partition.atteint:
        seuil = f"{partition.cible * 100:.0f} %"
        lignes += [
            "",
            f"## Candidats atteignant {seuil} de probabilité prudente — NON MISABLES",
            "",
            f"{len(partition.au_seuil)} candidat(s) dont la borne basse mesurée "
            f"atteint {seuil}. Ils restent EXPERIMENTAL : atteindre ta préférence "
            "ne rend rien misable.",
            "",
        ]
        for i, r in enumerate(partition.au_seuil[:top], start=1):
            lignes += _fiche_candidat(r, numero=i)
    else:
        seuil = f"{partition.cible * 100:.0f} %"
        lignes += [
            "",
            f"## Aucun candidat n'atteint {seuil} de probabilité prudente",
            "",
            f"Sur {partition.total} candidat(s) en revue : "
            f"{len(partition.sous_seuil)} ont une borne basse mesurée sous {seuil}, "
            f"et {len(partition.sans_borne_basse)} n'ont pas de borne basse mesurée "
            "— ceux-là ne sont pas comparables à ton seuil, ni au-dessus ni en "
            "dessous. La probabilité du modèle (`fair`) n'est PAS retenue comme "
            "équivalente : tu demandes une garantie, elle n'en est pas une.",
            "",
            f"Voici néanmoins les {min(top, len(partition.sous_seuil))} meilleurs "
            "candidats EXPERIMENTAL observés sous ce seuil :",
            "",
        ]
        for i, r in enumerate(partition.sous_seuil[:top], start=1):
            lignes += _fiche_candidat(r, numero=i)

    # Ce qui n'a PAS pu être comparé, et pourquoi. Un classement qui ne montre que
    # ses gagnants laisse croire que le reste a perdu.
    if review.non_comparables:
        motifs: dict[str, int] = {}
        for r in review.non_comparables:
            for motif in r.reasons:
                motifs[motif] = motifs.get(motif, 0) + 1
        lignes += ["", f"Non comparables : {len(review.non_comparables)} sélection(s)"]
        for motif, n in sorted(motifs.items(), key=lambda kv: -kv[1])[:4]:
            lignes.append(f"- {motif} — {n}")
    if review.ecartes_par_politique:
        lignes.append(f"- écartés par la politique d'éligibilité : "
                      f"{len(review.ecartes_par_politique)}")
    return lignes


def _quand(candidat: Any) -> str:
    """L'horaire, quand il est connu. Distingue deux rencontres des mêmes
    équipes — une série de baseball en programme deux en deux jours."""
    moment = getattr(candidat, "scheduled_at", None)
    if moment is None:
        return ""
    from .window import to_paris

    return f" ({to_paris(moment):%d/%m %H:%M})"


def _maturite_du_combo(combo: Any) -> str:
    """Un combiné hérite de la maturité la PLUS FAIBLE de ses jambes.

    Prendre la meilleure ferait passer un combiné pour plus mûr que la moins
    éprouvée des sélections qui le composent.
    """
    rang = {"EXPERIMENTAL": 0, "PROVISIONAL": 1, "SUPPORTED": 2}
    maturites = [getattr(l, "maturity", None) for l in combo.legs]
    connues = [m for m in maturites if m]
    if not connues or len(connues) < len(maturites):
        return NON_MESURE
    return min(connues, key=lambda m: rang.get(m, -1))


def render_combines_exploratoires(review: Any, contraintes: Any, cible: Any,
                                  *, objectif: Any = None,
                                  top: int = 3) -> list[str]:
    """Les combinés EXPLORATOIRES — si l'utilisateur les demande, ou si son
    objectif de cote n'est atteint par aucun pari simple.

    §4 : un objectif de cote qu'aucun simple ne satisfait est une raison
    légitime d'en chercher un. Ce n'est pas une suggestion spontanée — c'est la
    seule réponse possible à la demande, et se taire reviendrait à répondre
    « non » sans avoir cherché.
    """
    if review is None:
        return []
    population = population_de_revue(review, cible)
    demande = getattr(contraintes, "allow_combos", False)
    if not demande:
        if objectif is None:
            return []
        # Aucun simple dans la fourchette -> le combiné devient la seule piste.
        if any(objectif.contient(r.candidate.bookmaker_odds) for r in population):
            return []

    from .review_combos import construire

    combines = construire(population, top=top, objectif=objectif)
    if not combines:
        return []

    lignes = [
        "",
        "## Combinés exploratoires — EXPERIMENTAL, NON MISABLES",
        "",
        "Construits UNIQUEMENT sur des candidats de revue réellement évalués, avec "
        "la règle de corrélation du chemin argent. Aucun n'est misable, et aucun "
        "ne peut le devenir : un combiné hérite du statut le plus faible de ses "
        "jambes, toutes EXPERIMENTAL ici.",
        "",
    ]
    for i, combo in enumerate(combines, start=1):
        lignes.append(f"{i}. Cote combinée : {combo.cote_combinee:.2f}"
                      f"  ·  dépendance : {combo.dependance_lisible}"
                      f"  ·  maturité : {_maturite_du_combo(combo)}")
        for leg in combo.legs:
            lignes.append(f"   · {rencontre_du_candidat(leg)}{_quand(leg)} — "
                          f"{libelle_marche(leg)} / {libelle_issue(leg)} "
                          f"@ {leg.bookmaker_odds}")
        lignes.append(f"   Probabilité jointe : {combo.probabilite_lisible}")
        lignes.append(f"   Probabilité jointe basse : "
                      f"{_flottant_pct(combo.probabilite_jointe_basse)}")
        lignes.append(f"   EV combinée : {combo.ev_lisible}")
        motif = combo.motif_non_estimee
        if motif:
            lignes.append(f"   Pourquoi non estimée : {motif}")
        lignes.append(f"   Statut : {combo.statut} — aucune mise")
        lignes.append("")
    return lignes


def render_meilleur_par_rencontre(review: Any, *, top_evenements: int = 3,
                                  top_marches: int = 6) -> list[str]:
    """§3 — pour une rencontre, TOUS ses marchés priceables, puis le meilleur.

    Ne montre que les rencontres dont le meilleur marché N'EST PAS « qui gagne » :
    partout ailleurs, la section précédente dit déjà la même chose. C'est aussi la
    seule preuve produit que le chantier a changé quelque chose.
    """
    if review is None:
        return []
    interessants = review.evenements_dont_le_meilleur_n_est_pas_le_vainqueur
    if not interessants:
        return []
    lignes = ["", "## Rencontres dont le meilleur marché n'est pas le vainqueur", ""]
    for event_id in interessants[:top_evenements]:
        classees = review.par_evenement[event_id][:top_marches]
        premier = classees[0].candidate
        lignes.append(rencontre_du_candidat(premier))
        for r in classees:
            c = r.candidate
            marque = "  ← MEILLEUR MARCHÉ" if r.event_rank == 1 else ""
            lignes.append(
                f"   {r.event_rank}. {libelle_marche(c)} · {libelle_issue(c)} "
                f"@ {c.bookmaker_odds} · espérance prudente "
                f"{_flottant_pct_signe(r.expected_value_low)}{marque}")
        lignes.append("")
    return lignes


def _sport_entete(sports: list[str]) -> str:
    if len(sports) == 1:
        sport = sports[0]
        return f"{_EMOJI.get(sport, '•')} {_LIBELLE_SPORT.get(sport, sport)}"
    return "🎯 Tous sports"


def _checklist(evaluation: Any, readiness: Any) -> list[str]:
    """Pourquoi ce n'est pas encore misable — chaque ligne adossée à un fait.

    Les ✓ ne sont pas décoratifs : ils énoncent ce qui a RÉELLEMENT été vérifié.
    Un ✓ « modèle calibré » n'apparaît que si le critère de calibration est
    effectivement passé pour ce modèle ; sans mesure de readiness sous la main,
    la ligne n'est pas écrite du tout.
    """
    lignes = ["✓ rencontre évaluée par le modèle (identité et marché résolus)"]

    if readiness is not None:
        if "max_calibration_error" in readiness.passed:
            lignes.append("✓ modèle calibré sur son historique")
        if "min_sample_size" in readiness.passed:
            lignes.append("✓ échantillon de validation suffisant")
        if "must_beat_baselines" in readiness.passed:
            lignes.append("✓ modèle plus précis que les baselines")

    for raison in evaluation.policy_reasons:
        lignes.append(f"✗ {_RAISONS.get(raison, raison)}")

    if readiness is not None:
        for critere in readiness.blockers:
            if critere == "positive_clv":
                acquis, requis = readiness.clv_events, readiness.clv_required
                if acquis is not None and requis:
                    lignes.append(f"✗ CLV en accumulation — {acquis} rencontre(s) "
                                  f"sur les {requis} requises")
                else:
                    lignes.append("✗ CLV pas encore mesurable")
            elif critere == "measurable_live_freshness":
                continue          # déjà dit par FRESHNESS_UNKNOWN côté Advisor
            else:
                lignes.append(f"✗ {_CRITERES.get(critere, critere)} — critère de "
                              "maturité non atteint")
    return lignes


def _contexte(obs: Any, candidate: Any) -> list[str]:
    """Faits externes, et RIEN si rien n'a été trouvé.

    Une section « Contexte vérifié » vide, ou remplie d'un « aucune blessure
    connue », transformerait une absence de résultat en preuve d'absence. Ce
    n'est pas la même chose, et c'est la confusion la plus coûteuse que puisse
    produire une couche de recherche web.
    """
    features = obs.features_for(candidate) if obs is not None else ()
    if not features:
        return []
    lignes = ["", "   Contexte externe vérifié (informatif — n'entre dans aucun calcul) :"]
    for f in features:
        marque = {"OFFICIAL": "✓", "REPUTABLE": "·"}.get(f.confidence, "⚠")
        lignes.append(f"   {marque} {f.value[:180]} — {f.source[:50]}")
    return lignes


def _readiness_du_candidat(obs: Any, candidate: Any) -> Any:
    """La readiness du modèle qui a produit CE candidat, ou None."""
    if obs is None or not obs.readiness:
        return None
    for r in obs.readiness:
        if r.model_version == candidate.model_version:
            return r
    for r in obs.readiness:
        if r.sport == candidate.sport:
            return r
    return None


def _rencontre(ligne: Any, obs: Any, index: int) -> list[str]:
    from .window import to_paris

    c = ligne.candidate
    lignes = [
        "",
        f"{index}. {rencontre_lisible(c)}",
        f"   Coup d'envoi : {to_paris(c.scheduled_at):%d/%m à %H:%M} (Paris)",
        f"   Sélection observée : {selection_lisible(c)}",
        f"   Cote {c.bookmaker.capitalize()} : {c.bookmaker_odds}",
        f"   Probabilité du modèle : {_pct(c.fair_probability)}",
        f"   Probabilité implicite de la cote : {_pct(c.implied_probability)}",
    ]

    # Les deux grandeurs sont NOMMÉES : « edge » seul laisse croire que le pari
    # est rentable, alors qu'il compare des probabilités et non des gains.
    adapte = obs.adapted_for(c) if obs is not None else None
    sans_marge = getattr(adapte, "no_vig_probability", None)
    if sans_marge is not None:
        lignes.append(f"   Probabilité sans marge du bookmaker : {_pct(sans_marge)}")
    lignes += [
        f"   Avantage vs probabilité sans marge : {_points(c.edge_low)}",
        f"   Espérance à la cote actuelle : {_pct_signe(c.expected_value_low)}",
    ]
    if c.expected_value_low is not None and c.expected_value_low <= 0:
        lignes.append("   ⚠ espérance actuellement NÉGATIVE à cette cote — "
                      "un avantage de probabilité ne suffit pas à la rendre positive")
    lignes.append("   Statut : REVIEW ONLY — aucune mise")

    lignes.append("")
    lignes.append("   Pourquoi ce n'est pas encore misable :")
    lignes += [f"   {l}" for l in _checklist(ligne.evaluation, _readiness_du_candidat(obs, c))]
    lignes += _contexte(obs, c)
    return lignes


#: Refus du Betting Engine : libellé + le temps peut-il y changer quelque chose ?
#: Un code absent d'ici s'affiche tel quel — un code brut vaut mieux qu'une phrase
#: inventée qui le trahirait.
#:
#: `EVENT_NOT_RESOLVED` disait « participants inconnus de notre référentiel ».
#: C'était FAUX sur le cas qui l'a révélé : PSG et Aston Villa étaient tous deux
#: dans le référentiel, et c'est la COMPÉTITION (une européenne, non onboardée)
#: qui ne se rattachait à rien. Le libellé accusait une cause non vérifiée et
#: envoyait chercher au mauvais endroit. Il ne nomme plus que ce qui est établi :
#: l'identité de la rencontre n'a pas été résolue — participants OU compétition.
#:
#: `attendre` gouverne le conseil. Dire « re-scanne dans 24 h » sur une
#: compétition non onboardée est un conseil qui ne peut pas marcher.
_REFUS: dict[str, tuple[str, bool]] = {
    "EVENT_NOT_RESOLVED": (
        "rencontre non rattachée à une compétition connue (participants ou "
        "compétition non résolus)", False),
    "COMPETITION_NOT_RESOLVED": (
        "compétition absente du référentiel — non onboardée dans AXON", False),
    "COMPETITION_NOT_COVERED": (
        "compétition connue, mais aucun provider vérifié ne la couvre", False),
    "SPORT_NOT_SUPPORTED": ("sport sans modèle disponible", False),
    "MARKET_CANONICALIZATION_FAILED": ("marché illisible pour ce sport", False),
    "INSUFFICIENT_FEATURES": ("historique trop mince pour ce match", True),
    "DATA_TOO_STALE": ("données trop anciennes", True),
    "GATEWAY_UNAVAILABLE": ("source de données indisponible", True),
}

#: Ce que l'utilisateur peut réellement faire, par famille de blocage. Aucune
#: mention d'attente là où l'attente ne résout rien.
_CONSEIL_STRUCTUREL = (
    "Ces rencontres sont proposées par le bookmaker, mais AXON n'a pas de modèle "
    "compatible avec leur compétition. Attendre n'y changera rien : il faut "
    "onboarder la compétition (référentiel + rattachement bookmaker + données "
    "historiques + benchmark).")
_CONSEIL_TEMPOREL = (
    "Ces rencontres peuvent devenir évaluables : les données manquantes "
    "s'enrichissent avec le temps ou au prochain rafraîchissement.")


def _pourquoi_rien(run: Any, obs: Any) -> list[str]:
    """Ce qui a réellement manqué, agrégé — jamais une raison plausible."""
    if obs is None:
        return []
    telemetrie = obs.telemetry
    if telemetrie.events_inside_window == 0:
        return ["",
                f"Aucune rencontre dans cette fenêtre : {telemetrie.catalog_events_total} "
                f"événement(s) au catalogue, tous en dehors. Élargis la période "
                f"pour en trouver."]

    refus = obs.pre_evaluation_refusals
    if not refus:
        return []
    lignes = ["", f"{telemetrie.events_inside_window} rencontre(s) dans la fenêtre, "
                  "aucune évaluable :"]
    structurel = temporel = 0
    for code, nombre in sorted(refus.items(), key=lambda kv: (-kv[1], kv[0])):
        libelle, attendre = _REFUS.get(code, (code, True))
        lignes.append(f"  · {nombre} — {libelle}")
        if code in _REFUS:
            temporel += nombre if attendre else 0
            structurel += 0 if attendre else nombre

    # Le conseil suit le blocage réel. Sans cette phrase, la couche de résumé
    # comblait le vide par « re-scanne dans 24 h » — un conseil qui ne pouvait
    # pas marcher, et un identifiant de compétition inventé pour l'illustrer.
    if structurel:
        lignes += ["", _CONSEIL_STRUCTUREL]
    if temporel:
        lignes += ["", _CONSEIL_TEMPOREL]
    return lignes


def render_resume(run: Any, *, top_liste: int = TOP_LISTE,
                  top_detaille: int = TOP_DETAILLE) -> list[str]:
    """Le résumé lisible. Ne remplace pas le rendu technique — il le précède."""
    from .review_ranking import rank_review

    response, obs = run.response, run.observability
    contraintes = run.constraints
    fenetre = contraintes.time_window

    # Les sports RENCONTRÉS d'abord ; à défaut, ceux qui ont été DEMANDÉS. Une
    # fenêtre vide ne doit pas transformer « basket » en « tous sports » : le
    # titre décrirait alors la recherche que l'utilisateur n'a pas faite.
    sports = list(obs.sports_in_window) if obs is not None else []
    if not sports:
        demandes = contraintes.resolved_scope("sports")
        sports = sorted(demandes) if demandes else []

    lignes = [f"{_sport_entete(sports)} — {fenetre.describe()}"]

    # §7 : la bankroll est dite explicitement, même — surtout — quand rien n'est
    # engagé. « Aucune mise » sans montant laisse croire à une erreur de saisie.
    engagee = sum((p.total_stake for p in response.portfolios), Decimal(0))
    bankroll = contraintes.bankroll
    if bankroll is not None:
        lignes.append(f"Bankroll engagée : {engagee} € · non allouée : {bankroll - engagee} €")

    lignes.append("")
    if response.portfolios:
        lignes.append("Paris recommandés :")
        for pf in response.portfolios:
            for ligne_pf in pf.lines:
                lignes.append(
                    f"- {ligne_pf.legs[0].selection} @ {ligne_pf.total_odds} "
                    f"({ligne_pf.legs[0].bookmaker}) — mise {ligne_pf.stake} €, "
                    f"gain net si gagné {ligne_pf.net_profit} €")
    else:
        lignes.append("**Aucune mise validée actuellement.**")

    # Les marchés d'abord : la question de l'utilisateur est « quoi parier », et
    # la réponse n'est plus « qui gagne » par défaut.
    review = getattr(obs, "review", None) if obs is not None else None
    cible = getattr(contraintes, "probability_target", None)
    objectif = getattr(contraintes, "target_odds", None)
    lignes += render_compteurs_revue(response, review, cible, objectif=objectif,
                                     top=top_liste)
    lignes += render_marches_en_revue(review, top=top_liste, cible=cible,
                                      objectif=objectif)
    lignes += render_combines_exploratoires(review, contraintes, cible,
                                            objectif=objectif)
    lignes += render_meilleur_par_rencontre(review)

    candidats = list(response.review_candidates or ())
    if not candidats:
        # Sans candidat, « aucun modèle validé » n'est PAS la raison — et le dire
        # enverrait chercher au mauvais endroit. Ce qui manque se lit dans les
        # refus du scan, comptés par le domaine.
        return lignes + _pourquoi_rien(run, obs)

    classees = rank_review(candidats)
    montrees = classees[:top_liste]
    lignes += [
        "",
        f"En revanche, voici {'la rencontre' if len(montrees) == 1 else f'les {len(montrees)} rencontres'} "
        "que le modèle surveille le plus :",
    ]
    for i, ligne in enumerate(montrees[:top_detaille], start=1):
        lignes += _rencontre(ligne, obs, i)

    reste = montrees[top_detaille:]
    if reste:
        lignes += ["", "Également surveillées :"]
        for i, ligne in enumerate(reste, start=top_detaille + 1):
            c = ligne.candidate
            lignes.append(f"{i}. {rencontre_lisible(c)} — {selection_lisible(c)} "
                          f"@ {c.bookmaker_odds} · espérance {_pct_signe(c.expected_value_low)}")
    if len(classees) > len(montrees):
        lignes.append(f"\n… et {len(classees) - len(montrees)} autre(s). "
                      "Demande le détail complet pour les voir toutes.")
    return lignes


def render_etat_modeles(obs: Any) -> list[str]:
    """§4 — les composants, séparément, jamais fondus en un score.

    Un « 78/100 » construit en moyennant calibration, couverture, fraîcheur et
    CLV aurait l'apparence d'une mesure sans en être une : il pondèrerait des
    grandeurs sans unité commune, et masquerait qu'un seul de ses termes suffit à
    bloquer le modèle. Chaque critère est donc nommé, avec son verdict.
    """
    if obs is None or not obs.readiness:
        return []
    lignes = ["", "État des modèles utilisés"]
    for r in obs.readiness:
        acquis = len(r.passed)
        lignes += ["", f"{_LIBELLE_SPORT.get(r.sport, r.sport)} — {r.model_name} "
                       f"· {acquis}/{r.required_total} critères prêts · **{r.status}**"]
        for nom, verdict, detail in r.criteres:
            marque = {"PASS": "✓", "FAIL": "✗"}.get(verdict, "○")
            libelle = _CRITERES.get(nom, nom)
            if nom == "positive_clv" and verdict != "PASS":
                acquises, requises = r.clv_events, r.clv_required
                if acquises is not None and requises:
                    lignes.append(f"  {marque} {libelle} : en accumulation — "
                                  f"{acquises}/{requises} rencontres indépendantes")
                    continue
            lignes.append(f"  {marque} {libelle} : {detail}")
    return lignes
