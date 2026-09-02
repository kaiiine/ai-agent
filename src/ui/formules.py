"""Rendre les mathématiques lisibles dans un terminal.

Le modèle écrit du LaTeX correct — `\\(z\\)` en ligne, `\\[ … \\]` en bloc. C'est
`rich.Markdown` qui les défait : l'antislash y est une ÉCHAPPE, il disparaît, et
la délimitation avec lui. Reproduit :

    \\(\\in[0,1]\\)   devient   (\\in[0,1])
    \\[ \\frac{e^{z_i}}{\\sum_k e^{z_k}} \\]   devient   [ \\frac{e^{z_i}}{…} ]

L'utilisateur reçoit donc la source, sans même les repères qui disaient que
c'en était. On la traduit avant que Markdown y touche : Unicode pour ce qui a un
signe (Σ, ∈, ᵢ, ᴷ), une forme sobre pour le reste (`a / b`, `e^(x)`).

Traduire n'est pas composer. Un terminal n'empile pas une fraction ; le but est
qu'une formule se LISE, pas qu'elle ressemble à du papier.
"""
from __future__ import annotations

import re
import unicodedata

_EXPOSANT = str.maketrans(
    "0123456789+-=()abcdefghijklmnoprstuvwxyzABDEGHIJKLMNOPRTUVW",
    "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖʳˢᵗᵘᵛʷˣʸᶻᴬᴮᴰᴱᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾᴿᵀᵁⱽᵂ")

_INDICE = str.maketrans("0123456789+-=()aehijklmnoprstuvx",
                        "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢⱼₖₗₘₙₒₚᵣₛₜᵤᵥₓ")

#: Ce qui a un signe. Ce qui n'en a pas garde son nom, sans l'antislash.
_SIGNES = {
    "sum": "Σ", "prod": "∏", "int": "∫", "oint": "∮", "partial": "∂",
    "nabla": "∇", "infty": "∞", "sqrt": "√", "pm": "±", "mp": "∓",
    "times": "×", "div": "÷", "cdot": "·", "ast": "∗", "star": "⋆",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠",
    "ne": "≠", "approx": "≈", "sim": "∼", "equiv": "≡",
    "propto": "∝", "in": "∈", "notin": "∉", "subset": "⊂",
    "subseteq": "⊆", "cup": "∪", "cap": "∩", "emptyset": "∅",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    "to": "→", "rightarrow": "→", "leftarrow": "←",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "leftrightarrow": "↔",
    "mapsto": "↦", "implies": "⇒", "iff": "⇔",
    "dots": "…", "ldots": "…", "cdots": "…", "vdots": "⋮", "ddots": "⋱",
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "quad": "\u2003", "qquad": "\u2003\u2003", "ell": "ℓ", "hbar": "ℏ", "prime": "′",
    "langle": "⟨", "rangle": "⟩", "lVert": "‖", "rVert": "‖", "|": "‖",
    "{": "{", "}": "}", "%": "%", "&": "", "#": "#", "$": "$", "_": "_",
}

#: Décor de composition : ne se lit pas, ne se voit pas.
_DECOR = {"displaystyle", "textstyle", "limits", "nolimits", "left", "right",
          "big", "Big", "bigg", "Bigg", "!", ",", ";", ":", " "}

#: Une commande qui n'est qu'une police : son argument passe, elle non.
_POLICES = {"text", "textrm", "textbf", "textit", "mathrm", "mathbf", "mathit",
            "mathsf", "mathcal", "boldsymbol", "operatorname", "bm"}

_ACCENTS = {"hat": "̂", "bar": "̄", "overline": "̄",
            "vec": "⃗", "tilde": "̃", "dot": "̇",
            "ddot": "̈", "check": "̌"}

_ENSEMBLES = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "E": "𝔼",
              "P": "ℙ", "1": "𝟙"}

_COMPOSE = re.compile(r"[\s+\-−/·×=≤≥≠≈→⇒∈Σ∏∫]")


def _commande(expr: str, i: int) -> tuple[str, int]:
    """Le nom qui suit l'antislash : des lettres, ou un seul caractère."""
    j = i + 1
    while j < len(expr) and expr[j].isalpha():
        j += 1
    return (expr[i + 1:j], j) if j > i + 1 else (expr[i + 1:i + 2], i + 2)


