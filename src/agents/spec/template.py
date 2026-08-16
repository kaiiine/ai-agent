"""La forme de la spec produite — et pourquoi cette forme-là.

L'ancienne spec était un plan de document : Vision, Direction Artistique, Stack,
Pages. Complète et lisible, mais elle ne disait ni dans quel ordre construire,
ni comment savoir qu'une partie est finie. `/build` en tirait donc des phases par
COUCHE TECHNIQUE — scaffold, composants partagés, pages, polish — et la première
version utilisable n'existait qu'à la fin.

Deux changements, repris de spec-kit (github/spec-kit, MIT) :

TRANCHES PRIORISÉES ET INDÉPENDANTES. Chaque histoire P1, P2, P3 doit être
livrable seule. P1 seule = un produit qui marche, réduit mais réel. C'est ce qui
permet de s'arrêter après P1 sans avoir un chantier ouvert, et ce qui donne à
`/build` un ordre de construction qui produit de la valeur à chaque étape plutôt
qu'à la fin.

CRITÈRES VÉRIFIABLES. Chaque histoire porte des scénarios Étant donné / Quand /
Alors. Une phase de build a alors une définition de fini opposable, au lieu de
« l'agent estime avoir terminé ».

S'y ajoute une section propre à AXON : le JOURNAL DES CLARIFICATIONS. Chaque
réponse donnée pendant le wizard est écrite dans la spec avec sa question. Sans
lui, une décision arbitrée en trente secondes devient trois mois plus tard une
ligne dont personne ne sait si elle a été choisie ou subie.
"""

from __future__ import annotations

#: Rappelé au modèle à chaque génération. Ce qui rend une spec inutilisable
#: n'est pas ce qu'elle omet, c'est ce qu'elle laisse ouvert en ayant l'air
#: décidé.
REGLES_DE_REDACTION = """\
- TRANCHE. Aucun « ou bien », « selon les besoins », « à définir », « au choix ».
  Si tu hésites entre deux options, choisis-en une et écris pourquoi en une ligne.
- CHIFFRE. « rapide » n'est pas une exigence, « réponse sous 200 ms » en est une.
  Si aucun chiffre n'a été donné, propose-en un plausible et marque-le
  « (valeur proposée, à confirmer) ».
- N'INVENTE PAS DE FAIT. Les décisions viennent du descriptif et des réponses.
  Ce qui n'a pas été dit et qui doit l'être va dans « Questions ouvertes ».
- UNE SOURCE RÉFÉRENCÉE FAIT FOI, ET SON SILENCE AUSSI. Quand l'utilisateur
  renvoie à un dépôt, un README ou un fichier — « regarde dans le repo X » — le
  contenu injecté entre marqueurs `[Contenu de …]` ou `[DESIGN RÉEL …]` est LA
  réponse. Recopie ses valeurs exactes ; n'en propose aucune autre.
  Si le marqueur dit `[DESIGN NON TROUVÉ …]`, alors la source ne porte PAS cette
  information : écris-le noir sur blanc dans la section concernée, mets la
  question dans « Questions ouvertes », et NE FABRIQUE RIEN à la place.
  Inventer une palette là où l'utilisateur en a désigné une est le pire défaut
  possible : le résultat a l'air décidé, il est faux, et rien ne le signale.
- Chaque exigence porte un identifiant EF-001, EF-002… pour être citable.
- Chaque histoire est INDÉPENDAMMENT livrable : P1 seule doit donner un produit
  utilisable, réduit mais réel.
- LA DIFFÉRENCIATION ANNONCÉE EN VISION EST LA PARTIE LA PLUS DÉTAILLÉE DE LA
  SPEC, et elle a sa propre section. Si le produit se distingue par « une démo
  qu'on peut réellement essayer », alors son protocole, ses limites, sa sécurité
  et ses états d'échec reçoivent au moins autant de place que la page de contact.
  Une spec dont le cœur est moins précis que sa périphérie fera construire la
  périphérie.
- NE FIGE PAS UNE VERSION SANS RAISON. Écris « version LTS courante au moment de
  l'implémentation » plutôt qu'un numéro majeur arbitraire — sauf si une
  contrainte réelle l'impose, et alors dis laquelle.
- VÉRIFIE TA PROPRE COHÉRENCE avant de rendre : deux passages ne doivent pas se
  contredire, et « Questions ouvertes : aucune » est FAUX si une valeur porte
  encore « à confirmer ».\
"""

