"""Un markdown, plusieurs destinations — analysé UNE fois.

Le modèle écrit toujours le même markdown. Un Google Doc, un mail, un message
Slack et une présentation le reçoivent différemment, et chacun a son dialecte :

    Docs    des requêtes `batchUpdate` avec styles et index
    mail    du HTML
    Slack   du mrkdwn (`*gras*`, jamais `**gras**`) ou des blocs Block Kit
    slides  des titres et des puces

Avant ce module, une seule de ces surfaces traduisait quoi que ce soit — le mail,
et sans les tableaux. Les Docs recevaient le markdown en CARACTÈRES : les dièses
et les astérisques s'affichaient. Slack s'en remettait à une consigne dans une
docstring.

Écrire quatre convertisseurs séparés recréerait quatre bugs différents. Il y a
donc un analyseur et des rendus : ce que l'un comprend, tous les autres le
rendent, et un défaut d'analyse se corrige une fois.

Le sous-ensemble couvert est celui d'un rapport réel — titres, paragraphes,
listes, tableaux, code, citations, règles — pas la spécification CommonMark.
Ce qui n'est pas reconnu reste du texte, jamais une erreur.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field


# ── Modèle ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Fragment:
    """Un morceau de texte en ligne et ses marques."""
    texte: str
    gras: bool = False
    italique: bool = False
    code: bool = False
    lien: str = ""


@dataclass(frozen=True)
class Bloc:
    """Un bloc de niveau paragraphe.

    `genre` ∈ titre · paragraphe · liste · numerotee · tableau · code · citation · regle
    """
    genre: str
    niveau: int = 0                                   # titre : 1..6
    lignes: tuple[str, ...] = ()                      # paragraphe, liste, citation, code
    rangees: tuple[tuple[str, ...], ...] = ()         # tableau, en-tête comprise
    langue: str = ""                                  # code


# ── Analyse en ligne ──────────────────────────────────────────────────────────

_CODE = re.compile(r"`([^`]+)`")

#: Les liens avant l'emphase, pour qu'un souligné dans une URL
#: (`https://x.fr/a_b_c`) ne devienne pas de l'italique.
_MARQUES = [
    ("lien",      re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")),
    ("gras",      re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")),
    ("italique",  re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])|(?<![\w_])_([^_\n]+)_(?![\w_])")),
]

#: Un caractère qui n'apparaît pas dans du texte écrit à la main.
_JETON = "\x00"
_MOTIF_JETON = re.compile(f"{_JETON}(\\d+){_JETON}")


def fragments(texte: str) -> tuple[Fragment, ...]:
    """Découpe une ligne en fragments marqués.

    Les codes littéraux sont MIS DE CÔTÉ avant l'analyse de l'emphase, puis
    restitués. Traiter le code en premier dans la même passe protégeait bien un
    `**` écrit dans du code, mais cassait l'inverse : dans « **gras et `code`** »,
    l'extraction du code coupait la paire d'astérisques en deux morceaux et le
    gras disparaissait. Mesuré, et c'est ce qui a motivé cette mise à l'écart.

    Une marque non fermée n'est pas une erreur — elle reste du texte, parce qu'un
    rapport à moitié écrit vaut mieux qu'une exception.
    """
    codes: list[str] = []

    def _mettre_de_cote(m: re.Match) -> str:
        codes.append(m.group(1))
        return f"{_JETON}{len(codes) - 1}{_JETON}"

    protege = _CODE.sub(_mettre_de_cote, texte or "")
    return tuple(f for brut in _emphase(protege, 0)
                 for f in _restituer(brut, codes))


def _emphase(texte: str, depuis: int) -> list[Fragment]:
    if not texte:
        return []
    for i in range(depuis, len(_MARQUES)):
        nom, motif = _MARQUES[i]
        m = motif.search(texte)
        if not m:
            continue
        avant, apres = texte[:m.start()], texte[m.end():]
        if nom == "lien":
            contenu, cible = m.group(1), m.group(2)
        else:
            contenu, cible = (m.group(1) or m.group(2) or ""), ""
        # Un lien peut contenir du gras ; on repart donc du même rang pour lui.
        interne = _emphase(contenu, i if nom == "lien" else i + 1)
        interne = [
            Fragment(f.texte,
                     gras=f.gras or nom == "gras",
                     italique=f.italique or nom == "italique",
                     code=f.code,
                     lien=f.lien or cible)
            for f in interne
        ]
        return _emphase(avant, i) + interne + _emphase(apres, i)
    return [Fragment(texte)]


def _restituer(fragment: Fragment, codes: list[str]) -> list[Fragment]:
    """Rend leurs codes aux fragments, en leur laissant les marques englobantes."""
    if _JETON not in fragment.texte:
        return [fragment] if fragment.texte else []
    sortie: list[Fragment] = []
    reste = fragment.texte
    while (m := _MOTIF_JETON.search(reste)):
        if (avant := reste[:m.start()]):
            sortie.append(Fragment(avant, fragment.gras, fragment.italique,
                                   False, fragment.lien))
        sortie.append(Fragment(codes[int(m.group(1))], fragment.gras,
                               fragment.italique, True, fragment.lien))
        reste = reste[m.end():]
    if reste:
        sortie.append(Fragment(reste, fragment.gras, fragment.italique,
                               False, fragment.lien))
    return sortie


# ── Analyse en blocs ──────────────────────────────────────────────────────────

_TITRE     = re.compile(r"^(#{1,6})\s+(.*)$")
_PUCE      = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMERO    = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_CITATION  = re.compile(r"^>\s?(.*)$")
_CLOTURE   = re.compile(r"^```\s*(\S*)\s*$")
_REGLE     = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")
_SEPARE    = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _cellules(ligne: str) -> tuple[str, ...]:
    brut = ligne.strip()
    if brut.startswith("|"):
        brut = brut[1:]
    if brut.endswith("|"):
        brut = brut[:-1]
    return tuple(c.strip() for c in brut.split("|"))


def analyser(md: str) -> tuple[Bloc, ...]:
    """Découpe un markdown en blocs. Ne lève jamais."""
    lignes = (md or "").replace("\r\n", "\n").split("\n")
    blocs: list[Bloc] = []
    i = 0
    while i < len(lignes):
        ligne = lignes[i]

        if not ligne.strip():
            i += 1
            continue

        if (m := _CLOTURE.match(ligne)):
            langue, corps = m.group(1), []
            i += 1
            while i < len(lignes) and not _CLOTURE.match(lignes[i]):
                corps.append(lignes[i])
                i += 1
            i += 1                                     # la clôture
            blocs.append(Bloc("code", lignes=tuple(corps), langue=langue))
            continue

        if _REGLE.match(ligne):
            blocs.append(Bloc("regle"))
            i += 1
            continue

        if (m := _TITRE.match(ligne)):
            blocs.append(Bloc("titre", niveau=len(m.group(1)), lignes=(m.group(2).strip(),)))
            i += 1
            continue

        # Tableau : une ligne de cellules SUIVIE d'un séparateur. Sans séparateur,
        # ce sont des pipes dans du texte, et il faut les laisser tranquilles.
        if "|" in ligne and i + 1 < len(lignes) and _SEPARE.match(lignes[i + 1]):
            rangees = [_cellules(ligne)]
            i += 2
            while i < len(lignes) and "|" in lignes[i] and lignes[i].strip():
                rangees.append(_cellules(lignes[i]))
                i += 1
            blocs.append(Bloc("tableau", rangees=tuple(rangees)))
            continue

        if _PUCE.match(ligne) or _NUMERO.match(ligne):
            numerotee = bool(_NUMERO.match(ligne))
            items: list[str] = []
            while i < len(lignes):
                mp, mn = _PUCE.match(lignes[i]), _NUMERO.match(lignes[i])
                if numerotee and mn:
                    items.append(mn.group(1).strip())
                elif not numerotee and mp:
                    items.append(mp.group(1).strip())
                else:
                    break
                i += 1
            blocs.append(Bloc("numerotee" if numerotee else "liste", lignes=tuple(items)))
            continue

        if (m := _CITATION.match(ligne)):
            corps = [m.group(1)]
            i += 1
            while i < len(lignes) and (m2 := _CITATION.match(lignes[i])):
                corps.append(m2.group(1))
                i += 1
            blocs.append(Bloc("citation", lignes=tuple(corps)))
            continue

        corps = [ligne.strip()]
        i += 1
        while i < len(lignes) and lignes[i].strip() and not (
            _TITRE.match(lignes[i]) or _PUCE.match(lignes[i]) or _NUMERO.match(lignes[i])
            or _CITATION.match(lignes[i]) or _CLOTURE.match(lignes[i])
            or _REGLE.match(lignes[i])
        ):
            corps.append(lignes[i].strip())
            i += 1
        blocs.append(Bloc("paragraphe", lignes=tuple(corps)))

    return tuple(blocs)


# ── Rendu : HTML (mail) ───────────────────────────────────────────────────────

def _html_fragments(texte: str) -> str:
    sortie = []
    for f in fragments(texte):
        t = _html.escape(f.texte)
        if f.code:
            t = f"<code>{t}</code>"
        if f.gras:
            t = f"<strong>{t}</strong>"
        if f.italique:
            t = f"<em>{t}</em>"
        if f.lien:
            t = f'<a href="{_html.escape(f.lien, quote=True)}">{t}</a>'
        sortie.append(t)
    return "".join(sortie)


#: Styles EN LIGNE, jamais une feuille `<style>`. Le gabarit de mail plaçait ses
#: règles dans une balise `<style>` à l'intérieur d'un `<td>` : Gmail l'accepte
#: aujourd'hui, plusieurs clients dont Outlook l'ignorent, et une règle ignorée
#: rend le rapport nu sans que personne le sache. En ligne, ça tient partout.
_STYLE_MAIL = {
    "titre1":  "margin:0 0 12px;font-size:20px;line-height:1.3;color:#FF8700;font-weight:bold;",
    "titre2":  "margin:22px 0 10px;font-size:17px;line-height:1.35;color:#FF8700;font-weight:bold;",
    "titre3":  "margin:18px 0 8px;font-size:15px;line-height:1.4;color:#e0e0e0;font-weight:bold;",
    "para":    "margin:0 0 14px;font-size:14px;line-height:1.8;color:#e0e0e0;",
    "liste":   "margin:0 0 14px;padding-left:22px;font-size:14px;line-height:1.8;color:#e0e0e0;",
    "item":    "margin:0 0 6px;",
    "citation":"margin:0 0 14px;padding:2px 0 2px 16px;border-left:3px solid #FF8700;color:#999999;font-size:14px;line-height:1.7;",
    "pre":     "margin:0 0 14px;padding:12px 16px;background:#222222;border-left:3px solid #FF8700;color:#e0e0e0;font-family:'Courier New',Courier,monospace;font-size:13px;line-height:1.5;overflow:auto;white-space:pre-wrap;",
    "regle":   "border:0;border-top:1px solid #2a2a2a;margin:22px 0;",
    "table":   "border-collapse:collapse;width:100%;margin:0 0 14px;font-size:13px;",
    "th":      "text-align:left;padding:7px 10px;border-bottom:2px solid #FF8700;color:#FF8700;font-weight:bold;",
    "td":      "text-align:left;padding:7px 10px;border-bottom:1px solid #2a2a2a;color:#e0e0e0;",
}


def en_html(md: str) -> str:
    """Rend le corps d'un mail. Tout est en style en ligne, tableaux compris."""
    s = _STYLE_MAIL
    out: list[str] = []
    for b in analyser(md):
        if b.genre == "titre":
            cle = "titre1" if b.niveau == 1 else "titre2" if b.niveau == 2 else "titre3"
            balise = f"h{min(b.niveau, 6)}"
            out.append(f'<{balise} style="{s[cle]}">{_html_fragments(b.lignes[0])}</{balise}>')
        elif b.genre == "paragraphe":
            corps = "<br>".join(_html_fragments(l) for l in b.lignes)
            out.append(f'<p style="{s["para"]}">{corps}</p>')
        elif b.genre in ("liste", "numerotee"):
            balise = "ol" if b.genre == "numerotee" else "ul"
            items = "".join(
                f'<li style="{s["item"]}">{_html_fragments(l)}</li>' for l in b.lignes)
            out.append(f'<{balise} style="{s["liste"]}">{items}</{balise}>')
        elif b.genre == "citation":
            corps = "<br>".join(_html_fragments(l) for l in b.lignes)
            out.append(f'<blockquote style="{s["citation"]}">{corps}</blockquote>')
        elif b.genre == "code":
            out.append(f'<pre style="{s["pre"]}">{_html.escape(chr(10).join(b.lignes))}</pre>')
        elif b.genre == "regle":
            out.append(f'<hr style="{s["regle"]}">')
        elif b.genre == "tableau":
            entete, *corps = b.rangees
            th = "".join(f'<th style="{s["th"]}">{_html_fragments(c)}</th>' for c in entete)
            trs = "".join(
                "<tr>" + "".join(f'<td style="{s["td"]}">{_html_fragments(c)}</td>'
                                 for c in rang) + "</tr>"
                for rang in corps
            )
            out.append(
                f'<table style="{s["table"]}" cellpadding="0" cellspacing="0">'
                f"<thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>")
    return "\n".join(out)


