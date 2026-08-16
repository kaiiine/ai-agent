"""Périmètre produit : ce qu'AXON ne peut pas évaluer, il doit le dire JUSTE.

Trois défauts constatés sur un PSG–Aston Villa (compétition européenne, absente
du référentiel — 8 championnats nationaux onboardés, zéro compétition européenne) :

  · le blocage était libellé « participants inconnus » alors que les DEUX
    participants étaient au référentiel ;
  · le conseil disait « re-scanner 24 h avant », alors que le temps ne résout
    pas un référentiel ;
  · un identifiant d'événement Premier League a été fabriqué pour un match du
    PSG — le PSG ne joue pas en Premier League.
"""

from __future__ import annotations

import pytest

from src.agents.quant.conversation.guard import enforce, identifiants_fabriques

# ── §1 — aucune identité fabriquée ──────────────────────────────────────────

#: Le texte réellement produit par AXON, mot pour mot.
_HALLUCINATION = (
    "Vérifier l'identifiant du match : assure-toi que le match figure bien dans "
    "le catalogue Winamax (ex. "
    "event:football:eng:premier_league:2026-08-13T20:45:00Z:home=psg|away=aston_villa)."
)


def test_un_identifiant_d_evenement_invente_est_bloque():
    verdict = enforce(_HALLUCINATION, None)

    assert not verdict.allowed
    assert verdict.reason == "FABRICATED_IDENTIFIER"


def test_l_identifiant_complet_est_rapporte_pas_un_fragment():
    """Un horodatage ISO contient `T` et `Z` : s'arrêter avant tronquait la
    preuve à `…:2026-08-13`, illisible pour qui veut vérifier."""
    inventes = identifiants_fabriques(_HALLUCINATION, None)

    assert len(inventes) == 1
    assert inventes[0].endswith("away=aston_villa")


def test_le_message_dit_quoi_faire_a_la_place():
    texte = enforce(_HALLUCINATION, None).replacement

    assert "que le scan courant n'a pas produites" in texte
    assert "pas fabriquer l'identifiant" in texte


@pytest.mark.parametrize("identite", [
    "competition:football:fra:ligue1",
    "competition:tennis:atp:tour",
    "team:football:fra:psg",
    "player:tennis:atp:sinner-j",
])
def test_les_identites_hors_evenement_ne_sont_jamais_bloquees(identite):
    """MESURÉ : couvrir `competition:`/`team:`/`player:` bloquait la sortie
    LÉGITIME du renderer (`competition:tennis:atp:tour`). Ces identités vivent
    dans des registres dispersés, sans source unique — une liste blanche
    incomplète censure du vrai. Un garde qui bloque le correct est pire que rien."""
    assert identifiants_fabriques(f"La référence {identite} est citée.", None) == []


def test_un_evenement_du_scan_courant_passe():
    """Les identités d'événement ne sont pas au référentiel : elles naissent du
    scan. Les refuser bloquerait toute réponse citant un vrai match."""
    class _Evidence:
        event_ids = ("event:football:fra:ligue1:2026-08-15T19:00:00Z:home=psg",)

    assert identifiants_fabriques(
        f"Match {_Evidence.event_ids[0]} évalué.", _Evidence()) == []


def test_un_evenement_absent_du_scan_est_refuse():
    class _Evidence:
        event_ids = ("event:football:fra:ligue1:2026-08-15T19:00:00Z:home=psg",)

    assert identifiants_fabriques(
        "Match event:football:ita:serie_a:2026-08-15T19:00:00Z:home=inter", _Evidence())


def test_le_garde_ne_voit_pas_une_competition_reelle_mal_appliquee():
    """Portée assumée : `competition:football:eng:premier_league` EXISTE. L'employer
    pour un match du PSG est une faute SÉMANTIQUE qu'aucun contrôle structurel ne
    peut voir. Ce sont les libellés et conseils corrigés qui suppriment
    l'incitation — pas ce garde."""
    assert identifiants_fabriques(
        "Précise competition:football:eng:premier_league pour ce PSG–Aston Villa.",
        None) == []


# ── §2 — le conseil suit le blocage réel ────────────────────────────────────

def test_les_libelles_de_refus_portent_leur_resolubilite():
    """Sans ce booléen, le conseil ne peut pas distinguer « attends » de
    « attendre n'y changera rien »."""
    from src.agents.quant.conversation.summary import _REFUS

    for code, valeur in _REFUS.items():
        assert isinstance(valeur, tuple) and len(valeur) == 2, code
        assert isinstance(valeur[1], bool), f"{code} : résolubilité manquante"


@pytest.mark.parametrize("code", [
    "COMPETITION_NOT_RESOLVED", "COMPETITION_NOT_COVERED",
    "SPORT_NOT_SUPPORTED", "EVENT_NOT_RESOLVED",
])
def test_un_blocage_structurel_n_est_jamais_resoluble_par_le_temps(code):
    from src.agents.quant.conversation.summary import _REFUS

    assert _REFUS[code][1] is False, f"{code} laisserait conseiller d'attendre"


def test_aucun_libelle_n_accuse_les_participants():
    """La cause n'est vérifiée nulle part à ce niveau : l'affirmer est un mensonge
    une fois sur deux."""
    from src.agents.quant.conversation.summary import _REFUS

    for code, (libelle, _) in _REFUS.items():
        assert "participants inconnus" not in libelle, code


# ── §20 — aucun test n'écrit dans les stores de production ──────────────────

def test_aucune_suite_de_tests_n_ecrit_dans_les_stores_de_production(tmp_path):
    """515 prédictions synthétiques ont atterri dans var/betting_engine/ parce
    qu'une capture était appelée en dur. L'invariant porte sur le DOSSIER, pas
    sur un fichier : le prochain store aurait la même faille."""
    import pathlib
    import subprocess
    import sys

    var = pathlib.Path("var/betting_engine")
    avant = {p.name: p.stat().st_size for p in var.glob("*") if p.is_file()} if var.exists() else {}

    subprocess.run(
        # Sans `-x` : s'arrêter au premier échec n'exercerait qu'une fraction des
        # suites, et l'invariant ne verrait pas la pollution venue des autres.
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
         "tests/test_summary_ux.py", "tests/test_betting_conversation_safety.py"],
        capture_output=True, timeout=600, check=False)

    apres = {p.name: p.stat().st_size for p in var.glob("*") if p.is_file()} if var.exists() else {}

    grossis = [n for n, t in apres.items() if t != avant.get(n, 0)]
    assert not grossis, f"la suite a écrit dans var/betting_engine/ : {grossis}"


def test_tout_appel_de_scan_dans_les_tests_neutralise_les_ecritures():
    """Garde statique, complémentaire : il échoue AVANT qu'une suite ne pollue,
    là où le test dynamique ne le voit qu'après coup."""
    import pathlib
    import re

    fautifs = []
    for fichier in sorted(pathlib.Path("tests").glob("*.py")):
        texte = fichier.read_text(encoding="utf-8")
        for appel in re.finditer(r"run_recommendation\((?:[^()]|\([^()]*\))*\)", texte):
            if any(n not in appel.group() for n in ("capture=None", "persist_audit=None", "coverage=None")):
                fautifs.append(f"{fichier.name}: {appel.group()[:60]}")

    assert not fautifs, "écrit dans les stores de production :\n" + "\n".join(fautifs)
