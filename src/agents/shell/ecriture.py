"""Reconnaître une écriture de fichier dans une commande, et dire QUOI y sera écrit.

L'ancienne détection était une liste de chaînes littérales — `"sed -i"`,
`"cat >"`, `"tee /"`, `"echo > /"`. Elle avait deux défauts opposés.

Elle bloquait TROP PEU : `printf 'x' > f`, `echo x > f` sans slash, `tee f`
sans slash, ou n'importe quel programme redirigé passaient tranquillement.
Mesuré — sur cinq façons d'écrire `~/.ssh/config` à travers `ssh`, une seule
était vue.

Et elle bloquait TROP, au mauvais endroit : `ssh hôte "cat > …"` était refusé
avec un message renvoyant vers `edit_file`, qui ne prend qu'un chemin LOCAL.
Pour un fichier distant, ce n'était pas une porte manquante mais une porte
impossible, et l'agent n'avait plus qu'à rendre un mode d'emploi.

Ce module sépare donc trois questions que la liste confondait :

    « est-ce une écriture ? »          → détection structurelle, pas lexicale
    « QUOI y sera écrit ? »            → décide de ce qu'on peut montrer
    « enchaîne-t-elle un autre acte ? » → décide si on peut demander l'accord

La troisième est arrivée en dernier et commande les deux autres. Une commande
composée porte un effet que la revue ne montre pas : `echo x > /etc/motd &&
systemctl restart nginx` se lit « écrit /etc/motd », et l'approuver redémarre
nginx. Elle est donc refusée, avec demande de découpage — découper nous-mêmes
demanderait un parseur shell, et un parseur approximatif sur des commandes qui
effacent des données est exactement la faute qu'on refuse.

Pour ce qui reste, le traitement suit ce qu'on est capable de MONTRER :

    contenu lisible, local  → un vrai diff, relu comme ceux d'`edit_file` ;
                              la commande n'est jamais exécutée
    contenu illisible       → la commande, la cible, le mode — et on DIT qu'on
                              ne sait pas le reste
    distant                 → confirmation, `edit_file` ne prenant qu'un chemin
                              local
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
    """La commande avec le CONTENU des chaînes citées neutralisé, longueurs
    préservées.

    Un `>` entre guillemets est du texte, pas un opérateur. Sans ce masquage,
    `echo "a > b"` passait pour une écriture vers `b"` — un faux positif qui
    BLOQUE une commande inoffensive en local et réclame une confirmation
    imaginaire à distance. Mesuré sur neuf tournures adversariales : trois
    étaient mal lues.

    Les longueurs sont conservées pour que les positions trouvées sur la version
    masquée désignent les mêmes caractères dans l'originale — on cherche donc
    dans le masque et on découpe dans le texte réel.
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
    """La commande avec le CORPS du heredoc neutralisé, longueurs préservées.

    Le corps n'est pas cité : un `;` ou un `|` DANS le texte à écrire y reste
    visible. Sans ce masquage, `cat > f <<EOF` suivi d'une ligne contenant un
    tube passerait pour une commande composée — et le meilleur cas de tous,
    celui où le contenu est intégralement lisible, serait refusé à tort.
    """
    m = _HEREDOC.search(commande)
    if not m:
        return commande
    return commande[:m.start(3)] + "\x00" * len(m.group(3)) + commande[m.end(3):]


def operateur_de_composition(commande: str) -> str | None:
    """L'opérateur qui enchaîne un second acte, ou None si la commande est simple.

    On cherche dans une version masquée deux fois : chaînes citées et corps de
    heredoc neutralisés. Un `|` littéral dans du texte à écrire n'enchaîne rien.
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
        """Ce que l'utilisateur doit voir AVANT de confirmer.

        Une confirmation qui n'affiche que la commande demande d'approuver un
        effet qu'on ne voit pas. Quand le contenu est déterminable, il est
        montré ; quand il ne l'est pas, on le DIT plutôt que de laisser croire
        que la commande a été comprise.
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

    On s'arrête au guillemet FERMANT, pas à la fin du fragment. Exiger que le
    fragment se termine par le guillemet rendait `ssh h "echo x > /f" && rm -rf
    /tmp` illisible : le fragment finissait par `p`, rien n'était déshabillé, le
    masquage neutralisait ensuite l'écriture citée, et la commande passait le
    garde SANS qu'aucune écriture ne soit vue — `rm` compris.
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
    """Le contenu EXACT du fichier après écriture, ou None s'il ne se lit pas.

    Le saut de ligne final compte : `echo x > f` écrit `"x\\n"`, pas `"x"`. Tant
    que ce texte ne servait qu'à un aperçu, l'écart était invisible ; il devient
    un diff faux dès lors qu'on le compare au fichier existant.

    `printf` porte des séquences que le shell interprète — `%s`, `\\n`, `\\t`. Les
    rendre littéralement afficherait un contenu qui n'est pas celui qui sera
    écrit. On préfère alors déclarer le contenu indéterminable : montrer une
    approximation en la présentant comme le texte final serait le seul vrai
    danger ici.
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
    """L'écriture que cette commande effectue, ou None si elle n'en fait aucune.

    La détection est STRUCTURELLE : une redirection est reconnue par sa forme,
    pas parce qu'elle ressemble à l'un des cinq exemples d'une liste. `printf`,
    `echo`, `cat`, un binaire quelconque ou un heredoc sont donc tous vus.
    """
    if not commande or not commande.strip():
        return None

    distant = _hote_distant(commande)
    hote, interne = (distant[0], distant[1]) if distant else (None, commande)

    # Les DEUX niveaux comptent : `ssh h "écrit && rm"` cache son chaînage dans
    # les guillemets, que `_masquer_chaines` neutralise sur la commande entière ;
    # `ssh h "écrit" && rm` le porte au niveau externe. Manquer l'un des deux
    # laisserait passer un acte non montré.
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
