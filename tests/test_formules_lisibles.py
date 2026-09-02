"""Une formule doit se lire, pas se déchiffrer.

Le modèle écrivait du LaTeX correct ; `rich.Markdown` prenait l'antislash pour une
échappe et le supprimait. L'utilisateur recevait la source privée de ses propres
repères :

    \\(\\in[0,1]\\)                    →  (\\in[0,1])
    \\[ \\frac{e^{z_i}}{\\sum …} \\]   →  [ \\frac{e^{z_i}}{\\sum …} ]

Reproduit exactement avant correction, sur `rich` seul.
"""
from __future__ import annotations

import pytest

from src.ui.formules import rendre_les_formules as rendre


def test_markdown_defaisait_les_delimiteurs():
    """La cause, pas le symptôme : elle tient en une ligne de `rich`."""
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console(width=80, file=__import__("io").StringIO())
    console.print(Markdown(r"probabilité \(\in[0,1]\)"))

    assert r"(\in[0,1])" in console.file.getvalue()


# ── les délimiteurs ───────────────────────────────────────────────────────────
def test_la_formule_en_ligne_reste_en_ligne():
    assert rendre(r"dimension \(K\) et \(z\).") == "dimension K et z."


@pytest.mark.parametrize("source", [r"\[ x^2 \]", r"$$x^2$$"])
def test_la_formule_en_bloc_est_barree(source):
    """Barrée, Markdown ne la reflue pas et n'y lit pas de gras."""
    rendu = rendre(source)

    assert "```\nx²\n```" in rendu


def test_un_prix_nest_pas_une_formule():
    """`$…$` sans marque de LaTeX reste du texte : « entre $5 et $10 »."""
    assert rendre("entre $5 et $10") == "entre $5 et $10"


def test_un_bloc_de_code_est_laisse_intact():
    source = '```python\na = r"\\frac{1}{2}"\n```'

    assert rendre(source) == source


def test_un_texte_sans_math_ne_bouge_pas():
    assert rendre("Bonjour, tout va bien.") == "Bonjour, tout va bien."


def test_un_texte_vide_ne_leve_pas():
    assert rendre("") == ""


# ── la traduction ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("latex, lisible", [
    (r"\sum_{k=1}^{K}",            "Σₖ₌₁ᴷ"),
    (r"z_i",                       "zᵢ"),
    (r"e^{-x}",                    "e⁻ˣ"),
    (r"x \in \mathbb{R}^d",        "x ∈ ℝᵈ"),
    (r"\|w\|_2 \leq \sqrt{n}",     "‖w‖₂ ≤ √(n)"),
    (r"\hat{y}",                   "ŷ"),
    (r"\text{softmax}(z)",         "softmax(z)"),
    (r"\alpha + \beta \neq \pi",   "α + β ≠ π"),
    (r"\frac{\partial L}{\partial w}", "∂L / ∂w"),
])
def test_ce_qui_a_un_signe_prend_son_signe(latex, lisible):
    assert rendre(rf"\({latex}\)") == lisible


def test_ce_qui_na_pas_de_signe_le_dit():
    """θ n'a pas de forme indicielle. `str.translate` le laissait passer muet —
    « ∇θ » — ce qui n'est pas la même formule que « ∇_θ »."""
    assert rendre(r"\(\nabla_\theta J\)") == "∇_θ J"


def test_une_fraction_composee_se_parenthese():
    assert rendre(r"\(\frac{1}{1+e^{-x}}\)") == "1 / (1+e⁻ˣ)"


def test_ce_qui_suit_une_fraction_la_multiplie():
    """« -1 / NΣ » se lit -1/(NΣ) — l'inverse de ce qui était écrit."""
    rendu = rendre(r"\(-\frac{1}{N}\sum_{n=1}^{N} x_n\)")

    assert rendu == "-(1 / N) Σₙ₌₁ᴺ xₙ"


def test_une_fraction_suivie_dune_relation_ne_se_parenthese_pas():
    assert rendre(r"\(\frac{a}{b} = c\)") == "a / b = c"


def test_un_exposant_ne_colle_pas_au_terme_suivant():
    """« Σₖ₌₁ᴷeᶻₖ » ne se lit plus."""
    assert "ᴷ e" in rendre(r"\(\sum_{k=1}^{K}e^{z_k}\)")


def test_une_fonction_garde_son_espace():
    """`\\arg\\max` est « arg max », pas « argmax »."""
    assert "arg max" in rendre(r"\(\arg\max_i p_i\)")


def test_lecart_voulu_survit_au_resserrement():
    """`\\qquad` est un écart de l'auteur, pas une espace en trop."""
    rendu = rendre(r"\[ x = 1 \qquad y = 2 \]")

    assert "\u2003" in rendu


def test_une_commande_inconnue_reste_lisible():
    """Ce qu'on ne sait pas traduire perd son antislash, pas son sens : une
    commande qui porte un argument est une fonction, elle l'appelle."""
    assert rendre(r"\(\zorglub{x}\)") == "zorglub(x)"
    assert rendre(r"\(\zorglub\)") == "zorglub"


# ── le chemin réel ────────────────────────────────────────────────────────────
def test_le_panneau_final_rend_la_formule():
    import io

    from rich.console import Console

    from src.ui.panels import final_panel

    console = Console(width=90, file=io.StringIO())
    console.print(final_panel(r"Sortie \(\in[0,1]\) sur \(K\) classes."))
    sortie = console.file.getvalue()

    assert "∈ [0,1]" in sortie
    assert "\\in" not in sortie
