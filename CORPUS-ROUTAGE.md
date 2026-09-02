# Corpus de routage — à relabelliser

Tes 274 requêtes réelles, extraites de `~/.axon/memory.db`. Ce sont tes
formulations authentiques : fautes de frappe, noms propres, tournures — ce
qu'aucun corpus inventé ne reproduit.

## Ce qu'il faut faire

Pour chaque ligne, remplir `attendu:` avec **le groupe qui aurait dû gagner**.

`fait:` indique ce qu'AXON a réellement appelé. **Ce n'est PAS la bonne réponse** —
c'est ce qu'un système au routage défaillant a produit. S'y fier reviendrait à
noter le système sur ses propres décisions, ce qui a déjà faussé une mesure.

Valeurs possibles pour `attendu:`

- un nom de groupe de la liste ci-dessous
- `aucun` — la requête ne nécessite aucun outil (le modèle répond seul)
- `ambigu` — plusieurs groupes défendables ; sera écarté du corpus

### Les groupes — `attendu:` prend UN de ces noms

| groupe | à choisir quand… | outils |
|---|---|---|
| `calendar` | consulter les rendez-vous et événements à venir d'une journée … | calendar_list_events, calendar_create_event, calendar_update_event +3 |
| `coding` | créer une application ou un site web à partir de rien — landin… | run_coding_agent |
| `cron` | faire quelque chose tous les jours, chaque matin, chaque semai… | schedule_task, surveiller, list_cron_tasks +1 |
| `desktop` | capturer l'écran pour voir ou analyser ce qui y est affiché, l… | screenshot_take, clipboard_read, clipboard_write |
| `diagrams` | architecture d'un système, flowchart, diagramme de séquence, e… | mermaid_diagram |
| `drive` | parcourir et lister les fichiers, retrouver l'identifiant d'un… | drive_list_files, drive_find_file_id, drive_read_file +5 |
| `filesystem` | retrouver un fichier par son nom ou un motif, lister le conten… | local_find_file, local_read_file, local_list_directory +4 |
| `git` | état de la copie de travail, modifications en cours non encore… | git_status, git_log, git_diff +5 |
| `gmail` | chercher des messages, résumer les mails reçus, rédiger et env… | gmail_search, gmail_summarize, gmail_send_email +3 |
| `google_slides` | créer le document chez Google, y ajouter des diapositives, le … | slides_create, slides_add_slide, slides_from_markdown |
| `jira` | tickets, issues, sprints, epics et projets | jira_get_my_issues, jira_get_issue, jira_search_issues +15 |
| `memory` | mémorise ceci, retiens cette préférence, note-le dans ta mémoi… | axon_note |
| `network` | nom du Wi-Fi, adresse IP, force du signal, latence de la conne… | wifi_info |
| `news` | ce qui s'est passé aujourd'hui ou hier, les dernières nouvelle… | web_search_news |
| `process` | lister ce qui tourne et ce qui consomme du CPU ou de la mémoir… | process_list, process_kill |
| `quant` | scanner les matchs disponibles aujourd'hui ou demain et propos… | betting_recommend, winamax_odds_fetch, sports_stats_fetch +4 |
| `search` | recherche approfondie avec sources et citations, se renseigner… | web_research_report, deep_research, url_fetch +2 |
| `sheets` | créer une feuille de calcul, y ajouter des lignes de données, … | sheets_create, sheets_append_rows, sheets_read |
| `shell` | exécuter une commande ou un script, lancer un build, une insta… | shell_run, shell_cd, shell_pwd +1 |
| `skills` | Charger la procédure écrite d'avance pour un savoir-faire part… | load_skill |
| `slack` | envoyer, poster ou publier un message, un récap ou un compte r… | slack_find_user, slack_list_channels, slack_read_channel +4 |
| `slides` | synthétiser un sujet en diapositives avec titre, puces, chiffr… | create_slides |
| `study` | produire depuis un cours ou un PDF une fiche de synthèse ou un… | save_study_file |
| `time` | quelle heure il est, quel jour on est, la date d'aujourd'hui, … | get_current_time |
| `translate` | comment dit-on ceci en anglais, en espagnol, en allemand, trad… | translator |
| `weather` | le temps qu'il fait et celui qu'il fera | get_weather_by_city |
| `aucun` | la requête ne nécessite aucun outil | — |
| `ambigu` | plusieurs groupes défendables — sera écarté | — |

