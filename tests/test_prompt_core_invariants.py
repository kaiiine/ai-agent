"""Les cinq invariants d'action de `_CORE`, et ce qu'ils remplacent.

`_CORE` disait quels outils appeler, jamais quoi faire du RÉSULTAT. La boucle
existe pourtant en code — `graph.py` recâble `tools → chatbot`, et le
`ToolMessage` revient intact dans le contexte — mais rien n'indiquait au modèle
qu'une observation devait changer son approche. D'où le comportement observé :
répéter un appel qui vient d'échouer, ou demander à l'utilisateur ce qu'un outil
aurait rendu.

    UNDERSTAND   le résultat visé, pas l'action littérale
    GROUND       aucun identifiant, chemin ou état externe inventé
    ACT          la plus petite action réversible qui fait avancer
    ADAPT        ne retenter que sur information nouvelle
    ESCALATE     retrievable → retrieve it · user's call → ask

Deux choix mesurés en amont, dans le graph, et qui expliquent la forme du bloc :

  · la récupération d'erreur de `invocation.py` ne classe QUE des exceptions du
    LLM — `transient`, `rate_limit`, `context`, `unknown`. Un outil qui rend
    `{"status": "error"}` ou zéro résultat ne lève rien et n'atteint jamais ce
    code. Aucun contrôle programmatique ne couvre l'échec sémantique : ADAPT et
    ESCALATE portent seuls cette charge, sans risque de doubler le code ;
  · le `ToolMessage` revient tel quel. `_cap_tool_messages` ne tronque qu'au-delà
    de 3 000 caractères, et seulement sous compression — une erreur ou un « 0
    résultat » ne peut pas être perdu en chemin.

Ces tests portent sur la CONSTRUCTION du prompt. Les evals comportementales —
« face à cette observation, quelle action choisit Axon » — sont volontairement
hors de ce fichier : elles demandent un vrai modèle, plusieurs backends, et
c'est leur verdict qui compte, pas la stabilité du texte.
"""
from datetime import date

import pytest

from src.llm import prompts as module_prompts
from src.llm.prompts import _CORE, _GEMINI_FORMAT, build_system_prompt

#: Un jeu d'outils quelconque : `_CORE` est inconditionnel, il doit y être quoi
#: qu'on route.
_OUTILS = ["web_research_report", "local_read_file"]


def _assemble(outils=_OUTILS) -> str:
    return build_system_prompt(outils, date.today().isoformat(), "Kaine", lang="fr")


# ── Les cinq invariants ───────────────────────────────────────────────────────
@pytest.mark.parametrize("invariant", ["UNDERSTAND", "GROUND", "ACT", "ADAPT", "ESCALATE"])
def test_l_invariant_est_dans_le_prompt_assemble(invariant):
    """Assemblé, pas seulement défini : une section présente dans le module mais
    jamais ajoutée à `parts` ne sert à rien — c'est exactement ce qu'était
    `_OLD_CODING`."""
    assert invariant in _assemble()


def test_les_invariants_sont_inconditionnels():
    """Ils ne dépendent d'aucun outil : un tour sans outil du tout doit les
    porter, puisque c'est là que le modèle risque le plus de conclure seul."""
    nu = build_system_prompt([], date.today().isoformat(), "Kaine", lang="fr")

    for invariant in ("UNDERSTAND", "GROUND", "ACT", "ADAPT", "ESCALATE"):
        assert invariant in nu


def test_les_invariants_se_placent_entre_les_outils_et_le_plan():
    """L'ordre porte du sens : comment agir se lit après avoir su quels outils
    existent, et avant la règle qui décide s'il faut un plan."""
    p = _assemble()

    assert p.index("━━ TOOLS ━━") < p.index("━━ HOW TO ACT ━━") < p.index("━━ PLAN ━━")


# ── Ce que chaque invariant doit vraiment dire ────────────────────────────────
def test_adapt_pose_un_critere_informationnel_pas_un_seuil():
    """Un seuil chiffré serait arbitraire : `permission denied` ne mérite aucune
    seconde tentative, une recherche de fichier peut en mériter trois. Le
    critère juste est qu'une nouvelle tentative soit justifiée par une
    information nouvelle."""
    p = _assemble()

    assert "new information" in p
    assert "materially different" in p