# ── Rendu : texte brut (version alternative du mail) ──────────────────────────

def en_texte(md: str) -> str:
    """La version texte d'un mail : lisible, sans marques de balisage.

    Elle compte : un client en mode texte, ou un lecteur d'écran, ne voit que
    celle-là. Rendre le markdown brut ici serait le défaut d'origine, déplacé.
    """
    def plat(t: str) -> str:
        return "".join(f.texte for f in fragments(t))

    out: list[str] = []
    for b in analyser(md):
        if b.genre == "titre":
            titre = plat(b.lignes[0])
            out.append(titre.upper() if b.niveau == 1 else titre)
            out.append("=" * len(titre) if b.niveau == 1 else "-" * len(titre))
        elif b.genre == "paragraphe":
            out.append(" ".join(plat(l) for l in b.lignes))
        elif b.genre == "liste":
            out += [f"  • {plat(l)}" for l in b.lignes]
        elif b.genre == "numerotee":
            out += [f"  {i}. {plat(l)}" for i, l in enumerate(b.lignes, 1)]
        elif b.genre == "citation":
            out += [f"  | {plat(l)}" for l in b.lignes]
        elif b.genre == "code":
            out += [f"    {l}" for l in b.lignes]
        elif b.genre == "regle":
            out.append("—" * 40)
        elif b.genre == "tableau":
            larg = [max(len(plat(r[c])) if c < len(r) else 0 for r in b.rangees)
                    for c in range(max(len(r) for r in b.rangees))]
            for n, rang in enumerate(b.rangees):
                cells = [plat(rang[c]).ljust(larg[c]) if c < len(rang) else " " * larg[c]
                         for c in range(len(larg))]
                out.append("  " + "  ".join(cells).rstrip())
                if n == 0:
                    out.append("  " + "  ".join("-" * l for l in larg))
        out.append("")
    return "\n".join(out).strip()