---

## Requêtes autonomes (146)

Celles qui se suffisent à elles-mêmes. C'est le corpus qui compte.

### 1
> Surveille le cours du Bitcoin toutes les 2 minutes pendant 1h et notifie-moi sur Slack dans test-cron si le prix change de plus de 1%

fait: `schedule_task` → groupe `cron`
attendu: cron

### 2
> Surveille le cours du Bitcoin toutes les 2 minutes et notifie-moi sur Slack dans test-cron dès que le prix change de plus de 0.1%

fait: `stop_cron_task` → groupe `cron`
attendu: cron

### 3
> Peux tu me norifier sur mon pc a 15h40 que je dois appeler Nicolas stp

fait: `schedule_task` → groupe `cron`
attendu: cron

### 4
> Notifie moi aujourd'hui a 15h45 que je dois aller voir macopine sur mon pc stp

fait: `schedule_task` → groupe `cron`
attendu: cron

### 5
> Surveille moi le match de tennis Vaentova contre Joint (je suis pour Valentova) toutes les 5min et envoies une notif sur le canal test-cron

fait: `web_search_news` → groupe `news`
attendu: cron

### 6
> Peux tu envoyer un message a Nicolas Danquigny en lui expliquant ce qui est entrain de se passer sur le bitcoin en c moment, s'il faut investir ou non etc...

fait: `slack_find_user` → groupe `slack`
attendu: slack

### 7
> Tu peux envoyer le meme message a nicolas danquigny sur slack stp

fait: `slack_send_message` → groupe `slack`
attendu: slack

### 8
> peux tu me donner els meilleurss cotes a jouer en pari sportifs

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 9
> Fais moi une liste plus grande inclunt les apris de demain, qu'est ce qui est le plus safe pour me faire un peu d'argent

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 10
> Peux tu me dire qui est favorable au basket entre wahsington mystics et las vegas ? (il joe actuellement le amch)

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 11
> Regarde bien a nouveau, les amtch que tu dis perdu sont encore en cours et il gagnesnt , regarde tout bien

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 12
> Je veux que tu me note ce paris sportifs combinés, reverifie tout bien maintenant pour avoir les derniers scores

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 13
> Pux tu regarder tous les meilleurs pornos pour aujour'hui. Ton apri d'hier a été raté... Je veux un pari sur cette fois ci j'ai 5€ a mettre, le but est de finir la journée avec 15 à 30€

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 14
> Hmm peux tu regarder voir s'il n'y a pas moins risqu&é ? estime moi le purcentage de réussite sur ce vombot

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 15
> Je veux que tu me trouves un combien qui soit au essus de 80% de chance de réussite

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 16
> Je veux que tu ùe donnes mon pari combine sur les match de baseball Atlantas Braves, Detroit Tigers et pour le football Houston Dynamo, Los angeles

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 17
> Peux tu me dire s'il y a de bon pris a faire la en ce moment ou pas ?

fait: `ask_clarification` → groupe `—`
attendu: quant

### 18
> Peux tu me dire s'il y a de bon paris a faire la en ce moment ou pas ?

fait: `ask_clarification` → groupe `—`
attendu: quant

### 19
> Peux-tu me dire si y'a de bons paris ?

fait: `ask_clarification` → groupe `—`
attendu: quant

### 20
> Peux-tu me dire si y'a de bons paris à faire en foot en ce moment ?

fait: `ask_clarification` → groupe `—`
attendu: quant

### 21
> Peux tu me dire s'il y a de bon paris sportifs a faire la en ce moment ou pas ?

fait: `ask_clarification` → groupe `—`
attendu: quant

### 22
> Tu peux me donner les meillerus pronos sportifs du moment stp

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 23
> J'ai 5€ a mettre, trouve moi le meilleur ocmbiné pour faire au moins x2 voire x3

