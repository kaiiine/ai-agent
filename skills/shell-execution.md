---
name: shell-execution
description: Operational rules for running shell commands safely — what to check before a destructive or service-altering command, how to recover from a failure instead of retrying blind, and when to stop and ask. Use when installing packages, managing services, or deleting files.
aliases: [shell, terminal, bash, commande, install, installe, installer, paquet, paquets, service, systemctl, sudo, redemarre, redémarre]
scope: coding
---

━━ EXÉCUTION SHELL ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ce skill n'enseigne NI la syntaxe shell, NI quel gestionnaire de paquets utiliser.
La syntaxe est connue ; la machine est décrite par le bloc MACHINE du prompt
système, détecté au démarrage. Ici on ne trouve que ce qui ne se déduit d'aucun
des deux : quoi faire avant d'agir, et quoi faire quand ça échoue.

LISTER AVANT DE SUPPRIMER :
   Avant tout `rm -r`, `rm -rf` ou suppression en masse, exécuter d'abord un
   `ls` ou un `find` sur la cible et MONTRER ce qui va disparaître. Un glob se
   relit ; il ne se devine pas. Ne jamais enchaîner une suppression derrière une
   étape qui a échoué ou dont le résultat est ambigu — la cible n'est alors pas
   celle qu'on croit.

NE JAMAIS RÉESSAYER UN SERVICE À L'AVEUGLE :
   Si un redémarrage échoue, ou si le service ne revient pas en bonne santé,
   LIRE LES LOGS avant de retenter (voir la ligne `services` du bloc MACHINE).
   Relancer sans avoir lu produit deux fois la même panne et zéro information.
   C'est le mode d'échec par défaut, celui qu'on cherche à supprimer.

PRÉFÉRER LES ESSAIS À BLANC :
   Quand l'outil en propose un, le passer d'abord — `rsync -n`, `pacman -Sp`,
   `git clean -n`, `terraform plan`. Obligatoire dès que l'opération touche plus
   d'un fichier ou d'une ressource.

NE JAMAIS S'ÉLEVER EN SILENCE :
   Si une commande exige `sudo` ou des droits d'administrateur, le DIRE et le
   justifier. Ne jamais préfixer `sudo` à une commande qui n'était pas clairement
   prévue pour en avoir besoin : l'utilisateur doit voir la différence entre une
   action dans son espace et une action sur son système.

« COMMAND NOT FOUND » = LE CONTEXTE EST PÉRIMÉ, PAS LE BINAIRE :
   C'est presque toujours le signe que la machine n'est pas celle qu'on croit —
   un conteneur Debian lancé depuis un hôte Arch, par exemple. La re-détection
   est AUTOMATIQUE : `shell_run` vide le contexte machine dès qu'une commande
   est introuvable, quel que soit le shell (exit 127, exit 9009, ou le texte de
   PowerShell). Il suffit donc de RELIRE le bloc MACHINE avant de retenter — il
   peut désigner un autre gestionnaire de paquets. Ne jamais deviner un autre
   nom de binaire au hasard : ici, deviner enchaîne les échecs.

DIRE POURQUOI ON A CHANGÉ D'APPROCHE :
   Quand une commande échoue et qu'on en tente une autre, expliquer ce que
   l'échec a appris — pas seulement ce qu'on relance. Une session future lit le
   « pourquoi » dans `.axon/memory/`, jamais la liste des commandes.

CE QUI EST DÉJÀ APPLIQUÉ, ET QU'IL EST INUTILE DE RÉPÉTER :
   `shell_run` exige lui-même une confirmation pour toute commande destructive,
   dans les trois vocabulaires : POSIX (`rm`, `dd`, `mkfs`, `shred`, retrait de
   paquets), PowerShell et cmd (`Remove-Item`, `del`, `rd`, `Format-Volume`,
   `diskpart`), et VCS (`git reset --hard`, `git clean -f`, `git push --force`).
   Il REFUSE purement les cibles catastrophiques — `/`, `~`, `.`, `*`, `C:\`,
   `$env:USERPROFILE` — quel que soit le verbe employé.
   Ces garde-fous sont du CODE, pas des consignes : ils ne dépendent ni de la
   lecture de ce fichier, ni de l'OS correctement détecté.

CE QUI NE VA PAS ICI :
   Tout ce qui ne se généralise pas — pilotage du ventilateur `msi-ec`, IPC
   Hyprland (`hyprctl`), particularités d'un paquet AUR — appartient à un skill
   étroit qui lui est propre. Si la tâche en relève, appeler `load_skill` une
   seconde fois : les skills se composent.
