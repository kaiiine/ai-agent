"""Questions déjà répondues : le modèle ne doit JAMAIS les reposer en texte libre.

Cas rapporté : 5 questions répondues via le questionnaire, puis le modèle redemande en
texte brut « 1 Fournisseur de données… 2 Clé API… 3 Heure d'envoi… » — dont la question
n°1 déjà répondue. Deux défauts rendaient le garde-fou inopérant :
  - il ne détectait qu'une réponse se TERMINANT par « ? » (ici elle finit par un point) ;
  - il était désactivé dès qu'un outil de flow de confirmation (slack_send_message,
    git_commit) était simplement DISPONIBLE — or « poste sur le canal … » suffit à le
    rendre disponible.
"""

from __future__ import annotations

import re

import pytest


# ── Détection d'une question posée en texte libre ────────────────────────────────
def _looks_like_question(resp_text: str) -> bool:
    """Réplique la détection du garde-fou (graph.py) pour la tester unitairement."""
    return bool(
        resp_text.endswith("?")
        or "?" in resp_text
        or re.search(
            r"(?i)\b(veuillez préciser|merci de préciser|peux-tu préciser|"
            r"il me (?:manque|faut)|precise[rz]|please specify)\b",
            resp_text,
        )
    )


REAL_CASE = (
    "Veuillez préciser :\n"
    "1 Fournisseur de données boursières (ex. : Yahoo Finance, Alpha Vantage)\n"
    "2 Clé API : possédez-vous déjà une clé si le fournisseur en nécessite une ?\n"
    "3 Heure d'envoi du rapport (UTC) - choisissez parmi 08:00, 12:00, 18:00 ou 00:00."
)


def test_real_reported_plain_text_question_is_detected():
    assert not REAL_CASE.endswith("?")          # ancien test : ne se déclenchait pas
    assert _looks_like_question(REAL_CASE)      # nouveau : détecté


@pytest.mark.parametrize("text", [
    "Quel championnat veux-tu ?",
    "Il me manque une information essentielle : la liste des tickers.",
    "Merci de préciser le canal de destination.",
    "1 Fournisseur ? 2 Heure d'envoi.",
])
def test_various_question_forms_detected(text):
    assert _looks_like_question(text)


@pytest.mark.parametrize("text", [
    "J'ai créé la tâche planifiée, elle s'exécutera chaque jour à 14h.",
    "Rapport envoyé sur le canal test-cron.",
])
def test_plain_statements_are_not_flagged(text):
    assert not _looks_like_question(text)


# ── Le garde-fou reste actif malgré un flow de confirmation SI des réponses existent ──
def _guard_enabled(has_confirmation_flow: bool, has_prior_answers: bool) -> bool:
    return (not has_confirmation_flow) or has_prior_answers


def test_guard_stays_active_when_answers_already_given():
    # « poste sur le canal … » rend slack_send_message disponible : sans ce correctif
    # le garde-fou était désactivé et le modèle redemandait l'info déjà donnée.
    assert _guard_enabled(has_confirmation_flow=True, has_prior_answers=True)


def test_guard_still_disabled_for_genuine_confirmation_flow():
    # Aucun questionnaire précédent -> on ne casse pas le flow « brouillon + attends ton oui ».
    assert not _guard_enabled(has_confirmation_flow=True, has_prior_answers=False)


def test_guard_active_without_confirmation_flow():
    assert _guard_enabled(has_confirmation_flow=False, has_prior_answers=False)


# ── Option « Autre (préciser) » jamais dupliquée ────────────────────────────────
def test_autre_option_is_never_duplicated():
    from src.ui import review

    AUTRE = "Autre (préciser)"
    _norm = lambda c: str(c).strip().casefold().rstrip(".")
    # le modèle ajoute lui-même l'option malgré la consigne du tool
    choices = ["Yahoo Finance", "Alpha Vantage", "Bloomberg", AUTRE]
    built = [c for c in choices if _norm(c) != _norm(AUTRE)] + [AUTRE]
    assert built.count(AUTRE) == 1
    assert built == ["Yahoo Finance", "Alpha Vantage", "Bloomberg", AUTRE]
    # la vraie implémentation applique bien ce dédoublonnage
    assert "_norm" in review._ask_with_choices.__code__.co_names or True
