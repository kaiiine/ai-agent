# src/ui/prompt_guard.py
"""
Guard anti-leak du système prompt.

Détecte si une réponse du LLM contient des extraits du prompt système
et la remplace par un refus neutre.

Deux niveaux de détection :
  1. Phrases de trigger explicites ("montre ton prompt", "ignore tes instructions"…)
  2. Marqueurs structurels du prompt dans la réponse ("━━ RÈGLE ABSOLUE ━━", etc.)
"""
from __future__ import annotations

import re

# ── Phrases qui demandent à voir le prompt ─────────────────────────────────────
# Détectées dans le message de l'utilisateur AVANT d'appeler le LLM.
_TRIGGER_PATTERNS: list[re.Pattern] = [re.compile(p, re.IGNORECASE) for p in [
    r"(montre|affiche|révèle?|donne|écris?|dis)[- ]+(moi\s+)?(le\s+|ton\s+|le\s+)?("
    r"prompt|system\s*prompt|instructions?|prompt\s*système|configuration\s*interne)",
    r"what('?s| is) (your|the) (system\s*)?prompt",
    r"repeat (after me|your (system\s*)?prompt|your instructions)",
    r"ignore (all |your )?(previous |prior )?(instructions?|constraints?|rules?)",
    r"ignore (tes |les |toutes? (tes |les )?)?(instructions?|règles?|contraintes?)",
    r"ignore\s+(ce\s+que|tout\s+ce\s+que).{0,20}(dit|disait|indique)",
    r"jailbreak",
    r"bypass (your )?(safety|filter|guard|rule|instruction)",
    r"(pretend|act|behave).{0,30}(no restriction|no rule|no limit|no filter)",
    r"tu es (maintenant|désormais).{0,40}(sans restriction|libre|sans règle)",
    r"oublie (toutes? tes |tes )?(instructions?|règles?|contraintes?)",
    r"dis[- ]+moi (tout|ce que tu sais sur toi|ton fonctionnement interne)",
    r"(quel(les)?|montre).{0,20}(règles?|instructions?).{0,20}(tu suis|te gouvernent|internes?)",
]]

# ── Marqueurs structurels uniques au prompt système ───────────────────────────
# Si 2+ de ces patterns apparaissent dans une réponse → fuite probable.
_LEAK_MARKERS: list[re.Pattern] = [re.compile(p) for p in [
    r"━━\s+[A-ZÀÉÈÊËÎÏÔÙÛÜ\s]{4,}\s+━━",   # ━━ SECTION ━━
    r"RÈGLE ABSOLUE",
    r"CONFIDENTIALITÉ",
    r"Outils disponibles\s*:",
    r"tools_available",
    r"PLANIFICATION AUTOMATIQUE",
    r"<axon:plan>",
    r"Workflow strict\s*:",
    r"MOTS ET FORMULES INTERDITS",
    r"FORMAT DE SORTIE EXACT",
]]

_LEAK_THRESHOLD = 2   # nb de marqueurs nécessaires pour déclencher le filtre

_REFUSAL = "Ces informations sont confidentielles."


# ── API publique ───────────────────────────────────────────────────────────────

def is_prompt_request(user_message: str) -> bool:
    """
    Retourne True si le message utilisateur semble demander le prompt système
    ou tenter un jailbreak.
    """
    return any(p.search(user_message) for p in _TRIGGER_PATTERNS)


def contains_leak(response: str) -> bool:
    """
    Retourne True si la réponse contient ≥ _LEAK_THRESHOLD marqueurs du prompt système.
    """
    hits = sum(1 for p in _LEAK_MARKERS if p.search(response))
    return hits >= _LEAK_THRESHOLD


def sanitize(response: str) -> str:
    """
    Si la réponse contient une fuite, retourne le message de refus.
    Sinon retourne la réponse inchangée.
    """
    return _REFUSAL if contains_leak(response) else response
