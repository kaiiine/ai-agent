# Corpus de routage — agent de code

62 tâches réellement déléguées à `run_coding_agent`, extraites de
`~/.axon/memory.db`. C'est l'entrée EXACTE que reçoit `CodingToolRetriever` au
PREMIER tour : `retrieval_query` retombe sur la tâche tant qu'aucun message du
modèle n'existe. Aux tours suivants il route sur la sortie du modèle — ce qui ne
s'étiquette pas, sous peine de noter le système sur ses propres décisions.

## Ce qu'il faut faire

Remplir `attendu:` avec **le groupe d'outils qui aurait dû être lié** :

`filesystem`, `shell`, `git`, `web`, `memory`, `diagrams`, `assets`, `notebook`, `delegation`, `graphe`, `blender`, `playwright`, ou `aucun`.

`graphe` = les outils de graphe de projet (`graph_query`, `graph_affected`…),
qui répondent à « qu'est-ce qui appelle ceci », « qu'est-ce que ça casse ».
`delegation` = `deleguer`, pour confier une sous-tâche.

`aucun` = les 9 outils de flux toujours liés suffisaient
(plan, écriture de fichier, édition, clarification, skills).
`ambigu` = plusieurs groupes défendables ; la ligne sera écartée du calcul.

`fait:` est ce que le routeur rend AUJOURD'HUI. **Ce n'est pas la réponse** —
s'y fier reviendrait à noter le système sur lui-même.

## Deux réserves sur ce corpus

1. **39 % des tâches concernent Blender.** Un projet domine ; les conclusions
   qui en sortiront porteront cette empreinte. Et sur une tâche Blender le
   routeur lie le SERVEUR ENTIER — 28 outils d'un coup, plus les 9 de flux :
   l'étiquette `blender` y est presque toujours juste, donc peu informative.
   Les tâches non-Blender sont celles qui apprennent quelque chose.
2. **Ce ne sont pas tes mots.** `task` est rédigé par l'orchestrateur en
   reformulant ta demande — longueur médiane 536 caractères. C'est fidèle à ce
   que le routeur REÇOIT, mais ce n'est pas un corpus de formulations
   authentiques comme `CORPUS-ROUTAGE.md`.

Le partage réglage / tenu à l'écart est calculé par hachage, comme ailleurs :
rien à faire, il ne se voit pas ici.

---

> Crée un fichier Python `/home/kaine/Documents/projets-perso/ai-agent/stock_surveillance.py` qui : - Utilise yfinance pour récupérer les cours de ces actions : AAPL, MSFT, GOOGL, NVDA, META, AMD, TSLA, AMZN, JPM, BAC, COIN, MSTR, ^GSPC (S&P500), ^FCHI (CAC40) - Calcule la variation journalière en % -…

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, git, graphe, memory, shell

> Create a Blender Python script (compatible with Blender 3.6+) that: - Imports the provided SVG file (EPF_Projets_Logo.svg) as a mesh (convert curves to mesh). - Scales the logo to approximately 0.5 meters in its largest dimension. - Centers the logo at the origin. - Sets up an exterior environment: …

fait: blender
attendu: blender, git

> Dans le projet Blender contenant la scène déjà créée, ajouter du volume au logo SVG converti en mesh en appliquant une extrusion. Utiliser un Solidify Modifier (ou une extrusion via Edit Mode) avec une épaisseur d’environ 0.1 unité, appliquer le modificateur et mettre à jour le matériau d’émission. …

fait: assets, blender, diagrams, git, graphe
attendu: blender, git, graphe

> Re-generate the Blender scene for EPF Projets landing page, starting from the SVG logo at '/home/kaine/Documents/EPF Projets/Photo/EPF_Projets_Logo.svg'. After converting the SVG curves to a mesh, add a Solidify modifier (thickness 0.1) to give the logo volume, apply the modifier, then keep the emis…

fait: blender
attendu: blender, git, graphe