# ── Rendu : Slack (Block Kit) ─────────────────────────────────────────────────

def _mrkdwn(texte: str) -> str:
    """Le dialecte de Slack, qui n'est pas le markdown standard.

    `*gras*` et non `**gras**`, `_italique_`, `<url|texte>` pour les liens. Rien
    ne convertissait avant : un rapport arrivait avec ses astérisques doubles et
    ses dièses en clair.
    """
    def echapper(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Les fragments voisins qui partagent leurs marques sont GROUPÉS avant d'être
    # entourés. Sans ça, « **gras avec `code`** » donnait `*gras avec **code*` :
    # deux astérisques collés au milieu, que Slack rend de travers. Mesuré.
    out: list[str] = []
    for f in fragments(texte):
        marques = (f.gras, f.italique, f.lien)
        morceau = f"`{echapper(f.texte)}`" if f.code else echapper(f.texte)
        if out and out[-1][0] == marques:
            out[-1] = (marques, out[-1][1] + morceau)
        else:
            out.append((marques, morceau))

    rendu = []
    for (gras, italique, lien), contenu in out:
        if gras:
            contenu = f"*{contenu}*"
        if italique:
            contenu = f"_{contenu}_"
        if lien:
            contenu = f"<{lien}|{contenu}>"
        rendu.append(contenu)
    return "".join(rendu)


_LIMITE_SECTION = 2900          # Slack refuse un texte de section > 3000 caractères


def _sections(texte: str) -> list[dict]:
    """Découpe un texte long en plusieurs sections plutôt que de se faire rejeter."""
    morceaux, courant = [], ""
    for ligne in texte.split("\n"):
        if len(courant) + len(ligne) + 1 > _LIMITE_SECTION and courant:
            morceaux.append(courant)
            courant = ""
        courant += ligne + "\n"
    if courant.strip():
        morceaux.append(courant)
    return [{"type": "section", "text": {"type": "mrkdwn", "text": m.strip()}}
            for m in morceaux if m.strip()]


def en_blocs_slack(md: str) -> list[dict]:
    """Rend des blocs Block Kit — ce qui donne l'allure des messages soignés.

    Slack n'a pas de titres en mrkdwn : un `#` de niveau 1 ou 2 devient donc un
    bloc `header`, et un niveau 3 du gras. Et il n'a pas de tableaux : une
    grille devient un bloc de code à colonnes alignées, qui reste lisible là où
    des pipes bruts ne le sont pas.
    """
    blocs: list[dict] = []
    tampon: list[str] = []

    def vider():
        if tampon:
            blocs.extend(_sections("\n".join(tampon)))
            tampon.clear()

    for b in analyser(md):
        if b.genre == "titre" and b.niveau <= 2:
            vider()
            titre = "".join(f.texte for f in fragments(b.lignes[0]))
            blocs.append({"type": "header",
                          "text": {"type": "plain_text", "text": titre[:150], "emoji": True}})
        elif b.genre == "titre":
            tampon.append(f"*{''.join(f.texte for f in fragments(b.lignes[0]))}*")
        elif b.genre == "paragraphe":
            tampon.append("\n".join(_mrkdwn(l) for l in b.lignes))
        elif b.genre == "liste":
            tampon += [f"•  {_mrkdwn(l)}" for l in b.lignes]
        elif b.genre == "numerotee":
            tampon += [f"{i}.  {_mrkdwn(l)}" for i, l in enumerate(b.lignes, 1)]
        elif b.genre == "citation":
            tampon += [f"> {_mrkdwn(l)}" for l in b.lignes]
        elif b.genre == "code":
            tampon.append("```\n" + "\n".join(b.lignes) + "\n```")
        elif b.genre == "regle":
            vider()
            blocs.append({"type": "divider"})
        elif b.genre == "tableau":
            vider()
            plat = lambda t: "".join(f.texte for f in fragments(t))
            n_col = max(len(r) for r in b.rangees)
            larg = [max((len(plat(r[c])) if c < len(r) else 0) for r in b.rangees)
                    for c in range(n_col)]
            lignes = []
            for n, rang in enumerate(b.rangees):
                lignes.append("  ".join(
                    (plat(rang[c]) if c < len(rang) else "").ljust(larg[c])
                    for c in range(n_col)).rstrip())
                if n == 0:
                    lignes.append("  ".join("-" * l for l in larg))
            blocs.extend(_sections("```\n" + "\n".join(lignes) + "\n```"))
        if tampon and sum(len(t) for t in tampon) > _LIMITE_SECTION:
            vider()

    vider()
    return blocs[:50]           # Slack refuse au-delà de 50 blocs


# ── Rendu : Google Docs (requêtes batchUpdate) ────────────────────────────────

_TITRE_DOCS = {1: "HEADING_1", 2: "HEADING_2", 3: "HEADING_3",
               4: "HEADING_4", 5: "HEADING_5", 6: "HEADING_6"}


@dataclass
class RequetesDocs:
    """Ce qu'il faut envoyer à l'API Docs, et ce qu'il reste à faire ensuite.

    `requetes` s'envoie en un seul `batchUpdate`. `tableaux` liste les grilles
    dans l'ordre du document : leurs cellules ne peuvent PAS être remplies dans
    le même appel, parce que les index des cellules n'existent qu'une fois la
    table créée. L'appelant relit le document et appelle `requetes_cellules`.
    """
    requetes: list[dict] = field(default_factory=list)
    tableaux: list[tuple[tuple[str, ...], ...]] = field(default_factory=list)


def en_requetes_docs(md: str) -> RequetesDocs:
    """Traduit le markdown en requêtes de style Docs.

    Les requêtes sont construites en ordre INVERSE du document, chacune insérant
    à l'index 1. C'est ce qui rend le calcul d'index tenable : un `batchUpdate`
    applique ses requêtes en séquence, donc juste après avoir inséré un bloc à
    l'index 1, ce bloc occupe exactement [1, 1+len] et se style sans connaître
    le reste. L'insertion suivante le repousse plus bas, sans rien invalider.

    L'alternative — insérer dans l'ordre et suivre un curseur — oblige à
    recalculer chaque index après chaque requête, et se casse au premier bloc
    dont la longueur rendue diffère de la longueur écrite.
    """
    res = RequetesDocs()
    blocs = analyser(md)
    tableaux_ordre: list[tuple[tuple[str, ...], ...]] = []

    for b in reversed(blocs):
        if b.genre == "regle":
            res.requetes.append({"insertText": {"location": {"index": 1}, "text": "\n"}})
            res.requetes.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": 1, "endIndex": 2},
                    "paragraphStyle": {"borderBottom": {
                        "color": {"color": {"rgbColor": {"red": .8, "green": .8, "blue": .8}}},
                        "width": {"magnitude": 1, "unit": "PT"},
                        "padding": {"magnitude": 1, "unit": "PT"},
                        "dashStyle": "SOLID"}},
                    "fields": "borderBottom",
                }})
            continue

        if b.genre == "tableau":
            tableaux_ordre.append(b.rangees)
            res.requetes.append({"insertTable": {
                "location": {"index": 1},
                "rows": len(b.rangees),
                "columns": max(len(r) for r in b.rangees),
            }})
            continue

        if b.genre == "code":
            texte = "\n".join(b.lignes) + "\n"
            res.requetes.append({"insertText": {"location": {"index": 1}, "text": texte}})
            res.requetes.append({"updateTextStyle": {
                "range": {"startIndex": 1, "endIndex": 1 + len(texte)},
                "textStyle": {"weightedFontFamily": {"fontFamily": "Roboto Mono"}},
                "fields": "weightedFontFamily",
            }})
            continue

        # Titres, paragraphes, listes, citations : du texte et des marques.
        if b.genre == "titre":
            items = [b.lignes[0]]
        elif b.genre in ("liste", "numerotee"):
            items = list(b.lignes)
        elif b.genre == "citation":
            items = list(b.lignes)
        else:
            items = [" ".join(b.lignes)]

        # Le texte inséré est celui SANS ses marques — c'était le défaut d'origine,
        # et il s'était reproduit ici : insérer `item` brut mettait les astérisques
        # dans le document tout en calculant les plages de style sur le texte
        # nettoyé, donc doublement faux. Un test l'a rattrapé.
        decoupes = [fragments(item) for item in items]
        plats = ["".join(f.texte for f in fs) for fs in decoupes]

        texte = "".join(t + "\n" for t in plats)
        if not texte.strip():
            continue
        res.requetes.append({"insertText": {"location": {"index": 1}, "text": texte}})

        # Marques en ligne, décalées de leur position dans le bloc.
        base = 1
        for fs, plat in zip(decoupes, plats):
            pos = base
            for f in fs:
                n = len(f.texte)
                if n and (f.gras or f.italique or f.code or f.lien):
                    style: dict = {}
                    champs = []
                    if f.gras:
                        style["bold"] = True
                        champs.append("bold")
                    if f.italique:
                        style["italic"] = True
                        champs.append("italic")
                    if f.code:
                        style["weightedFontFamily"] = {"fontFamily": "Roboto Mono"}
                        champs.append("weightedFontFamily")
                    if f.lien:
                        style["link"] = {"url": f.lien}
                        champs.append("link")
                    res.requetes.append({"updateTextStyle": {
                        "range": {"startIndex": pos, "endIndex": pos + n},
                        "textStyle": style,
                        "fields": ",".join(champs),
                    }})
                pos += n
            base += len(plat) + 1

        fin = 1 + len(texte)
        if b.genre == "titre":
            res.requetes.append({"updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": fin},
                "paragraphStyle": {"namedStyleType": _TITRE_DOCS[min(b.niveau, 6)]},
                "fields": "namedStyleType",
            }})
        elif b.genre in ("liste", "numerotee"):
            res.requetes.append({"createParagraphBullets": {
                "range": {"startIndex": 1, "endIndex": fin},
                "bulletPreset": ("NUMBERED_DECIMAL_ALPHA_ROMAN" if b.genre == "numerotee"
                                 else "BULLET_DISC_CIRCLE_SQUARE"),
            }})
        elif b.genre == "citation":
            res.requetes.append({"updateParagraphStyle": {
                "range": {"startIndex": 1, "endIndex": fin},
                "paragraphStyle": {"indentStart": {"magnitude": 36, "unit": "PT"},
                                   "indentFirstLine": {"magnitude": 36, "unit": "PT"}},
                "fields": "indentStart,indentFirstLine",
            }})

    # Les requêtes sont en ordre inverse du document ; les tableaux, eux, doivent
    # être rendus dans l'ordre du document pour être remplis dans le bon ordre.
    res.tableaux = list(reversed(tableaux_ordre))
    return res


