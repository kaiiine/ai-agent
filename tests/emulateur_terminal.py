"""Un mini-terminal, pour assertionner sur ce qui est VISIBLE.

Chercher un mot dans les octets qu'une console Rich a produits ne prouve rien :
une région `Live` écrit son image puis la retire avec `ESC[A` et `ESC[2K`. Le
texte reste donc dans le tampon alors qu'il a disparu de l'écran, et un test qui
lit le tampon valide un affichage que personne ne voit.

Ce module rejoue le sous-ensemble de séquences que Rich émet — retour chariot,
saut de ligne, effacement de ligne, remontée de curseur — et rend l'écran final.

Il vivait dans `tests/test_zone_live.py`, supprimé avec la façade `ZoneLive`
qu'il servait à tester. L'émulateur, lui, n'avait rien à voir avec cette façade :
il vaut pour tout affichage Rich, et deux fichiers de tests s'en servent encore.
"""
from rich.console import Console


def _sortie(console: Console) -> str:
    """Les octets bruts écrits par la console — le flux, pas l'écran."""
    return console.file.getvalue()


def _ecran(console: Console) -> str:
    """Ce que l'utilisateur VOIT, après application des séquences de contrôle.

    Chercher un mot dans les octets bruts ne prouve rien : `transient=True` écrit
    l'image puis la retire avec `ESC[A` et `ESC[2K`. Le texte reste donc dans le
    tampon alors qu'il a disparu de l'écran. Ce mini-terminal rejoue le
    sous-ensemble que Rich émet — retour chariot, saut de ligne, effacement de
    ligne, remontée de curseur — pour qu'on assertionne sur l'écran et non sur
    le flux.
    """
    lignes, y, x = [""], 0, 0
    flux = _sortie(console)
    i = 0
    while i < len(flux):
        c = flux[i]
        if c == "\x1b" and flux[i + 1:i + 2] == "[":
            j = i + 2
            while j < len(flux) and not flux[j].isalpha():
                j += 1
            params, commande = flux[i + 2:j], flux[j:j + 1]
            if commande == "A":                      # curseur vers le haut
                y = max(0, y - int(params or 1))
            elif commande == "B":                    # curseur vers le bas
                y += int(params or 1)
            elif commande == "K":                    # effacer la ligne
                while len(lignes) <= y:
                    lignes.append("")
                lignes[y] = lignes[y][:x] if params == "0" else ""
            i = j + 1
            continue
        if c == "\n":
            y += 1
            x = 0
            while len(lignes) <= y:
                lignes.append("")
        elif c == "\r":
            x = 0
        else:
            while len(lignes) <= y:
                lignes.append("")
            ligne = lignes[y].ljust(x)
            lignes[y] = ligne[:x] + c + ligne[x + 1:]
            x += 1
        i += 1
    return "\n".join(lignes)