fait: `parlay_analyze` → groupe `quant`
attendu: quant

### 24
> J'ai 5€ a mettre, trouve moi les meilleurs paris sirtifs ou combinés pour faire au moins x2 voire x3 sur mes gains

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 25
> Peux tu faire des recherhes internet pour assuré ce que tu dis sur les paris safe et moderate

fait: `web_search_news` → groupe `news`
attendu: news

### 26
> tu aurais d'autes paris a me faire qui sont sur, sur d'autres sport style tennis ou autre ?

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 27
> peux tu approfondir le paris entre de minaur et tsitsipas ? pour savoir si c'est sur qu de minaur gagne ou non

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - quant)

### 28
> cherche d'autres paris a faire ou des combines sur et certains pour arriver au moins sur un x2 et si posible x3

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 29
> le match kansas city il est quand ?

fait: `get_current_time` → groupe `—`
attendu: search

### 30
> peux tu appronfondir le pari pjiladelphia contre atalnta stp

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - quant)

### 31
> Toutes les entreprises dans la tech finance bitvoin etc..

fait: `shell_run` → groupe `shell`
attendu: ambigu

### 32
> reprend ou tu en étais

fait: `shell_run` → groupe `shell`
attendu: ambigu

### 33
> J'ai 4€ a metre dans des paris sportifs avec comme but de faire un x2 voire x3, tu aurais des paris quasi sur et certains ou combos a faire en ce moment pour ça ?

fait: `get_current_time` → groupe `—`
attendu: quant

### 34
> je  suis sur tout, je veux juste lesmeilleursnmises pour jouer aujour'dhui

fait: `web_search_news` → groupe `news`
attendu: quant

### 35
> je veyx des matchs plus récents, demain ou après demain max, pas 21 aout..

fait: `web_search_news` → groupe `news`
attendu: quant

### 36
> il y a as mal de tennis en ce moment, regarde la dessus

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 37
> on est le 1aout j'en veux pur le 1

fait: `web_search_news` → groupe `news`
attendu: ambigu

### 38
> surveille moi alors les entreprises cotes en bourse

fait: `ask_clarification` → groupe `—`
attendu: cron

### 39
> je veux des paris pour aujourd'hui, pas dans 1 mois

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 40
> gznre quans je lance saphire alpha ça me dis "vous ne pouvez pas utiliser ceete carte de jeu"

fait: `ask_clarification` → groupe `—`
attendu: search

### 41
> Tu peux surveiller chaque jour le cours d'actions des entreprises partout dans le monde (je veux TOUT) et tu me fais des rapports sur le canal test-cron

fait: `ask_clarification` → groupe `—`
attendu: cron

### 42
> 'utilise dunctl, tu peux tout me close stp

fait: `shell_run` → groupe `shell`
attendu: shell

### 43
> Crée un cube rouge au centre de la scène Blender, puis dis-moi ce qu'il y a dans la scène.

fait: `blender__execute_blender_code` → groupe `?`
attendu: mcp blender

### 44
> Peux tu supprimer mle cube rouge et me faire une camionnette de safari

fait: `ask_clarification` → groupe `—`
attendu: mcp blender

### 45
> fais moi une camionnette de safari

fait: `ask_clarification` → groupe `—`
attendu: mcp blender

### 46
> Tu peux me la ceter un peu ieux stp

fait: `ask_clarification` → groupe `—`
attendu: ambigu

### 47
> Peux tu juste donner du volume au logo en faisant  une extrusion dessus ? comme ça il sera lui aussi 3d

fait: `run_coding_agent` → groupe `coding`
attendu: mcp blender

### 48
> Peux tu juste donner du volume au logo en faisant  une extrusion dessus sur blender ? comme ça il sera lui aussi 3d

fait: `run_coding_agent` → groupe `coding`
attendu: mcp blender

### 49
> Extrude le plus, ce n'est pas assez encore la

fait: `blender__execute_blender_code` → groupe `?`
attendu: mcp blender

### 50
> Peux tu sur blender rendre le cube rouge

