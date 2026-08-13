"""Les manques historiques MESURÉS, sport par sport.

Ces chiffres ne sont pas des estimations : chacun vient d'un rejeu réel sur les
données d'AXON, daté du 2026-08-13. Ils vivent dans du code plutôt que dans une
configuration parce qu'ils sont des OBSERVATIONS — on les remplace en remesurant,
pas en les éditant.

Pourquoi les figer plutôt que les recalculer à chaque appel : un rejeu
walk-forward complet coûte plusieurs minutes par compétition, et une commande
d'audit qu'on n'ose pas lancer ne sert à rien. La date de mesure accompagne donc
chaque entrée, et c'est elle qui dit quand il faut recommencer.
"""

from __future__ import annotations

from .needs import HistoricalDataNeed

MESURE_LE = "2026-08-13"

#: Statut des chantiers historiques par sport. Un chantier CLOS ne se rouvre pas
#: pour grappiller quelques points : la mesure a montré ce qu'il en coûtait.
STATUTS = {
    "tennis:atp": {
        "statut": "CLOSED",
        "couverture": 0.9366,
        "min_data_coverage": "PASS",
        "note": "Les Futures ITF ne seront PAS ajoutés : 2 points de couverture "
                "de plus pour une dégradation de Brier six fois supérieure "
                "(ΔBrier +0.003083 contre +0.000539). Mesuré, pas supposé.",
    },
    "tennis:wta": {
        "statut": "PARTIAL",
        "couverture": 0.8545,
        "min_data_coverage": "FAIL",
        "blocker": "MISSING_RECENT_QUALIFYING_ITF_HISTORY",
        "classe": "DATA / EXTERNAL",
        "note": "Ne JAMAIS présenter le WTA comme historiquement complet. Le "
                "backfill Kaggle est conservé — il récupère 5 009 prédictions et "
                "améliore le Brier absolu — mais il ne justifie AUCUNE promotion "
                "de maturité. Le jeu s'arrête en 2021 et n'expose pratiquement "
                "aucune qualification : la recherche de source gratuite est close, "
                "faute de candidat récent, structuré et correctement licencié.",
    },
}


def besoins_mesures() -> tuple[HistoricalDataNeed, ...]:
    """Les manques observés sur les corpus réels d'AXON."""
    return (
        # ── tennis : le plus gros manque du système, et le plus bloqué ───────
        HistoricalDataNeed(
            sport="tennis", entity_type="player", entity_ids=("atp:*",),
            data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
            minimum_required_evidence=20, observed_evidence=20,
            competition_id="competition:tennis:atp:tour",
            detail={"predictions_perdues": 4485, "corpus": 70688,
                    "couverture_avant": 0.7740, "couverture_apres": 0.9366,
                    "comble_par": "sackmann_atp_fork",
                    "recuperees": 11494, "entites_sous_seuil": 0,
                    "residuel_2019_plus": 2552,
                    "cause": "le miroir sous licence s'arrête en 2018 ; les joueurs "
                             "apparus depuis n'ont toujours pas d'historique Challenger",
                    "mesure_le": MESURE_LE}),
        HistoricalDataNeed(
            sport="tennis", entity_type="player", entity_ids=("wta:*",),
            data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
            minimum_required_evidence=20, observed_evidence=17,
            competition_id="competition:tennis:wta:tour",
            detail={"predictions_perdues": 6806, "corpus": 46769,
                    "couverture_avant": 0.7474, "couverture": 0.8545,
                    "recuperees": 5009, "comble_partiellement_par": "kaggle_atp_wta",
                    "residuel_2022_2026": 2179, "entites_sous_seuil": 820,
                    "cause": "le dataset Kaggle sous licence n'expose NI qualifications "
                             "(1 seul tour Q sur 195 452) NI Challenger, et s'arrête en "
                             "2021 : il comble la profondeur pré-2007 mais laisse un "
                             "plancher d'environ 300 rencontres par an et tout 2022-2026",
                    "mesure_le": MESURE_LE}),
        # ── football : comblé, gardé pour la trace ───────────────────────────
        HistoricalDataNeed(
            sport="football", entity_type="team", entity_ids=("cl:*",),
            data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
            minimum_required_evidence=1, observed_evidence=1,
            competition_id="competition:football:eur:champions_league",
            detail={"predictions_perdues": 0, "couverture_avant": 0.8893,
                    "couverture_apres": 0.9395, "comble_par": "openfootball",
                    "mesure_le": MESURE_LE}),
        HistoricalDataNeed(
            sport="football", entity_type="team", entity_ids=("conf:*",),
            data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
            minimum_required_evidence=500, observed_evidence=495,
            competition_id="competition:football:eur:conference_league",
            detail={"predictions_perdues": 80, "couverture": 0.8609,
                    "cause": "compétition créée en 2021 : quatre saisons existent, "
                             "openfootball les fournit toutes",
                    "mesure_le": MESURE_LE}),
        # ── sports US : un seul est réellement sous le seuil ─────────────────
        HistoricalDataNeed(
            sport="american_football", entity_type="team", entity_ids=("nfl:*",),
            data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
            minimum_required_evidence=10, observed_evidence=10,
            competition_id="competition:american_football:usa:nfl",
            detail={"predictions_perdues": 0, "couverture_avant": 0.8986,
                    "couverture_apres": 0.9754, "comble_par": "nflverse",
                    "mesure_le": MESURE_LE}),
        HistoricalDataNeed(
            sport="volleyball", entity_type="team", entity_ids=("ita_a1:*",),
            data_type="matches", reason="INSUFFICIENT_DATA_no_prior_form",
            minimum_required_evidence=10, observed_evidence=9,
            competition_id="competition:volleyball:ita:superlega",
            detail={"predictions_perdues": 100, "couverture": 0.9036,
                    "entites_totales": 17,
                    "cause": "aucune archive libre de volley EN SALLE identifiée",
                    "mesure_le": MESURE_LE}),
    )


#: Sports mesurés SUFFISANTS — présents pour que « absent du rapport » ne se
#: confonde pas avec « pas encore regardé ».
COUVERTURE_SUFFISANTE = {
    "basketball": {"competition": "NBA", "couverture": 0.9696, "perdues": 168},
    "hockey": {"competition": "NHL", "couverture": 0.9753, "perdues": 186},
    "baseball": {"competition": "MLB", "couverture": 0.9845, "perdues": 174},
}