#: Sections communes à tous les profils. Les sections propres au profil
#: (direction artistique, contrat d'API…) sont ajoutées par `structure_pour`.
_SOCLE = """\
# {nom}

## Vision
- Le produit en une phrase
- Pour qui, précisément
- Ce qui le distingue de l'existant

## Périmètre
### Dans la v1
- Liste explicite

### HORS périmètre v1
- Liste explicite de ce qu'on ne fait PAS, et pourquoi
- Cette section est aussi importante que la précédente : sans elle, tout ajout
  paraît légitime

## Histoires utilisateur

### P1 — [titre court]
[Le parcours en langage courant, sans jargon technique]

**Pourquoi cette priorité** : [ce qu'on perd si on ne fait que ça]

**Livrable seul** : [en quoi cette tranche, seule, donne un produit utilisable]

**Critères d'acceptation**
1. **Étant donné** [état initial], **quand** [action], **alors** [résultat observable]
2. **Étant donné** […], **quand** […], **alors** […]

### P2 — [titre court]
[même structure]

### P3 — [titre court]
[même structure]

## Exigences fonctionnelles
- **EF-001** : [exigence testable, une seule idée par ligne]
- **EF-002** : …

## Domaine & données
- Entités, attributs, relations
- Règles d'identité et d'unicité
- Cycle de vie / transitions d'état
- Volumétrie attendue

## Contraintes techniques
- Stack COMPLÈTE et tranchée : langage, framework, persistance, hébergement
- Alternatives rejetées, en une ligne chacune
- Dépendances externes et comportement quand elles tombent

## Exigences non fonctionnelles
- Performance : [chiffré]
- Montée en charge : [chiffré]
- Sécurité et données personnelles
- Observabilité : ce qu'on doit pouvoir mesurer en production

## Cas limites
- Scénarios négatifs et ce qui doit se passer
- Accès concurrent, conflits
- États vide / chargement / erreur

## Definition of Done
- Ce qui prouve que la v1 est livrable
- Niveau de test attendu
"""