fait: `load_skill` → groupe `—`
attendu: mcp blender

### 51
> fais moi la scene demandé sur blender

fait: `run_coding_agent` → groupe `coding`
attendu: mcp blender

### 52
> Peux tu me faire une scene sur blender d'un igloo sur une baquise avec une tuile de l'igloo qui floote dans l'air ?

fait: `load_skill` → groupe `—`
attendu: mcp blender

### 53
> Refais l'igloo, je veux quelque chsoe de ce type la: 6e1362cd70304fd39abd7917a26e10fa  juste une des briques du cote tu l'loignes de quelques centmetres et u la fais flotter avec une animation

fait: `run_coding_agent` → groupe `coding`
attendu: mcp blender

### 54
> Refais l'igloo sur blender, je veux quelque chsoe de ce type la: 6e1362cd70304fd39abd7917a26e10fa (uuid sur sketchlab)

fait: `load_skill` → groupe `—`
attendu: mcp blender

### 55
> essaye avec lui, ça passera 224f673917e6486eb08c496baf77ce84

fait: `blender__download_sketchfab_model` → groupe `?`
attendu: mcp blender

### 56
> Supprime l'igloo que tu avais fais avant pour ne garder que celui de sketchlab, et fais flotter une pierre de l'igloo du cote droit avec une animation

fait: `blender__execute_blender_code` → groupe `?`
attendu: mcp blender

### 57
> tu peux rendre l'une des briques de l'igloo sur e cote et la déplacé un peu sur le cote, moitié de la brique dans l'igloo l'autre moitié dehors

fait: `blender__execute_blender_code` → groupe `?`
attendu: mcp blender

### 58
> Tu e penses quoi du paris sportif que Lyion gagne et les deux équipes marquent entre Sparta Prague et Lyon ? Tu l'évaluerais comment ce pari ?

fait: `ask_clarification` → groupe `—`
attendu: quant

### 59
> peux tu faire des recherches internet dur les deux equipes pur recueillir des données et me donnes plus de détail stp

fait: `web_research_report` → groupe `search`
attendu: ambigu (search - quant)

### 60
> peux tu envoyer tout ça à Nicolas Danquigny sur Slack stp

fait: `ask_clarification` → groupe `—`
attendu: slack

### 61
> reprend le texte sur quoi faire a nice et envoie le sur Slack à Nicolas Danquigny

fait: `slack_find_user` → groupe `slack`
attendu: slack

### 62
> envoie le mail de nouveau

fait: `ask_clarification` → groupe `—`
attendu: gmail

### 63
> envoie lui la lsite des meilleurs casino du coins à faire

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - slack - gmail)

### 64
> J'ai 20€ de bankroll et 20€ de freebets, donne moi des parsi sur afin d'augmenter mes gains, j'aiemrais un but de x2 voire x3 mais je veux surtout que le pari soit sur

fait: `ask_clarification` → groupe `—`
attendu: quant

### 65
> Reverifie es matchs car il y en a qui sont pour dimanche ou autre, pas du tout pour aujourd'hui ou demain ?

fait: `web_search_news` → groupe `news`
attendu: ambigu (quant - search)

### 66
> Regarde tous les matchs atp au tennis, et dis moi les paris a faire sur matchs les plus surs ou les meilleurs combinés a faire aujourd'hui ou demain matin

fait: `winamax_odds_fetch` → groupe `quant`
attendu: quant

### 67
> en sachant que je veux que du tennis, tu en penses quoi de gagnant tiafoe, nakashima, pegula ? pour toi ce paris est il sur de passer ? tu le situerais ou ?

fait: `ev_analyze` → groupe `quant`
attendu: quant

### 68
> Peux tu me dire si mon ollama cli est a jour ou pas ? et comment le mettre a jour ? check avec qui l a été installé etc.

fait: `shell_run` → groupe `shell`
attendu: shell

### 69
> vérifie par tp meme les version e tla mienne

fait: `web_search_news` → groupe `news`
attendu: shell

### 70
> Combien coute un macbook pro avc une puce Apple M2 pro, 16go sur le site officielle apple ?

