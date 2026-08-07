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


def render_resume(run: Any, *, top_liste: int = TOP_LISTE,
                  top_detaille: int = TOP_DETAILLE) -> list[str]:
    """Le résumé lisible. Ne remplace pas le rendu technique — il le précède."""
    from .review_ranking import rank_review

    response, obs = run.response, run.observability
    contraintes = run.constraints
    fenetre = contraintes.time_window
    sports = list(obs.sports_in_window) if obs is not None else []

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
        lignes.append("Aucun pari n'est encore validé pour une mise réelle.")

    candidats = list(response.review_candidates or ())
    if not candidats:
        return lignes

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
