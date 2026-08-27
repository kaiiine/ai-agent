"""Lier 27 outils était au-dessus de toutes les limites publiées : OpenAI conseille
moins de 20 au début d'un tour, Anthropic 3 à 5 plus une recherche à la demande, et
mesure que différer AMÉLIORE la précision du choix (49 → 74 % sur Opus 4).

Le budget coupe donc dans le classement du groupe. Ce qui n'était qu'un ordre
devient une décision de liaison — et l'ordre venait d'une similarité dense qui ne
sépare pas les verbes d'une même famille : `calendar_delete_event` sortait avant
`calendar_create_event` sur « crée un événement ». Deux pièces réparent ça, et ces
tests les tiennent : le pont FR→EN, et les têtes de groupe déclarées.
"""
from __future__ import annotations

import pytest

from src.orchestrator.registry import build_all_tools
from src.orchestrator.tool_retriever import (
    _BUDGET_OUTILS, _PINNED_TOOLS, TOOL_GROUPS, ToolRetriever,
)


@pytest.fixture(scope="module")
def retriever():
    return ToolRetriever(build_all_tools())


@pytest.mark.parametrize("requete", [
    "envoie le recap dans le salon",
    "quels sont mes rendez-vous de demain",
    "y a-t-il de bons paris a faire ce soir",
    "Tu peux me schématiser comment fonctionne un rag en prod, pas en dev",
    "commit mes changements avec un message clair",
])
def test_le_budget_est_tenu(retriever, requete):
    assert len(retriever.get(requete)) <= _BUDGET_OUTILS, requete


def test_les_epingles_survivent_au_budget(retriever):
    """Ils sont épinglés parce qu'aucune requête ne les demande explicitement ;
    un budget qui les coupe les rend injoignables pour de bon."""
    noms = {t.name for t in retriever.get("y a-t-il de bons paris a faire ce soir")}
    assert _PINNED_TOOLS <= noms


def test_le_pont_place_le_verbe_en_tete(retriever):
    """« envoie » et « send » sont le même verbe ; sans le pont, l'embedding
    classait `slack_send_message` 6e de son groupe, derrière trois lectures."""
    ordre = retriever._tools_of("slack", "envoie le recap dans le salon")
    assert ordre[0] == "slack_send_message"


@pytest.mark.parametrize("groupe", [g for g, s in TOOL_GROUPS.items() if s.tete])
def test_une_tete_declaree_mene_toujours_son_groupe(retriever, groupe):
    """Une tête est un invariant métier, pas une préférence de classement : elle
    doit tenir quelle que soit la requête qui élit le groupe."""
    for requete in ("peu importe", "fais le maintenant", "et pour demain ?"):
        ordre = retriever._tools_of(groupe, requete)
        attendues = [t for t in TOOL_GROUPS[groupe].tete if t in TOOL_GROUPS[groupe].tools]
        assert ordre[:len(attendues)] == attendues, requete


def test_aucune_tete_ne_designe_un_outil_absent_de_son_groupe():
    for nom, spec in TOOL_GROUPS.items():
        assert set(spec.tete) <= set(spec.tools), nom


def test_le_tourniquet_ne_laisse_pas_un_groupe_tout_manger(retriever):
    """Sans tourniquet, le groupe de rang 1 remplit le budget et les intentions
    suivantes n'ont plus rien — le défaut déjà corrigé au niveau des clauses."""
    requete = "trouve la date du rdv dans mes mails et ajoute la au calendrier"
    noms = {t.name for t in retriever.get(requete)}
    assert any(n.startswith("gmail_") for n in noms), noms
    assert any(n.startswith("calendar_") for n in noms), noms


# ── familles d'intention dans un groupe ───────────────────────────────────────
def test_une_famille_visee_ecarte_le_reste_du_groupe(retriever):
    """`quant` est le groupe le plus lourd du registre : sur une demande de cotes
    il liait six outils pour 5 436 tokens, soit un tiers de l'entrée du tour.
    Demander les cotes n'appelle ni le calcul de probabilité ni l'analyse d'un
    combiné."""
    quant = set(TOOL_GROUPS["quant"].tools)
    lies = {t.name for t in retriever.get("donne moi les cotes du match PSG Marseille")} & quant
    assert "winamax_odds_fetch" in lies
    assert not lies & {"parlay_analyze", "same_match_combo_analyze"}, lies
    assert len(lies) < len(quant), lies


def test_la_tete_survit_au_filtre_par_famille(retriever):
    """Une demande de cotes reste une demande de pari : `betting_recommend` est
    l'unique chemin de recommandation et ne doit jamais disparaître du groupe."""
    lies = {t.name for t in retriever.get("donne moi les cotes du match PSG Marseille")}
    assert "betting_recommend" in lies


@pytest.mark.parametrize("groupe", [g for g, s in TOOL_GROUPS.items() if s.capabilities])
def test_les_familles_couvrent_exactement_le_groupe(groupe):
    """Un outil oublié d'une famille devient injoignable dès qu'une autre gagne."""
    spec = TOOL_GROUPS[groupe]
    dedans = {t for outils in spec.capabilities.values() for t in outils}
    assert dedans == set(spec.tools), dedans ^ set(spec.tools)


@pytest.mark.parametrize("groupe", [g for g, s in TOOL_GROUPS.items() if s.capabilities])
def test_aucune_famille_ne_partage_un_outil(groupe):
    spec = TOOL_GROUPS[groupe]
    vus: set[str] = set()
    for outils in spec.capabilities.values():
        assert not (vus & set(outils)), vus & set(outils)
        vus |= set(outils)


# ── mots-clés durs et souples ─────────────────────────────────────────────────
def test_un_mot_souple_ne_pose_pas_le_rang_1(retriever):
    """`prix` a fait la démonstration des deux côtés : 0 déclenchement juste pour
    2 faux sur les requêtes réelles — « si le prix change de plus de 1 % » est une
    surveillance —, mais « quel est le prix du Lenovo » a besoin de la recherche
    web. Un indice rend joignable, il ne décide pas."""
    from src.orchestrator.tool_retriever import _RANG_INDICE

    _, rangs = retriever._rank_groups_detaille(
        "Surveille le cours du Bitcoin et préviens-moi si le prix change de 1%")
    assert rangs.get("search", _RANG_INDICE) >= _RANG_INDICE
    assert rangs.get("cron") == 1


def test_un_mot_souple_rend_quand_meme_le_groupe_joignable(retriever):
    noms = {t.name for t in retriever.get("quel est le prix du Lenovo Legion 7i")}
    assert noms & set(TOOL_GROUPS["search"].tools), noms


def test_aucun_mot_nest_a_la_fois_dur_et_souple():
    for nom, spec in TOOL_GROUPS.items():
        assert not (spec.keywords & spec.soft_keywords), nom


def test_un_indice_nouvre_pas_un_groupe_a_seuil_strict():
    """Le rang d'un indice est délibérément sous les seuils : on n'entre pas dans
    le groupe le plus lourd du registre sur un mot qui a tort deux fois sur trois."""
    from src.orchestrator.tool_retriever import _RANG_INDICE

    quant = TOOL_GROUPS["quant"]
    assert quant.soft_keywords
    assert quant.requires_top_rank is not None
    assert _RANG_INDICE > quant.requires_top_rank