fait: `web_research_report` → groupe `search`
attendu: search

### 71
> regarde sur d'autres sites pour voir

fait: `web_research_report` → groupe `search`
attendu: search

### 72
> J'ai 20 € de bankroll et 20 € de freebets. Je veux les meilleures opportunités disponibles maintenant ou demain matin. Tous sports, toutes compétitions. Simple ou combiné.

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 73
> J'ai 20 € de bankroll et 20 € de freebets. Tous sports, toutes compétitions, maintenant ou demain matin.

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 74
> porpose quand meme pour l'experimentale

fait: `ask_clarification` → groupe `—`
attendu: quant

### 75
> J'ai 20 €, les meilleurs paris tennis aujourd'hui ?

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 76
> FAIS moi le prjet de A à Z, développe moi tout vasy en suivant la spec

fait: `shell_ls` → groupe `shell`
attendu: coding

### 77
> ajoute moi ses dépendances et continue: Toutes listées dans le plan (lucide‑react, clsx, tailwind‑merge, framer‑motion, lenis, shadcn/ui, @radix‑ui/react‑slot)

fait: `run_coding_agent` → groupe `coding`
attendu: coding

### 78
> reprend ou tu en étais sans rien oublier

fait: `shell_run` → groupe `shell`
attendu: coding

### 79
> contoinue alors, reprend le travail et finin moi tout ça

fait: `axon_note` → groupe `memory`
attendu: coding

### 80
> reprend le site next js et termne le moi comme le dis la spec, n'oublie rien

fait: `run_coding_agent` → groupe `coding`
attendu: coding

### 81
> tu auras de paris sur du foot ou du tennis avec les memes consignes qu'ua début ?

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 82
> Ce soit im y a psg aston villa, tu pense quoi de ce match ? c'est quoi tn porni avec ton puircentage ?

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 83
> il y a des paris ou des combinés qui te semblent intéressant pour faire du x2 voire x3 ? il faut que lesparis soitsure à plus de 90% sur l'evenement

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 84
> Au tennis tu me conseilles quoi comme paris sportifs a faire qui est quasi sur de passer ? je préfere un combiné par aileurs

fait: `ask_clarification` → groupe `—`
attendu: quant

### 85
> d'accord mais quels sont les paris en review onl, peux tu me les montrer stp

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 86
> j'ai 10€ et tous les sports, et sur un combiné ou si tu as des paris simples, mais faut que le pari soit sur. La le but c'est d'aoir iun cimbiné qui est sur et certain de passer

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 87
> Cherche sur le web les nouveautes de LangGraph en 2026

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - news)

### 88
> Fais moi un rapport détaillé su les dernieres news de l'ia stp

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - news)

### 89
> Fais moi un rapport detaille sur les dernieres news de lia stp

fait: `ask_clarification` → groupe `—`
attendu: ambigu (search - news - drive)

### 90
> Fais moi une recherche sur le dog argentin

fait: `web_research_report` → groupe `search`
attendu: search

### 91
> Tu peux réparer le bug qu'il y a sur le repo axon-landing stp

fait: `shell_pwd` → groupe `shell`
attendu: coding

### 92
> c'es tquoi la mété demain ?

fait: `ask_clarification` → groupe `—`
attendu: weather

### 93
> Quelle est la météo de demain ?

fait: `ask_clarification` → groupe `—`
attendu: weather

### 94
> Quelle est la meteo de demain a Suresnes ?

fait: `get_weather_by_city` → groupe `weather`
attendu: weather

### 95
> Tu peux me faire un rapport d'une vingtaine de pages avec des pages annexes ou il y a des photos tableaux etc.. sur la seconde guerre mondiale ? fais le sut google doc

fait: `google_docs_create` → groupe `drive`
attendu: drive

### 96
> Peux tu me dire s'il va pleuvoir à suresnes oupas ?

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - weather)

### 97
> je vux plus de détail, un tableau de toutes les heurs

fait: `web_search` → groupe `?`
attendu: cron