> Project: EPF Projets landing page. Create a Blender scene that imports the provided SVG file (EPF_Projets_Logo.svg). Convert the SVG curves to a mesh, extrude the geometry by a few centimeters (e.g., 0.05 m) to give it volume, orient the logo vertically (standing upright). Add a simple material (Pri…

fait: assets, blender
attendu: blender, git

> Créer une scène Blender contenant le logo SVG fourni (EPF_Projets_Logo.svg). Importer le SVG, le convertir en courbes, l'extruder d'environ 2 cm, le placer verticalement au centre de la scène, appliquer un matériau simple (ex. métal poli ou couleur corporate), ajouter une lumière d'appoint (HDRI ou …

fait: assets, blender, diagrams, graphe
attendu: blender, git

> Créer une scène Blender comprenant le logo SVG fourni (EPF_Projets_Logo.svg). Importer le SVG, le convertir en courbes, extruder les courbes de quelques centimètres pour donner du volume, orienter le logo verticalement (axe Z), placer le logo au centre de la scène, ajouter un matériau simple (ex: co…

fait: assets, blender, diagrams, filesystem, graphe
attendu: 

> Dans le dépôt du projet, créer une scène Blender qui utilise le fichier SVG fourni EPF_Projets_Logo.svg. Importer le SVG, le convertir en courbes, extruder les courbes de 0.05 m (5 cm) pour donner du volume, orienter le logo verticalement et le placer au centre de la scène. Ajouter un éclairage HDRI…

fait: assets, diagrams, filesystem, graphe
attendu: blender, graphe, git

> Créer dans le dépôt /home/kaine/Documents/projets-perso/ai-agent une scène Blender nommée logo_scene.blend. Importer le fichier EPF_Projets_Logo.svg (situé dans le même dossier), le convertir en courbes, l'extruder de 0.05 m, le faire pivoter pour qu'il soit vertical (axe Y). Placer le logo au centr…

fait: assets, diagrams, filesystem, graphe
attendu: blender, graphe, git

> Create a Blender scene in the current project. Write the provided SVG content to a file named EPF_Projets_Logo.svg in the repo root. In Blender: clear default objects, import the SVG as curves, convert to mesh, extrude the geometry by 0.05 meters along the local Z axis, ensure the object is centered…

fait: blender
attendu: graphe, git, blender

> Create a Blender scene in the repository at /home/kaine/Documents/projets-perso/ai-agent. Write the provided SVG content to a file named EPF_Projets_Logo.svg in the repo root. In Blender: delete any default objects, import EPF_Projets_Logo.svg as curves, convert the curves to a mesh, extrude the mes…

fait: assets, blender
attendu: blender, git, graphe

> Dans le projet situé à /home/kaine/Documents/projets-perso/ai-agent, ouvrir le fichier Blender existant (ou en créer un nouveau s'il n'existe pas) et: 1. Supprimer le cube par défaut s'il est présent. 2. Créer un sol représentant un glacier : un grand plan avec un matériau blanc/bleuté, légèrement b…

fait: assets, diagrams, filesystem, git, graphe
attendu: blender, graphe, filesystem, shell, assets

> In the existing Blender scene, replace the current igloo dome with a version built from individual brick-like segments (similar to a snow brick). Separate one brick on the side, offset it by a few centimeters from the main structure, and add a simple up‑down floating animation (e.g., sine wave) to t…

fait: blender
attendu: blender, assets, git, graphe

> Replace the current igloo with a brick-style igloo composed of small cube "snow bricks" (size ~0.4m). Arrange bricks in a rough hemispherical dome (about 4 rows high) using Python in Blender. Use the existing IceMaterial for all bricks. Then select one brick on the side, move it outward by ~0.08m fr…

fait: assets, blender
attendu: blender, assets, git, graphe

> Replace the current Igloo with a brick-based igloo built from a Sketchfab brick model (UUID 6e1362cd70304fd39abd7917a26e10fa). Steps: 1. Search Sketchfab for this ID, get preview, confirm it is downloadable. 2. Download the model into the Blender scene, target size ~0.4 m (largest dimension). 3. Del…

fait: blender
attendu: blender, git, graphe, assets

> Replace the existing igloo with a brick-based igloo built from the Sketchfab model UUID 6e1362cd70304fd39abd7917a26e10fa. Steps: 1. Search Sketchfab for this UUID, get a preview, and verify it is downloadable. 2. Download the model into Blender, scaling it so its largest dimension is about 0.4 m (a …

fait: blender
attendu: blender, git, graphe, assets

> In the repository /home/kaine/Documents/projets-perso/axon-landing, inside the newly created 'site' folder, scaffold a complete Next.js (v14) project using the installed dependencies (next, react, react-dom, tailwindcss, postcss, autoprefixer). Configure Tailwind CSS (tailwind.config.js, postcss.con…

fait: graphe, memory
attendu: filesystem, shell, graphe, memory, git, playwright

> Scaffold a Next.js (v14) project in /home/kaine/Documents/projets-perso/axon-landing/site. - Create next.config.js with experimental appDir disabled (use pages router). - Create tsconfig.json minimal for TypeScript. - Create tailwind.config.js and postcss.config.js using installed tailwindcss. - Add…

fait: graphe, memory, shell
attendu: filesystem, shell, graphe, memory, git, playwright

> Créer une landing page Next.js complète dans le répertoire /home/kaine/Documents/projets-perso/axon-landing/site selon la spécification spec.md. Le projet doit inclure : - Structure de dossiers (pages, components, public, styles) et configuration Next.js (package.json, next.config.js). - Implémentat…

fait: diagrams, filesystem, git, graphe, memory, shell
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create a Next.js (v14/app router) website for the Axon landing page in the repository /home/kaine/Documents/projets-perso/axon-landing. The site must be placed in a new directory parallel to spec.md (e.g., /home/kaine/Documents/projets-perso/axon-landing/site). Use the content from spec.md (provided…

fait: assets, graphe, memory, playwright, shell
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create a Next.js (v14 app router) landing page for Axon in /home/kaine/Documents/projets-perso/axon-landing/site. Include a package.json with dependencies: next@14, react@19, react-dom@19, tailwindcss@4, lucide-react, clsx, tailwind-merge, framer-motion, lenis, shadcn/ui, @radix-ui/react-slot. Add n…

fait: graphe, memory
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create a Next.js (v14) landing page for the Axon project using the specification located at /home/kaine/Documents/projets-perso/axon-landing/spec.md and the content from the ai-agent repository (/home/kaine/Documents/projets-perso/ai-agent). The new Next.js site must be placed in a folder parallel t…

fait: assets, blender, graphe, memory
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Crée un site Next.js dans le dossier `/home/kaine/Documents/projets-perso/axon-landing/axon-landing-page`. Le site doit être basé sur la spécification fournie dans `/home/kaine/Documents/projets-perso/axon-landing/spec.md` et utiliser les informations du dépôt `ai-agent` situé dans `/home/kaine/Docu…

fait: filesystem, git, memory, shell, web
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Continue la création du site Next.js dans `/home/kaine/Documents/projets-perso/axon-landing/axon-landing-page`. Termine l'intégration des composants principaux : terminal interactif (simulé), sections de features, parcours utilisateur, formulaire de contact, et mise en place du glassmorphism. Assure…

fait: git, graphe, memory, shell
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create a Next.js (v14) website in a new folder parallel to spec.md within /home/kaine/Documents/projets-perso/axon-landing. Folder name: nextjs-site. Use TypeScript, Tailwind CSS, and implement the design and content described in spec.md. Pull visual assets (banner.svg, any icons) from the ai-agent …

fait: assets, blender, diagrams, graphe, playwright, shell
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create a Next.js (v14) web site for the Axon landing page described in /home/kaine/Documents/projets-perso/axon-landing/spec.md. The site must be placed in a new folder named 'axon-landing-site' parallel to spec.md inside /home/kaine/Documents/projets-perso/axon-landing. Use the specification sectio…

fait: assets, graphe, memory, web
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Scaffold a Next.js 14 project with TypeScript and Tailwind CSS in the current directory. Include basic scripts (dev, build, start) and install dependencies: next, react, react-dom, tailwindcss, postcss, autoprefixer. Use npx create-next-app@latest with --ts flag and then add Tailwind following offic…

fait: graphe, notebook
attendu: filesystem, shell, graphe, memory, git, playwright, web

> In the existing Next.js 14 project at /home/kaine/Documents/projets-perso/axon-landing/axon-landing-site, complete the Axon landing page implementation according to the spec (spec.md). Steps: 1. Populate src/data with JSON files: features.json (array of feature objects with id, title, icon, descript…

fait: assets, blender, graphe, memory
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create the following data files in src/data of the Next.js project (axon-landing-site): - features.json : array of objects {id:string, title:string, icon:string (relative path to an SVG in public/assets/icons), description:string, category:'core'|'ai'|'ci'} with at least 5 sample features matching t…

fait: assets, graphe, memory
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create the data files (features.json, storySteps.json, team.json, llmBackends.json, roadmap.json) in src/data of the existing Next.js project at /home/kaine/Documents/projets-perso/axon-landing/axon-landing-site, with sample content matching the Axon spec. Ensure valid JSON and proper relative asset…

fait: assets, filesystem, graphe, memory
attendu: filesystem, shell, graphe, memory, git, playwright, web

> Create a file at /tmp/axon-essai/x.py with a simple Hello World Python script (e.g., print('Hello, world!')). Then delete the file /tmp/axon-essai/a.txt if it exists.

fait: blender, memory, shell
attendu: filesystem, shell, memory

> In the filesystem, ensure the directory /tmp/axon-essai exists. Create a file /tmp/axon-essai/x.py containing a simple Python hello world program (print('Hello, world!')). Then delete the file /tmp/axon-essai/a.txt if it exists, without raising an error.

fait: filesystem, memory, shell
attendu: filesystem, shell, memory

> Dans le répertoire /tmp/axon-essai, créer le fichier x.py contenant le code Python minimal qui imprime 'Hello, World!'. Ensuite, supprimer le fichier a.txt s'il existe.

fait: filesystem, shell, web
attendu: filesystem, shell, memory

> supprime le dossier temporaire du projet

fait: assets, filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Create a new file at /tmp/axon-essai/x.py containing a simple Python hello world program: ```python print('Hello, world!') ```

fait: blender, filesystem, memory, notebook, shell
attendu: filesystem, shell, memory

> Créer un script Python nommé /tmp/axon-essai/tri.py. Le script doit définir une fonction `trier_liste(liste)` qui renvoie la liste triée en ordre croissant. Il doit également contenir un bloc `if __name__ == "__main__":` qui crée une liste d'exemple, l'affiche avant et après appel à la fonction, et …

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, shell, memory

> Create a Python script at /tmp/axon-essai/tri.py. The script should define a function `tri_liste(liste)` that returns the sorted version of the input list using Python's built-in sorting. Include a `if __name__ == "__main__":` block that demonstrates the function with a sample list (e.g., [5, 2, 9, …

fait: blender, filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Créer le script Python /tmp/axon-essai/tri.py. Le script doit définir une fonction `trier_liste(liste)` qui retourne la liste triée en ordre croissant et, si le script est exécuté directement, lire une liste d'entiers depuis les arguments de ligne de commande, la trier et afficher le résultat. Utili…

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, shell, memory

> Create a Python script at /tmp/axon-essai/tri.py that defines a function to sort a list and includes a simple command-line interface: when run, it reads a space-separated list of numbers from command line arguments or stdin, sorts them, and prints the sorted list. Ensure the script is executable and…

fait: blender, filesystem, graphe, notebook, shell
attendu: filesystem, shell, memory

> Create the file /tmp/axon-essai/tri.py. The script should be executable, start with a shebang (#!/usr/bin/env python3), define a function sort_list(lst) that returns a sorted copy of the list, and provide a command-line interface: if arguments are given, treat them as numbers; otherwise read a line …

fait: blender, notebook, shell
attendu: filesystem, shell, memory

> Créer le fichier /tmp/axon-essai/tri.py contenant un script Python qui définit une fonction `tri_liste(liste)` triant une liste en place ou retournant une nouvelle liste triée, utilise la fonction `sorted` ou `list.sort`, inclut un bloc `if __name__ == "__main__":` pour démontrer le tri avec un exem…

fait: filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Créer le fichier /tmp/axon-essai/tri.py contenant un script Python simple qui définit une liste d'exemple, la trie en utilisant la fonction built‑in sorted() et affiche le résultat. Le script doit être exécutable directement (avec shebang) et inclure un commentaire d'en‑tête expliquant son but.

fait: filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Créer un script Python situé à /tmp/axon-essai/tri.py. Le script doit définir une fonction `tri_liste(liste)` qui renvoie la liste triée en ordre croissant, et lorsqu'il est exécuté directement, il doit lire une liste de nombres depuis les arguments de ligne de commande ou, à défaut, demander à l'ut…

fait: filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Créer un script Python nommé /tmp/axon-essai/tri.py. Le script doit définir une fonction `trier_liste(liste)` qui retourne la liste triée en ordre croissant. Inclure un bloc `if __name__ == "__main__":` qui lit une liste d'entiers depuis les arguments de la ligne de commande (séparés par des virgule…

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, shell, memory

> Créer le fichier /tmp/axon-essai/tri.py contenant un script Python qui reçoit une liste de nombres (ou de chaînes) depuis la ligne de commande, la trie en ordre croissant et affiche le résultat. Le script doit gérer les arguments séparés par des espaces, convertir chaque élément en entier si possibl…

fait: filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Créer un script Python nommé /tmp/axon-essai/tri.py. Le script doit définir une fonction `tri_liste(liste)` qui retourne une nouvelle liste triée en ordre croissant en utilisant `sorted`. Inclure un bloc `if __name__ == "__main__":` qui montre un exemple d'utilisation : créer une liste d'entiers dés…

fait: filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Modifier le script /tmp/axon-essai/tri.py afin qu'il demande à l'utilisateur d'entrer une suite de chiffres (un par ligne). L'utilisateur peut terminer la saisie en laissant la ligne vide ou en tapant 'done'. Le script doit alors convertir les entrées en nombres (int si possible, sinon float), trier…

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, shell, memory, graphe

> Créer un script Python à l'emplacement /tmp/axon-essai/tri.py. Le script doit contenir une fonction `trier_liste(liste)` qui renvoie la liste triée en ordre croissant et, lorsqu'il est exécuté directement, il doit démontrer son usage : lire une liste de nombres séparés par des espaces passée en argu…

fait: filesystem, git, graphe, memory, shell, web
attendu: filesystem, shell, memory

> Créer un script Python situé à /tmp/axon-essai/tri.py. Le script doit recevoir une liste d'entiers depuis la ligne de commande (séparés par des espaces) ou depuis l'entrée standard, trier la liste en ordre croissant et afficher le résultat. Utiliser la fonction sorted(). Inclure un bloc if __name__ …

fait: filesystem, graphe, memory, shell
attendu: filesystem, shell, memory

> Créer un script Python situé à /tmp/axon-essai/tri.py. Le script doit pouvoir être exécuté directement. Il doit définir une fonction `trier_liste(liste)` qui retourne la liste triée en utilisant `sorted`. Le script doit contenir une fonction `main()` qui lit une liste d'entiers depuis les arguments …

fait: filesystem, graphe, memory, shell
attendu: 

> Créer le fichier /tmp/axon-essai/tri.py contenant un script Python qui trie une liste. Le script doit accepter une liste de nombres fournie en argument de ligne de commande (ex. python tri.py 3 1 4 2) ou, si aucun argument n'est fourni, lire une ligne de texte depuis l'entrée standard contenant les …

fait: filesystem, graphe, memory, shell
attendu: filesystem, graphe, memory, shell

> Créer un script Python à l'emplacement /tmp/axon-essai/tri.py. Le script doit contenir une fonction `trier_liste(lst)` qui renvoie la liste triée en ordre croissant, et un bloc `if __name__ == "__main__":` qui lit une liste d'entiers depuis les arguments de ligne de commande, l'affiche avant et aprè…

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, graphe, memory, shell

> Améliorer le script /tmp/axon-essai/tri.py afin d'utiliser la bibliothèque Rich pour une interface console design. Conserver la fonction trier_liste(lst) qui renvoie la liste triée. Dans le bloc if __name__ == "__main__": - Utiliser Rich Console pour afficher un titre stylisé. - Lire les nombres dep…

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, graphe, memory, shell

> Dans le répertoire /tmp/axon-essai, créer les fichiers suivants : 1. tri.py – script Python qui utilise la bibliothèque Rich pour afficher un titre stylisé, demander à l'utilisateur, via une invite unique, d'entrer les nombres séparés par des espaces (ex. "5 2 9"). Le script doit parser les entrées,…

fait: filesystem, graphe, memory, shell
attendu: filesystem, graphe, memory, shell

> Créer un script Python nommé /tmp/axon-essai/tri.py. Le script doit accepter en argument une liste d'entiers ou de chaînes séparés par des espaces, trier la liste en ordre croissant et afficher le résultat. Gérer les erreurs d'argument et inclure une fonction `main()` avec un guard `if __name__ == "…

fait: filesystem, git, graphe, memory, shell
attendu: filesystem, graphe, memory, shell

> Écrire un script Python dans /tmp/axon-essai/tri.py qui trie une liste d'entiers fournie en argument de ligne de commande ou, à défaut, utilise une liste d'exemple [5,2,9,1,5,6]. Le script doit afficher la liste triée en ordre croissant. Inclure une fonction main() et un bloc if __name__ == '__main_…

fait: filesystem, graphe, memory, shell
attendu: filesystem, memory, shell

> Ouvrir le notebook /home/kaine/Documents/EPF/deep-learning/#1/TP1_executed.ipynb, identifier les cellules vides ou contenant uniquement des commentaires indiquant 'TODO' ou similaires, et les compléter selon les consignes de l'énoncé du notebook. Utiliser les bibliothèques déjà installées (numpy, sc…

fait: graphe, memory, notebook
attendu: notebook, filesystem, memory

> Exécuter le notebook Jupyter situé à /home/kaine/Documents/EPF/deep-learning/#1, remplir toutes les cellules vides, s'assurer que le .venv du dossier est utilisé, installer les dépendances nécessaires, sauvegarder le notebook avec les résultats.

fait: filesystem, graphe, memory, notebook, shell
attendu: notebook, filesystem, shell, memory

> Exécuter le notebook Jupyter TP1.ipynb situé dans /home/kaine/Documents/EPF/deep-learning/#1, compléter toutes les cellules vides, s'assurer qu'il s'exécute sans erreurs et enregistrer le notebook mis à jour.

fait: notebook
attendu: notebook, filesystem, shell, memory

> Dans le notebook TP1.ipynb du répertoire /home/kaine/Documents/EPF/deep-learning/#1, ajouter les cellules nécessaires pour implémenter un modèle Perceptron (sans bibliothèque high‑level), l’entraîner sur le dataset déjà chargé, afficher les métriques d’évaluation (précision, rappel, f1) et tracer la…

fait: graphe, memory, notebook
attendu: notebook, filesystem, memory

> Ajouter dans le notebook TP1.ipynb (chemin /home/kaine/Documents/EPF/deep-learning/#1) les cellules nécessaires pour implémenter un perceptron simple (sans utiliser de bibliothèque high‑level), l’entraîner sur le dataset déjà chargé, calculer précision, rappel, f1, tracer la frontière de décision, p…

fait: memory, notebook
attendu: notebook, filesystem, memory

> Dans le notebook TP1.ipynb (chemin /home/kaine/Documents/EPF/deep-learning/#1), corriger la classe Perceptron pour éviter l'erreur de dimensions. Implémenter la méthode fit en itérant sur les échantillons bruts (sans ajouter de biais manuellement dans la boucle) et mettre à jour les poids correcteme…

fait: filesystem, graphe, memory, notebook
**attendu**: notebook, filesystem, memory
