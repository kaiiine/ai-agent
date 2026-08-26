---
name: browser-driving
description: Drives an already-running Playwright browser session: accessibility snapshot, element references, click, type, fill, wait, console and network inspection. For operating a live site — logging in, submitting, reading a value that only exists after an action. Never for building or styling a site.
aliases: [navigateur, browser, playwright, snapshot, clique, cliquer, connecte-toi, se connecter, panier, onglet, naviguer, formulaire]
scope: orchestrator
---

━━ PILOTER UN NAVIGATEUR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

QUAND — ET SURTOUT QUAND PAS

`web_research_report` lit ce qui est indexé, et c'est presque toujours suffisant.
Le navigateur sert aux quatre cas qu'il ne couvre pas :

    un site derrière un login          une page rendue en JavaScript
    un formulaire à remplir            une valeur qui n'existe qu'après un clic

Pour « quel est le prix de X », commencer par la recherche. Ouvrir un navigateur
coûte plusieurs secondes et une session ; ce n'est pas un moteur de recherche.

LA BOUCLE, TOUJOURS LA MÊME

    browser_navigate     ouvrir l'URL
    browser_snapshot     LIRE la page — c'est ici qu'on obtient les références
    browser_click        agir, en désignant l'élément par sa référence
    browser_snapshot     vérifier que l'action a eu l'effet attendu

`browser_snapshot` rend l'arbre d'accessibilité, où chaque élément porte une
RÉFÉRENCE. Les actions se désignent par cette référence, jamais par un sélecteur
CSS deviné ni par des coordonnées. Une référence lue est exacte ; un sélecteur
inventé échoue silencieusement sur la moitié des sites.

NE JAMAIS AGIR SANS AVOIR LU

Enchaîner deux clics sans snapshot intermédiaire, c'est cliquer à l'aveugle sur
une page qui a changé. Après toute action qui navigue, soumet ou ouvre quelque
chose : re-snapshot avant l'action suivante.

Un `browser_take_screenshot` ne remplace pas un snapshot : il montre à l'humain,
il ne donne aucune référence cliquable.

CHERCHER DANS LA PAGE

Sur une page longue, `browser_find` cherche un texte ou un rôle dans le snapshot
sans tout ramener. Préférer `browser_find` à un snapshot complet suivi d'une
lecture au jugé.

REMPLIR UN FORMULAIRE

`browser_fill_form` remplit plusieurs champs en un appel — préférer à une suite
de `browser_type`, qui multiplie les allers-retours et les occasions de perdre
le focus. `browser_select_option` pour les listes déroulantes,
`browser_press_key` pour Entrée ou Échap.

ATTENDRE

`browser_wait_for` attend un TEXTE, pas une durée arbitraire. Attendre trois
secondes « au cas où » est un pari ; attendre l'apparition de « Commande
confirmée » est une vérification.

QUAND ÇA NE MARCHE PAS

    rien ne s'affiche          → browser_console_messages
    un bouton ne fait rien     → browser_network_requests, chercher un échec
    le contenu n'arrive jamais → browser_wait_for sur un texte attendu

Regarder AVANT de retenter. Recliquer sur un bouton qui n'a pas répondu ne le
fera pas répondre davantage.

CE QU'IL NE FAUT PAS FAIRE

`browser_run_code_unsafe` exécute du JavaScript arbitraire dans la page. Il
existe, il n'est presque jamais nécessaire, et il contourne tout ce que les
autres outils rendent lisible. Ne pas l'utiliser pour contourner un sélecteur
récalcitrant : re-snapshot et lire la vraie référence.

Ne jamais saisir un mot de passe, un numéro de carte ou un code reçu par SMS.
Si une page en demande un, s'arrêter et le dire à l'utilisateur — c'est à lui de
le faire, pas à un agent.

DIRE CE QU'ON A VU, PAS CE QU'ON SUPPOSE

Rapporter la valeur lue dans le snapshot, telle quelle. Si la page n'affiche pas
l'information cherchée, le dire — ne pas compléter avec ce qu'on croit savoir du
site. Une page mal lue et une page qui ne contient rien se ressemblent, et seule
la seconde justifie d'inventer.