### 98
> Cherche sur le web les dernieres nouveautes de LangGraph en 2026 et resume les

fait: `web_research_report` → groupe `search`
attendu: search

### 99
> va regarde les modeles sdispo su internet et test les dans le terminal avec un message pour quo puissesavoir si oui ou non ils sont accessible pour axon, et refais donc les 3 tableaux dans le fichier

fait: `web_research_report` → groupe `search`
attendu: ambigu (search - shell)

### 100
> noraml tu n'as pas de clef api, lance depuis mon terminal directement un ollama run [model_name] "hello" et la tu auras ta réponse

fait: `shell_run` → groupe `shell`
attendu: shell

### 101
> J'ai une bankrool de 20€ j'aimerais faire un combine de paris sportif pour atteindre un x2, tu me conseilles quoi ? ens chantq ueje veux que le âri soit sur de passer

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 102
> pour le tennis tu en as aussi pour le atp ou wta ??

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 103
> le truc virtual box tu peux me le supprimer au meme titre que les versions d'android stp ?

fait: `ask_clarification` → groupe `—`
attendu: shell

### 104
> je n'ai aps des réisuds de nAS qui grattent quelques go et des rasidus de andrpoid avec des versions ?

fait: `ask_clarification` → groupe `—`
attendu: shell

### 105
> il me rste cbm de stockage ?

fait: `shell_run` → groupe `shell`
attendu: shell

### 106
> Yo, tu pourrais me faire des recherches sur les denrieres infos politiques en france stp ? les polémiques etc.

fait: `web_search_news` → groupe `news`
attendu: ambigu (news - search)

### 107
> peux tu me faire un rapport sur un doc google doc avc des images stp en lien avec c euqe tu as trouvé sur iternet, tu peux préciser vua d'autres recherhes internet, et tu me emts tes sources

fait: `google_docs_create` → groupe `drive`
attendu: ambigu (search - news - drive)

### 108
> tu pourrais regarder mes derniers mails stp

fait: `gmail_search` → groupe `gmail`
attendu: gmail

### 109
> tu peux tout me mettre dans un google doc, puis me faire une présentaion des différents agents avec leurs point fort, points faibles etc..

fait: `google_docs_create` → groupe `drive`
attendu: ambigu (search - news - drive)

### 110
> danns le match actuelle marseille strasbourg, le but a la 45eme a été marqué en premiere mi temps ou en deucieme ?

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - news)

### 111
> il  a été marqué quand le but ? 45 ou 46 ?

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - news)

### 112
> mais c'eest 46eme premier mi tempsaec temps additionnel, ou 46 deuxieme mi temps, c'est ça ma qustion

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - news)

### 113
> Je dois faire une présentation sur le TypeScript, et précise sur react avec la dfférence vec le javascript. 

Fais les rechereces nécessaires sur tout ça et fais en moi une présentation

fait: `web_research_report` → groupe `search`
attendu: ambigu (search - news - slides)

### 114
> tu peux le reprendre et etre plus complet, parler plus de la diffrence entre type script et javascript et en faire un cours, et s'appuyer sur l'example de react

fait: `create_slides` → groupe `slides`
attendu: ambigu (search - news - slides)

### 115
> tu peux rajouter des arbres etc.. diversifie es slides

fait: `create_slides` → groupe `slides`
attendu: slides

### 116
> Tu peux me faire une nouvelle présenation sous forme de cours pour apprendre next.js

fait: `create_slides` → groupe `slides`
attendu: ambigu (search - news - slides)

### 117
> refais mais fais des recherches internet dessus avant pour avor les derniers infos etc.

fait: `web_research_report` → groupe `search`
attendu: ambigu (search - news - slides)

### 118
> Tu eux regarder ce qu'est le rag en détail, pa en dev en prod, ce qui change du dev et me schématiser tout ça

fait: `mermaid_diagram` → groupe `diagrams`
attendu: ambigu (search - news - diagrams)