def _groupe(expr: str, i: int) -> tuple[str, int]:
    """L'argument à la position `i` : `{…}` équilibré, une commande, ou un signe."""
    while i < len(expr) and expr[i] == " ":
        i += 1
    if i >= len(expr):
        return "", i
    if expr[i] != "{":
        if expr[i] == "\\":
            _, fin = _commande(expr, i)
            return expr[i:fin], fin
        return expr[i], i + 1
    profondeur, j = 1, i + 1
    while j < len(expr) and profondeur:
        profondeur += (expr[j] == "{") - (expr[j] == "}")
        j += 1
    return expr[i + 1:j - 1], j


#: Tout ce qui EST déjà un exposant ou un indice. Traduire ne suffit pas à
#: vérifier : `str.translate` laisse passer sans broncher ce qu'il ne connaît pas,
#: et `\\nabla_\\theta` sortait « ∇θ » — l'indice évaporé, la formule fausse.
_HISSES = {chr(c) for c in (*_EXPOSANT.values(), *_INDICE.values())}


def _hauteur(contenu: str, table: dict) -> str:
    """En exposant ou en indice si chaque signe en a un ; sinon à plat, marqué."""
    rendu = _convertir(contenu)
    hisse = rendu.translate(table)
    if hisse and all(c in _HISSES for c in hisse):
        return hisse
    marque = "^" if table is _EXPOSANT else "_"
    return f"{marque}{rendu}" if len(rendu) == 1 else f"{marque}({rendu})"


#: Ce qui suit une fraction sans la multiplier : une relation, une fermeture, un
#: écart, une fin de ligne.
_MULTIPLIE = re.compile(r"(?!$)(?![+\-=<>)\]},;])(?!\\(?:qquad|quad|right|end|\\|[,;:!]))")


def _terme(rendu: str) -> str:
    """Parenthèse un membre de fraction dès qu'il est composé."""
    return f"({rendu})" if _COMPOSE.search(rendu.strip()) else rendu


def _convertir(expr: str) -> str:
    sortie: list[str] = []
    i = 0
    while i < len(expr):
        caractere = expr[i]
        if caractere in "{}":
            i += 1
        elif caractere == "&":
            i += 1
        elif caractere in "^_":
            contenu, i = _groupe(expr, i + 1)
            sortie.append(_hauteur(contenu, _EXPOSANT if caractere == "^" else _INDICE))
        elif caractere != "\\":
            sortie.append(caractere)
            i += 1
        else:
            nom, i = _commande(expr, i)
            if nom == "\\":
                sortie.append("\n")
            elif nom in _DECOR:
                pass
            elif nom in _POLICES:
                contenu, i = _groupe(expr, i)
                sortie.append(_convertir(contenu))
            elif nom in _ACCENTS:
                contenu, i = _groupe(expr, i)
                sortie.append(_convertir(contenu) + _ACCENTS[nom])
            elif nom == "mathbb":
                contenu, i = _groupe(expr, i)
                sortie.append(_ENSEMBLES.get(contenu.strip(), contenu))
            elif nom in ("frac", "dfrac", "tfrac"):
                haut, i = _groupe(expr, i)
                bas, i = _groupe(expr, i)
                rendu = f"{_terme(_convertir(haut))} / {_terme(_convertir(bas))}"
                # Une barre horizontale sépare d'elle-même ; une barre oblique non.
                # `-\frac{1}{N}\sum …` rendu « -1 / NΣ… » se lit -1/(NΣ…), soit
                # l'inverse de ce qui était écrit. Ce qui suit la fraction la
                # MULTIPLIE : la parenthèse le dit.
                sortie.append(f"({rendu})" if _MULTIPLIE.match(expr[i:].lstrip()) else rendu)
            elif nom == "sqrt":
                if expr[i:i + 1] == "[":
                    fin = expr.find("]", i)
                    sortie.append(_convertir(expr[i + 1:fin]).translate(_EXPOSANT))
                    i = fin + 1
                contenu, i = _groupe(expr, i)
                sortie.append(f"√({_convertir(contenu)})")
            elif nom in ("begin", "end"):
                _, i = _groupe(expr, i)
            elif nom in _SIGNES:
                # TeX mange l'espace qui termine un nom de commande : dans
                # `\partial L` il sépare le nom du reste, il ne s'imprime pas.
                # On ne le mange que derrière un symbole — `\alpha x` reste deux
                # termes, `\log x` aussi.
                sortie.append(_SIGNES[nom])
                if not _SIGNES[nom].isalpha() and expr[i:i + 1] == " ":
                    i += 1
            else:
                # Un nom qu'on ne connaît pas est une fonction — `\log`, `\max`,
                # `\arg`. LaTeX les espace, nous aussi : « argmaxᵢ » n'est pas
                # ce qui était écrit.
                colle = nom.isalpha() and sortie and sortie[-1][-1:].isalnum()
                if nom.isalpha() and expr[i:i + 1] == "{":
                    argument, i = _groupe(expr, i)
                    nom += f"({_convertir(argument)})"
                sortie.append((" " if colle else "") + nom)
    return "".join(sortie)