def requetes_cellules(document: dict,
                      tableaux: list[tuple[tuple[str, ...], ...]]) -> list[dict]:
    """Remplit les cellules des tableaux, une fois leurs index connus.

    Un `insertTable` crée la grille mais pas son contenu, et les index des
    cellules n'existent qu'après. On relit donc le document, on apparie les
    tables dans l'ordre, et on écrit à REBOURS — dernière cellule d'abord —
    parce qu'écrire dans une cellule décale toutes celles qui la suivent.
    """
    trouvees = [e["table"] for e in document.get("body", {}).get("content", [])
                if "table" in e]
    requetes: list[dict] = []
    for grille, table in zip(tableaux, trouvees):
        cibles = []
        for i, rang in enumerate(table.get("tableRows", [])):
            for j, cellule in enumerate(rang.get("tableCells", [])):
                if i < len(grille) and j < len(grille[i]):
                    brut = grille[i][j]
                    texte = "".join(f.texte for f in fragments(brut))
                    if texte:
                        cibles.append((cellule["startIndex"] + 1, texte, i == 0))
        for index, texte, entete in sorted(cibles, reverse=True):
            requetes.append({"insertText": {"location": {"index": index}, "text": texte}})
            if entete:
                requetes.append({"updateTextStyle": {
                    "range": {"startIndex": index, "endIndex": index + len(texte)},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }})
    return requetes