#: Ajouts par profil. Insérés APRÈS « Périmètre » pour les profils visuels — la
#: direction artistique se lit avant les histoires — et après « Contraintes
#: techniques » pour les autres.
_SECTIONS_PROFIL: dict[str, str] = {
    "site_web": """\
## Direction artistique
### Ambiance & références
- Ambiance : 3 adjectifs précis
- Références concrètes (sites, films, artistes) : 2-3
- Niveau : luxe / minimal / expérimental / artisanal

### Système visuel
- Palette : primaires + accents, codes hex
- Typographies : heading et body, noms réels
- Layout : densité, marges, grille
- Textures et fonds

### À éviter absolument
- Ce que le design ne doit pas évoquer
- Patterns visuels interdits

## Pages & contenu
- Arborescence complète
- Contenu de chaque page
- Responsive : points de rupture
- Accessibilité : niveau visé
- SEO : titres, métadonnées, données structurées
""",
    "application_web": """\
## Direction artistique
- Ambiance : 3 adjectifs
- Densité d'interface : outil dense / grand public aéré
- Palette, typographies, thème clair-sombre
- Bibliothèque de composants retenue

## Comptes & autorisations
- Méthode d'authentification
- Rôles, et ce que chaque rôle peut faire
- Ce qui est visible sans compte

## Écrans & navigation
- Liste des écrans
- Navigation principale
- Responsive
""",
    "api_service": """\
## Contrat d'API
- Style : REST / GraphQL / RPC, et pourquoi
- Ressources et opérations
- Format des erreurs (structure exacte)
- Pagination, filtrage, tri

## Accès & quotas
- Authentification
- Portées / permissions
- Limitation de débit

## Versionnage
- Stratégie de version
- Politique de rupture et dépréciation
""",
    "cli": """\
## Surface de commande
- Commandes et sous-commandes
- Options principales par commande
- Comportement sans argument
- Mode interactif : oui / non

## Sorties
- Format lisible par un humain
- Format machine (JSON) : oui / non
- Codes de sortie et leur signification
- Verbosité et mode silencieux
""",
    "pipeline_donnees": """\
## Sources & fraîcheur
- Origines des données
- Fréquence de rafraîchissement
- Comportement quand une source est indisponible
- Fenêtre de rattrapage

## Schéma & qualité
- Schéma d'entrée et de sortie
- Validation appliquée
- Traitement d'un enregistrement invalide

## Idempotence & reprise
- Rejouable sans doublon : comment
- Reprise après échec partiel
- État persistant et où il vit
""",
    "mobile": """\
## Plateformes & distribution
- iOS / Android / les deux, versions minimales
- Natif ou cross-platform, et pourquoi
- Distribution

## Hors-ligne & synchronisation
- Ce qui fonctionne sans réseau
- Stratégie de synchronisation
- Résolution de conflit

## Permissions & notifications
- Permissions demandées et justification
- Notifications push
""",
    "bibliotheque": """\
## Surface publique
- Ce qui est exporté
- Ce qui reste interne
- Exemple d'appel typique

## Compatibilité & packaging
- Versions du langage supportées
- Dépendances acceptables
- Publication et versionnage
""",
    "agent_ia": """\
## Capacités & garde-fous
- Ce que l'agent peut faire
- Ce qu'il ne doit JAMAIS faire
- Ce qui exige une validation humaine

## Évaluation
- Comment on mesure qu'il fait bien
- Jeu de test
- Critère d'échec

## Modèle & coût
- Modèle retenu
- Budget par exécution
- Latence acceptable
""",
}

#: Toujours en dernier. Une spec honnête se termine par ce qu'elle ne sait pas.
_QUEUE = """\
## Questions ouvertes
- Ce qui reste à trancher, et qui doit trancher
- Écrire « aucune » si tout est décidé — le silence se lit comme un oubli
"""


def structure_pour(profil: str) -> str:
    """Le plan de la spec pour ce profil, sections propres comprises."""
    sections = _SECTIONS_PROFIL.get(profil, "")
    if not sections:
        return _SOCLE + "\n" + _QUEUE

    # Les profils visuels placent leur direction artistique AVANT les histoires :
    # elle conditionne la façon de les écrire. Les autres l'ajoutent après les
    # contraintes techniques, où elle se lit comme un complément.
    if profil in ("site_web", "application_web"):
        avant, apres = _SOCLE.split("## Histoires utilisateur", 1)
        return f"{avant}{sections}\n## Histoires utilisateur{apres}\n{_QUEUE}"
    return _SOCLE + "\n" + sections + "\n" + _QUEUE


def journal_des_clarifications(paires: list[dict]) -> str:
    """Les questions posées et les réponses reçues, telles quelles.

    Écrit DANS la spec, et pas seulement consommé pour la produire. Une décision
    arbitrée en trente secondes devient sinon une ligne dont plus personne ne
    sait, trois mois après, si elle a été choisie ou subie.
    """
    if not paires:
        return ""
    lignes = ["", "## Journal des clarifications", "",
              "_Questions posées pendant la rédaction, et réponses retenues._", ""]
    for i, paire in enumerate(paires, start=1):
        lignes.append(f"{i}. **{paire['q']}**")
        lignes.append(f"   → {paire['a']}")
    return "\n".join(lignes) + "\n"


def systeme_de_generation(profil: str) -> str:
    """Le prompt système complet de la génération."""
    return (
        "Tu es un directeur produit et architecte technique. Tu rédiges une "
        "spécification COMPLÈTE, OPINIONÉE et ACTIONNABLE en Markdown français.\n\n"
        f"Règles de rédaction :\n{REGLES_DE_REDACTION}\n\n"
        "Respecte EXACTEMENT cette structure de sections :\n\n"
        f"{structure_pour(profil)}"
    )