#: Une relation respire des deux côtés ; un exposant collé au terme suivant ne se
#: lit plus (« Σₖ₌₁ᴷeᶻₖ »). L'espacement se pose ici, une seule fois, pour que rien
#: ne double.
_RELATIONS = "=≤≥≠≈∼≡∝∈∉⊂⊆→←⇒⇐↔↦⇔∧∨·"


def _propre(expr: str) -> str:
    rendu = unicodedata.normalize("NFC", _convertir(expr))
    rendu = re.sub(rf"\s*([{_RELATIONS}])\s*", r" \1 ", rendu)
    hisses = "".join(sorted(_HISSES))
    rendu = re.sub(rf"([{hisses}])(?![{hisses}])(?=[^\W_])", r"\1 ", rendu)
    rendu = re.sub(r"(?<=[0-9A-Za-z)])(?=[Σ∏∫∮])", " ", rendu)
    rendu = re.sub(r"\s+([,;.])", r"\1", rendu)
    return re.sub(r"[ \t]{2,}(?![ \t])", " ", rendu).strip()


def _bloc(trouve: re.Match) -> str:
    """Une formule hors ligne : barrée, pour que Markdown ne la reflue pas."""
    lignes = [l.strip() for l in _propre(trouve.group(1)).split("\n") if l.strip()]
    return "\n\n```\n" + "\n".join(lignes) + "\n```\n\n"


def _ligne(trouve: re.Match) -> str:
    return _propre(trouve.group(1))


#: `$…$` sur une seule ligne ne compte que s'il porte une marque de LaTeX : sans
#: cela « entre $5 et $10 » deviendrait une formule.
_DOLLAR_SEUL = re.compile(r"(?<!\$)\$([^$\n]*[\\^_{][^$\n]*)\$(?!\$)")
_DELIMITES = (
    (re.compile(r"\\\[(.+?)\\\]", re.S), _bloc),
    (re.compile(r"\$\$(.+?)\$\$", re.S), _bloc),
    (re.compile(r"\\\((.+?)\\\)", re.S), _ligne),
    (_DOLLAR_SEUL, _ligne),
)

_BARRIERE = re.compile(r"^\s*(?:```|~~~)")


def _segments(texte: str):
    """(barré, lignes) — ce qui est déjà dans un bloc de code n'est pas du texte.

    On rend des LIGNES, pas des morceaux recollés : un segment vide — un texte
    qui s'ouvre sur une barrière — ajouterait sinon une ligne vide à lui seul.
    """
    courant: list[str] = []
    dedans = False
    for ligne in texte.split("\n"):
        if _BARRIERE.match(ligne):
            if courant:
                yield dedans, courant
            courant, dedans = [ligne], not dedans
        else:
            courant.append(ligne)
    if courant:
        yield dedans, courant


def rendre_les_formules(texte: str) -> str:
    """Le même markdown, ses formules lisibles. Un bloc de code reste intact."""
    if not texte or ("\\" not in texte and "$" not in texte):
        return texte

    sortie: list[str] = []
    for barre, lignes in _segments(texte):
        morceau = "\n".join(lignes)
        if not barre:
            for motif, remplace in _DELIMITES:
                morceau = motif.sub(remplace, morceau)
        sortie.extend(morceau.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(sortie))