def test_escalate_distingue_ce_qui_se_recupere_de_ce_qui_se_demande():
    """Sans cette distinction, « il manque une info » se traduit toujours par
    une question à l'utilisateur — y compris quand un outil l'aurait rendue."""
    p = _assemble()

    assert "retrieve it yourself" in p
    assert "→ ask" in p


def test_ground_couvre_les_identifiants_au_dela_du_mcp():
    """`_MCP` portait déjà cette garantie, mais seulement pour les outils
    `server__tool`. Le chemin absolu deviné en phase 2 d'un build n'était pas un
    outil MCP : `_CORE` étend la règle à tout identifiant, chemin compris.

    La redite avec `_MCP` est assumée — les deux portées diffèrent, et alléger
    `_MCP` avant d'avoir mesuré le filet général casserait une garantie qui
    fonctionne.
    """
    p = _assemble()

    assert "a path" in p
    assert "plausible-looking failure, never a result" in p


def test_axon_note_est_mentionne_dans_le_noyau():
    """`_MEMORY` reste conditionnel à l'outil `axon_note`. Sans mention dans
    `_CORE`, une découverte faite pendant un tour où l'outil n'est pas routé
    reste locale au tour, et le même blocage revient à la session suivante."""
    assert "axon_note" in _CORE


# ── Nettoyage ─────────────────────────────────────────────────────────────────
def test_old_coding_n_existe_plus():
    """Section jamais assemblée, 263 tokens, et elle enseignait
    `create_presentation` — un outil absent du registre."""
    assert not hasattr(module_prompts, "_OLD_CODING")

    from src.llm.prompts import orchestrateur

    assert not hasattr(orchestrateur, "_OLD_CODING")


def test_gemini_ne_contredit_plus_le_style_du_noyau():
    """`_CORE` demande des paragraphes, `_GEMINI_FORMAT` les interdisait au-delà
    de deux phrases. Les deux arrivaient ensemble sur backend Gemini."""
    assert "2 consecutive sentences" not in _GEMINI_FORMAT
    assert "otherwise use paragraphs" in _CORE


def test_gemini_garde_ses_regles_de_structure():
    """Seule la ligne contradictoire part : le reste ne contredit rien et sert
    encore sur un backend qui répond volontiers en prose plate."""
    for regle in ("## heading", "**key term**", "| table |", "```lang"):
        assert regle in _GEMINI_FORMAT


# ── Ce qui ne devait PAS bouger ───────────────────────────────────────────────
def test_skills_garde_sa_formulation_imperative():
    """À mesurer avant d'assouplir : on ignore si le routeur sémantique a la
    même granularité que `load_skill`. Tant que la mesure n'existe pas, le texte
    reste tel quel."""
    from src.llm.prompts import _SKILLS

    assert "MANDATORY FIRST STEP" in _SKILLS
    assert "UNCONDITIONAL" in _SKILLS


def test_study_n_a_pas_bouge():
    """Bloqué par un prérequis externe : `fiche.md` et `exo.md` déclarent
    `scope: template`, une portée qu'aucun agent ne lit, donc `load_skill` ne
    peut pas encore les servir."""
    from src.llm.prompts import _STUDY

    assert "Axon Slate Glass" in _STUDY


def test_le_reste_du_noyau_est_intact():
    """STYLE et PLAN n'étaient pas dans le périmètre.

    SAFETY, si : elle disait « Confirm before any irreversible action » et le
    modèle obéissait, en posant un questionnaire oui/non AVANT une suppression
    qu'AXON allait de toute façon faire confirmer. Deux questions pour un geste,
    dont la première ne décidait rien. La section reste, sa consigne a changé.
    """
    for marqueur in ("━━ STYLE ━━", "━━ PLAN ━━", "━━ SAFETY ━━",
                     "no filler openers", "<axon:plan>",
                     "AXON asks for consent ITSELF"):
        assert marqueur in _CORE

    assert "Confirm before any irreversible action" not in _CORE
