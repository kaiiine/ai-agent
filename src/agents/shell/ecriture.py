"""Reconnaître une écriture de fichier dans une commande, et dire QUOI y sera écrit.

`analyser_ecriture` rend une `Ecriture` ou None. La détection est structurelle —
une redirection est reconnue par sa forme, pas par ressemblance avec un exemple.

Trois informations en sortent, et chacune décide d'un traitement différent
dans `shell/tools.py` :

    cible / distante  → local, distant, ou modification sur place
    contenu           → None si illisible ; JAMAIS deviné
    composee          → l'opérateur qui enchaîne un AUTRE acte, s'il y en a un

Une commande composée est refusée : une confirmation ne peut porter que sur un
acte, et `echo x > /etc/motd && systemctl restart nginx` en porte deux.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Redirection vers un fichier. Exclut `2>&1`, `>&2` et `&>` : ce sont des
#: branchements de descripteurs, pas des écritures de fichier nommé.
_REDIRECTION = re.compile(r"(?<![0-9&<>])(>>?)(?!&)\s*([^\s;|&<>]+)")

#: Outils dont l'écriture est le métier, quelle que soit la redirection.
_OUTILS_ECRITURE = (
    (re.compile(r"(?<!\w)tee\s+(?:-\w+\s+)*([^\s;|&<>]+)"), "tee"),
    (re.compile(r"(?<!\w)sed\s+(?:-\w+\s+)*-i(?:\S*)?\b.*?([^\s;|&<>]+)\s*$"), "sed -i"),
    (re.compile(r"(?<!\w)dd\b[^|;]*?\bof=([^\s;|&<>]+)"), "dd"),
    (re.compile(r"(?i)(?<!\w)(?:Set-Content|Out-File|Add-Content)\s+(?:-\w+\s+)*([^\s;|&<>]+)"),
     "powershell"),
    (re.compile(r"(?<!\w)truncate\b[^|;]*?\s([^\s;|&<>]+)\s*$"), "truncate"),
)

#: `ssh [options] hôte <commande>`. Les options à valeur (-i, -p, -o, -F, -l)
#: sont consommées avec leur argument pour ne pas prendre la clé pour l'hôte.
_SSH = re.compile(
    r"^\s*ssh\s+((?:-[46AaCfGgKkMNnqsTtVvXxYy]+\s+|-[ioplFJbcDeLRWw]\s+\S+\s+)*)"
    r"([^\s-]\S*)\s+(.+)$", re.S)

#: `scp source hôte:cible` ou `rsync … hôte:cible`.
_COPIE_DISTANTE = re.compile(r"^\s*(scp|rsync)\b.*?\s([\w.@-]+):(\S+)\s*$", re.S)

#: Corps d'un heredoc : c'est là que vit le contenu, quand il y en a un.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1\s*\n(.*?)\n\s*\2\s*$", re.S)

#: `echo …` / `printf …` : le contenu est sur la ligne même.
_ECHO = re.compile(r"(?<!\w)(echo|printf)\s+(.*?)(?=\s*>>?[^&])", re.S)

#: Tout ce qui enchaîne un SECOND acte à l'écriture. Le tube en fait partie au
#: même titre que `&&` : mesuré, `rm -rf /tmp/cache | tee log.txt` ne contient
#: AUCUN opérateur de chaînage, et se lit pourtant « écrit log.txt ». Approuver
#: cette écriture lancerait le `rm`. Un tube seul suffit donc à cacher un acte
#: destructeur — le traiter à part rouvrirait le trou avec un autre séparateur.
_COMPOSEE = re.compile(r"\|\||&&|;|\|")


def _masquer_chaines(commande: str) -> str:
    """La commande avec le contenu des chaînes citées neutralisé.

    Un `>` entre guillemets est du texte, pas un opérateur. Les longueurs sont
    préservées : on cherche dans le masque, on découpe dans le texte réel.
    """
    sortie: list[str] = []
    quote: str | None = None
    echappe = False
    for c in commande:
        if echappe:
            sortie.append("\x00" if quote else c)
            echappe = False
            continue
        if c == "\\":
            echappe = True
            sortie.append(c)
            continue
        if quote:
            sortie.append(c if c == quote else "\x00")
            if c == quote:
                quote = None
            continue
        if c in ("'", '"'):
            quote = c
            sortie.append(c)
            continue
        sortie.append(c)
    return "".join(sortie)


def _masquer_heredoc(commande: str) -> str:
    """La commande avec le corps du heredoc neutralisé, longueurs préservées.

    Le corps n'est pas cité : un `;` ou un `|` dans le texte à écrire y reste
    visible et passerait pour un opérateur.
    """
    m = _HEREDOC.search(commande)
    if not m:
        return commande
    return commande[:m.start(3)] + "\x00" * len(m.group(3)) + commande[m.end(3):]


def operateur_de_composition(commande: str) -> str | None:
    """L'opérateur qui enchaîne un second acte, ou None.

    Cherché hors des chaînes citées et du corps de heredoc.
    """
    masque = _masquer_chaines(_masquer_heredoc(commande))
    trouve = _COMPOSEE.search(masque)
    return trouve.group(0) if trouve else None


@dataclass(frozen=True)
class Ecriture:
    """Une écriture repérée, et ce qu'on sait d'elle."""
    cible: str
    ajoute: bool                 # `>>` plutôt que `>`
    outil: str                   # redirection · tee · sed -i · dd · …
    distante: bool
    hote: str | None
    contenu: str | None          # None = indéterminable, JAMAIS deviné
    composee: str | None = None  # l'opérateur qui enchaîne un AUTRE acte

    @property
    def mode(self) -> str:
        return "ajout à la fin" if self.ajoute else "écrasement complet"

    def apercu(self, max_lignes: int = 40, max_chars: int = 4000) -> str:
        """Ce que l'utilisateur doit voir avant de confirmer.

        Montre le contenu quand il est déterminable ; le dit explicitement quand
        il ne l'est pas.
        """
        ou = f"{self.hote}:{self.cible}" if self.distante else self.cible
        entete = [f"Fichier   : {ou}", f"Mode      : {self.mode}",
                  f"Écrit par : {self.outil}"]
        if self.contenu is None:
            entete.append(
                "Contenu   : INDÉTERMINABLE depuis la commande (il vient d'une "
                "entrée standard, d'un tube ou d'un programme). Vérifie toi-même "
                "avant de confirmer.")
            return "\n".join(entete)
        lignes = self.contenu.splitlines()
        tronque = len(lignes) > max_lignes
        corps = "\n".join(lignes[:max_lignes])[:max_chars]
        entete.append(f"Contenu   : {len(lignes)} ligne(s)")
        bloc = [*entete, "", "─── contenu à écrire ───", corps]
        if tronque or len(self.contenu) > max_chars:
            bloc.append(f"… (tronqué, {len(lignes)} lignes au total)")
        return "\n".join(bloc)


def _hote_distant(commande: str) -> tuple[str, str] | None:
    """(hôte, commande exécutée à distance), ou None si tout est local."""
    m = _COPIE_DISTANTE.match(commande)
    if m:
        return m.group(2), commande
    m = _SSH.match(commande)
    if not m:
        return None
    hote, reste = m.group(2), m.group(3).strip()
    # Un hôte n'est pas une option ; une commande vide n'est qu'une connexion.
    if hote.startswith("-") or not reste:
        return None
    return hote, _deshabiller(reste)


def _deshabiller(fragment: str) -> str:
    """La commande distante, sans les guillemets qui l'enveloppent.

    S'arrête au guillemet fermant, pas à la fin du fragment : `ssh h "…" && rm`
    porte du texte après la commande distante.
    """
    fragment = fragment.strip()
    if not fragment or fragment[0] not in ('"', "'"):
        return fragment
    q, echappe = fragment[0], False
    for i, c in enumerate(fragment[1:], start=1):
        if echappe:
            echappe = False
        elif c == "\\":
            echappe = True
        elif c == q:
            return fragment[1:i]
    return fragment[1:]


def _contenu_de(commande: str) -> str | None:
    """Le contenu exact du fichier après écriture, ou None s'il ne se lit pas.

    Saut de ligne final inclus : `echo x > f` écrit `"x\\n"`. Un `printf` portant
    `%s` ou `\\n` est déclaré indéterminable plutôt que rendu littéralement —
    montrer une approximation comme si c'était le texte final serait pire.
    """
    m = _HEREDOC.search(commande)
    if m:
        return m.group(3) + "\n"
    m = _ECHO.search(commande)
    if m:
        verbe, brut = m.group(1), m.group(2).strip()
        for q in ('"', "'"):
            if len(brut) >= 2 and brut.startswith(q) and brut.endswith(q):
                brut = brut[1:-1]
                break
        if verbe == "printf":
            return None if ("%" in brut or "\\" in brut) else brut
        return brut + "\n"
    return None


def analyser_ecriture(commande: str) -> Ecriture | None:
    """L'écriture que cette commande effectue, ou None."""
    if not commande or not commande.strip():
        return None

    distant = _hote_distant(commande)
    hote, interne = (distant[0], distant[1]) if distant else (None, commande)

    # Les deux niveaux comptent : `ssh h "écrit && rm"` cache son chaînage dans
    # les guillemets, `ssh h "écrit" && rm` le porte à l'extérieur.
    compose = operateur_de_composition(commande) or operateur_de_composition(interne)

    # `scp`/`rsync` écrivent chez l'hôte sans redirection visible.
    m = _COPIE_DISTANTE.match(commande)
    if m:
        return Ecriture(cible=m.group(3), ajoute=False, outil=m.group(1),
                        distante=True, hote=m.group(2), contenu=None, composee=compose)

    masque = _masquer_chaines(interne)
    for motif, nom in _OUTILS_ECRITURE:
        trouve = motif.search(masque)
        if trouve:
            cible = interne[trouve.start(1):trouve.end(1)]
            return Ecriture(cible=cible, ajoute="-a" in interne,
                            outil=nom, distante=distant is not None, hote=hote,
                            contenu=_contenu_de(interne), composee=compose)

    redirection = _REDIRECTION.search(masque)
    if redirection:
        cible = interne[redirection.start(2):redirection.end(2)]
        # `> /dev/null` n'écrit rien qu'on veuille relire.
        if cible.startswith("/dev/"):
            return None
        return Ecriture(cible=cible, ajoute=redirection.group(1) == ">>",
                        outil="redirection", distante=distant is not None,
                        hote=hote, contenu=_contenu_de(interne), composee=compose)
    return None
