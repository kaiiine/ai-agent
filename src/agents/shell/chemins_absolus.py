"""Ce qu'on approuve doit être ce qui s'exécute.

Vécu : l'agent fait `shell_cd /tmp/axon-essai`, puis propose

    Commande DESTRUCTIVE :
    rm -rf ./*

`./` n'est écrit nulle part. Le même écran vaut pour un dossier d'essai et pour
la racine d'un projet, et l'accord porte sur ce qu'on lit. Ajouter « dans … » à
côté aide, mais laisse la commande dépendre d'un répertoire courant qui, lui,
peut avoir changé entre la proposition et l'exécution.

On réécrit donc les chemins en ABSOLU avant de poser la question. La commande
montrée est alors littéralement celle qui partira, et elle ne dépend plus de rien.

PRUDENCE, deux fois :

  · seules les commandes dont TOUS les arguments non-option sont des chemins
    sont réécrites. `git reset --hard HEAD~1` prend une référence, pas un
    fichier : y coller un préfixe la casserait ;
  · une commande enchaînée (`&&`, `|`, `;`, une substitution) est laissée
    intacte. Chaque morceau peut tourner ailleurs, et deviner lequel serait
    précisément le genre d'à-peu-près qu'on cherche à supprimer.

Ce qui n'est pas réécrit n'est pas exécuté à l'aveugle pour autant : la
confirmation montre alors le répertoire à côté de la commande.
"""
from __future__ import annotations

import shlex
from pathlib import Path

#: Commandes dont chaque argument non-option désigne un chemin.
_A_CHEMINS = frozenset({"rm", "rmdir", "shred", "truncate", "unlink"})

#: Ce qui enchaîne ou redirige : au-delà, on ne réécrit rien.
_ENCHAINEMENTS = ("&&", "||", ";", "|", ">", "<", "$(", "`", "\n")

#: Un argument déjà absolu, ou qui ne désigne pas un chemin.
_DEJA_SITUE = ("/", "~")


def absolutiser(commande: str, base: str | Path) -> str:
    """La même commande, ses chemins relatifs résolus depuis `base`.

    Rend la commande inchangée dès qu'un doute existe : mieux vaut une question
    accompagnée de son répertoire qu'une commande réécrite de travers.
    """
    if not commande.strip() or any(e in commande for e in _ENCHAINEMENTS):
        return commande
    try:
        mots = shlex.split(commande)
    except ValueError:                      # guillemet non fermé
        return commande
    if not mots or mots[0] not in _A_CHEMINS:
        return commande

    racine = Path(base)
    if not racine.is_absolute():
        return commande

    sortie = [mots[0]]
    for mot in mots[1:]:
        if mot.startswith("-") or mot.startswith(_DEJA_SITUE):
            sortie.append(mot)
            continue
        # `./x` et `x` désignent la même chose ; `.` et `..` se résolvent aussi,
        # mais sans `Path.resolve()` — il suit les liens symboliques, et effacer
        # la CIBLE d'un lien au lieu du lien serait une surprise de plus.
        relatif = mot[2:] if mot.startswith("./") else mot
        sortie.append(_remettre(f"{racine}/{relatif}" if relatif else str(racine)))
    return " ".join(sortie)


#: Ce qui fait d'un mot un motif : le shell doit pouvoir l'étendre.
_GLOB = set("*?[]")


def _remettre(mot: str) -> str:
    """Le mot tel qu'il doit repartir au shell.

    `shlex.split` a retiré les guillemets ; les remettre est indispensable dès
    qu'il y a une espace — sans quoi `rm -rf "mon dossier"` deviendrait DEUX
    chemins, et supprimerait ce qu'on ne lui demandait pas. Mais un glob doit
    rester nu, sinon le shell ne l'étend plus et la commande ne désigne rien.
    """
    if _GLOB & set(mot):
        return mot
    return shlex.quote(mot)