### 119
> J'aimerais faire des paris sportifs sur n'importe quel sport, des combinés de préférence, tu me conseillerais quoi ? (j'ai 6€ de bankoll)

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 120
> dans mon serveur kaine, tu peux me génrer une clef ssh dessus stp ? en ed2... ?

fait: `shell_run` → groupe `shell`
attendu: shell

### 121
> tu peux accéder a mon serveur disyant kaine ?

fait: `ask_clarification` → groupe `—`
attendu: shell

### 122
> peux tu vérifier tout ça ?

fait: `shell_run` → groupe `shell`
attendu: shell

### 123
> peux tu renommer ma cmlef u recrer la clef pour qu'elle soit revocnnus avec un nom normal stp ?

fait: `ask_clarification` → groupe `—`
attendu: shell

### 124
> Tu peux me mettre ces lignes en comentaires stp

fait: `shell_run` → groupe `shell`
attendu: ambigu (shell - coding)

### 125
> tu penses quoi de ce pari ?

fait: `ask_clarification` → groupe `—`
attendu: quant

### 126
> TU peux me faire une recherche sur les modeles du frree tiers du nvidia cloud

fait: `ask_clarification` → groupe `—`
attendu: ambigu (search - news)

### 127
> tu peuxme faire une recherche et un benchmark sur le model nemotron en llm agentique stp

fait: `local_find_file` → groupe `filesystem`
attendu: ambigu (search - news)

### 128
> peux tu analyser encore plus end étail mour savoir qu'est ce qui prend autant de place ? je veux tout savoir, que e soit dans documents, dans les docker qui tourne etc...

fait: `shell_run` → groupe `shell`
attendu: shell

### 129
> liste moi les gros dossiers dans projet perso

fait: `shell_run` → groupe `shell`
attendu: shell

### 130
> dans rag et ai-agent qu'est ce qui prend le plus d'esapce ? comment c'est possible ? c'est cuda ?

fait: `shell_run` → groupe `shell`
attendu: shell

### 131
> vasy suppirme les caches, les volumes docker, les runtimes flatpack inutiliées

fait: `shell_run` → groupe `shell`
attendu: shell

### 132
> il me reste cbm de stockage ?

fait: `shell_run` → groupe `shell`
attendu: shell

### 133
> je veux que tu regardes s'ile xiste des codes pormos sur cette article: Lenovo Legion 7i Gen 7
Trouve des codes pormosn et teste les pour voir lesquels foinctionne

fait: `web_search_news` → groupe `news`
attendu: ambigu (search - news)

### 134
> Tu me conseillerais quoi comme combine de paris sportif a faire en ce moment ?

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 135
> refais, je veux des paris qui sont sur de passer, je m'en fous de la cote

fait: `betting_recommend` → groupe `quant`
attendu: quant

### 136
> écris un mail a qtdufour@gmail.com pour lui dire bonjour

fait: `gmail_send_email` → groupe `gmail`
attendu: gmail

### 137
> Envoie un mail a qtdufour@gmail.com pour lui dire bonjour

fait: `gmail_send_email` → groupe `gmail`
attendu: gmail

### 138
> Le mail n'a pas été envoyé. rédige un peu plus quand meme, et demande lui si ces vacances se sont bien passées. Prépare un nouveau brouillon avec gmail_send_email en tenant compte de cette demande.

fait: `gmail_send_email` → groupe `gmail`
attendu: gmail

### 139
> Le mail n'a pas été envoyé. c'est pour mon boss donc ne soit pas aussi direct. Prépare un nouveau brouillon avec gmail_send_email en tenant compte de cette demande.

fait: `gmail_send_email` → groupe `gmail`
attendu: gmail

### 140
> nvoie un mail a qtdufour@gmail.com pour lui dire bonjour

fait: `gmail_send_email` → groupe `gmail`
attendu: gmail

### 141
> 1 fichier(s) écrit(s) : cooler-boost Poursuis la tâche ; n'écris pas ces fichiers une seconde fois.

fait: `edit_file` → groupe `filesystem`
attendu: ambigu (shell - filesystem)

### 142
> 1 fichier(s) écrit(s) : user-scenario Poursuis la tâche ; n'écris pas ces fichiers une seconde fois.

fait: `local_read_file` → groupe `filesystem`
attendu: ambigu (shell - filesystem)

### 143
> tu peux mettre le fan mode en mode max pour tester pendant 5sec et le remettre en mode auto pares ?

fait: `shell_run` → groupe `shell`
attendu: shell

### 144
> L'utilisateur a refusé d'exécuter : ~/.local/bin/fan-max-test. Ne la relance pas ; propose autre chose ou demande-lui ce qu'il préfère.

fait: `ask_clarification` → groupe `—`
attendu: 

### 145
> tu ne peux pas rendre le notification de cooler-boost u peu plus jolie ?

fait: `edit_file` → groupe `filesystem`
attendu: 

### 146
> reprend pour user scenarion, car le vois MSI: rien et FAN: rien..

fait: `local_read_file` → groupe `filesystem`
attendu: ambigu (shell - filesystem)

---

## Tours elliptiques (38) — hors corpus

Réponses de suivi qui ne se comprennent que dans leur contexte. Un routeur ne
peut pas les traiter, et ne devrait pas essayer : elles relèvent du prior
conversationnel. Gardées ici pour mémoire, à ne pas labelliser.

- « Créer moi in projet » → `ask_clarification`
- « Nan aujourd'hui » → `stop_cron_task`
- « c'est le wta a prague » → `web_search_news`
- « tu peux reprendre » → `shell_run`
- « c'est bin je veins de répondre a esq questions » → `shell_run`
- « et potu les matchs de foot ? aujour'hui il y en a pas mal tu peux regarder pour  » → `web_search_news`
- « ok trouve moi les meilleurs paris sportifs pour les match duu 1aout et maaaaaax  » → `web_search_news`
- « comment ça ? » → `ask_clarification`
- « voici l'uid: d76a1407c0cd4d36a68d379a89863c07 » → `blender__download_sketchfab_model`
- « je t'ai rep » → `ask_clarification`
- « https://sketchfab.com/3d-models/7-igloo-6e1362cd70304fd39abd7917a26e10fa » → `blender__download_sketchfab_model`
- « nan elle est beaucoup trop loins, il faut que la tuile tu l'enleves du modele de » → `blender__execute_blender_code`
- « et envoie lui la lsite des meilleurs casino du coins à faire » → `web_search_news`
- « du coup ? » → `ask_clarification`
- « nan pas la puce M5, la puce M2 pro je veux » → `web_search_news`
- « ??? regarde » → `url_fetch`
- « Coucou ça va ? » → `ask_clarification`
- « vasy poursuit alors » → `shell_ls`
- « et en combiné tu as quoi à me porposer ? » → `ask_clarification`
- « OK j'aimerai faire des paris sur sur sur, je m'en fous de la cote, tume coseiles » → `betting_recommend`
- « OK j'aimerai faire des paris sportifs sûr, je m'en fous de la cote, tu me coseil » → `ask_clarification`
- « J'ai 20€ de bankroll » → `ask_clarification`
- « Ok montre moi des paris/combinés surs qui me permettraient de faire environ un x » → `ask_clarification`
- « c'est quoi la météo de demain ? » → `ask_clarification`
- « et demain ? fais moi un tableau es prvisions de suesnes temperature et temps de  » → `get_weather_by_city`
- « tout est good ? » → `shell_run`
- « nan je veux que tu le fasses dans le serveur kaine » → `shell_run`
- « ok mtn peux tu t'y connecter et créer dans ce serveur une paire de clefs ssh ed_ » → `shell_run`
- « nan fais le toi » → `run_coding_agent`
- « vérifie sur internet » → `web_research_report`
- « coucou ça va ? » → `url_fetch`
- « coucou » → `shell_run`
- « vasy supprime els alors » → `shell_run`
- « j'ai 6€ » → `betting_recommend`
- « lance le » → `shell_run`
- « ~/.local/bin/fan-max-test » → `shell_run`
- « c'est fait normalement, e viens de le faire, check et dis moi » → `local_read_file`
- « et pareil pour les user scenarion ? le deisgné autrement ? car la on ne comprend » → `edit_file`
