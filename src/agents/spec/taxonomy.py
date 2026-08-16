"""Les zones d'ambiguïté d'une spécification — le catalogue de ce qu'on peut ignorer.

Le générateur posait CINQ questions fixes : concept, direction artistique, stack,
UX, arborescence. Écrites pour des projets web créatifs, elles y étaient bonnes
et ailleurs absurdes — demander une palette de couleurs pour un pipeline de
données, et ne jamais demander sa volumétrie ni sa reprise sur erreur.

Le défaut n'était pas le nombre de questions, c'était leur SOURCE : elles
venaient du template, pas du projet. Une spec ne se remplit pas, elle se
complète — et ce qui manque dépend de ce qui a déjà été dit.

Ce module tient donc deux choses :

- un SOCLE de catégories qui valent pour tout projet logiciel — ce qu'il fait,
  sur quelles données, pour qui, avec quelles limites, et à quoi on saura que
  c'est fini ;
- des PROFILS qui ajoutent les catégories propres à une nature de projet. Un
  site vitrine a une direction artistique, un CLI a une ergonomie de commande,
  un pipeline a une politique de reprise. Aucun n'a les trois.

Chaque catégorie porte un POIDS D'IMPACT : combien la réponse change réellement
l'implémentation. Il sert à choisir quelles questions poser quand on ne peut pas
toutes les poser — un poids 3 non résolu passe devant deux poids 1.

La taxonomie du socle est reprise de spec-kit (github/spec-kit, MIT), dont
l'inventaire d'ambiguïté est le meilleur que je connaisse. Elle y est traduite,
resserrée, et surtout séparée des profils : spec-kit l'applique uniformément à
tout projet, ce qui pose les mêmes questions à un site et à une bibliothèque.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Categorie:
    """Une zone qu'une spec peut laisser floue, et ce que coûte ce flou."""

    id: str
    libelle: str
    #: Ce qu'on cherche à savoir. Sert à l'analyse de couverture ET à la
    #: rédaction de la question — les deux doivent parler de la même chose.
    couvre: tuple[str, ...]
    #: 1 à 3. Combien la réponse change l'implémentation, pas combien elle est
    #: intéressante. « Quelle base de données » vaut 3 ; « quelle police » vaut 1
    #: sur une API, 3 sur un site vitrine — d'où des poids par PROFIL.
    impact: int
    #: Pourquoi la question mérite d'être posée. Écrit pour être lu par le
    #: modèle qui rédige la question, pas seulement par un humain.
    pourquoi: str


# ══ Socle — vaut pour tout projet logiciel ══════════════════════════════════
SOCLE: tuple[Categorie, ...] = (
    Categorie(
        "objectif", "Objectif & périmètre",
        ("problème résolu", "critère de succès mesurable",
         "ce qui est explicitement HORS périmètre", "utilisateur visé"),
        impact=3,
        pourquoi="Sans périmètre explicite, tout ajout paraît légitime et la v1 "
                 "ne finit jamais. Le hors-scope est aussi décisif que le scope."),
    Categorie(
        "donnees", "Domaine & données",
        ("entités manipulées", "relations entre elles", "règle d'identité/unicité",
         "cycle de vie et transitions d'état", "volumétrie attendue"),
        impact=3,
        pourquoi="Le modèle de données décide de la moitié de l'architecture. "
                 "Le découvrir en cours de route impose une réécriture."),
    Categorie(
        "parcours", "Parcours & états",
        ("séquence principale bout en bout", "états vide / chargement / erreur",
         "ce que voit l'utilisateur quand ça échoue"),
        impact=2,
        pourquoi="Les états non nominaux sont la moitié du travail réel et la "
                 "totalité de ce qu'on oublie de spécifier."),
    Categorie(
        "contraintes", "Contraintes techniques",
        ("langage et framework", "persistance", "hébergement / exécution",
         "alternatives explicitement rejetées"),
        impact=3,
        pourquoi="Une contrainte tranchée ferme un débat ; une contrainte floue "
                 "le rouvre à chaque phase d'implémentation."),
    Categorie(
        "qualite", "Exigences non fonctionnelles",
        ("performance attendue chiffrée", "montée en charge", "disponibilité",
         "sécurité et données personnelles", "observabilité"),
        impact=2,
        pourquoi="« Rapide » et « robuste » ne se testent pas. Un chiffre, même "
                 "approximatif, rend le critère vérifiable."),
    Categorie(
        "integrations", "Intégrations externes",
        ("services et API tiers", "que faire quand ils tombent",
         "formats d'import/export", "authentification"),
        impact=2,
        pourquoi="Une dépendance externe non spécifiée devient une panne non "
                 "gérée. Son mode de défaillance fait partie du contrat."),
    Categorie(
        "cas_limites", "Cas limites & concurrence",
        ("scénarios négatifs", "limites de débit", "accès concurrent",
         "résolution de conflit"),
        impact=2,
        pourquoi="Ce sont les cas qui produisent les bugs qu'on ne reproduit pas."),
    Categorie(
        "fini", "Definition of Done",
        ("critères d'acceptation testables", "ce qui prouve que c'est livrable",
         "niveau de test attendu"),
        # Impact 2 et non 3, alors que la question est parmi les plus
        # importantes : le POIDS mesure ce que la RÉPONSE apporte, et ici la
        # structure fait déjà l'essentiel du travail. Le gabarit impose une
        # section Definition of Done et des critères Étant donné/Quand/Alors par
        # histoire ; `analyze` refuse la spec qui les omet. Poser la question en
        # plus la ferait payer deux fois, au prix d'une catégorie propre au
        # profil qui, elle, n'a aucun filet.
        impact=2,
        pourquoi="Sans critère d'acceptation, « fini » est une opinion. Avec, "
                 "c'est une vérification."),
)


# ══ Profils — ce qui ne vaut QUE pour une nature de projet ═════════════════
def _c(id, libelle, couvre, impact, pourquoi) -> Categorie:
    return Categorie(id, libelle, couvre, impact, pourquoi)


PROFILS: dict[str, tuple[Categorie, ...]] = {
    "site_web": (
        _c("direction_artistique", "Direction artistique",
           ("ambiance en 3 adjectifs", "références visuelles concrètes (sites, films, artistes)",
            "niveau : luxe / minimal / expérimental", "ce que le design ne doit PAS évoquer"),
           3, "Sur un site, l'ambiance EST le produit. Sans référence concrète, "
              "le résultat sera générique — et « moderne » n'est pas une référence."),
        _c("systeme_visuel", "Système visuel",
           ("palette avec codes hex", "typographies heading et body",
            "densité et grille", "traitement des fonds et textures"),
           2, "Ces valeurs se décident une fois ou se re-décident à chaque écran."),
        _c("interactions", "Interactions & motion",
           ("expérience principale (scroll narratif ? démo interactive ? vidéo ?)",
            "microinteractions qui comptent", "ce qui doit être mémorable"),
           2, "C'est ce qui distingue un site d'une brochure."),
        _c("arborescence", "Pages & arborescence",
           ("liste complète des pages/sections", "contenu de la v1",
            "responsive et accessibilité", "SEO et métadonnées"),
           2, "Une page oubliée en spec est une page improvisée en build."),
    ),
    "application_web": (
        _c("direction_artistique", "Direction artistique",
           ("ambiance en 3 adjectifs", "références visuelles concrètes",
            "densité d'interface : dense outil / aéré grand public"),
           2, "Une application dense et une application grand public ne se "
              "dessinent pas pareil, et le choix se fait une seule fois."),
        _c("systeme_visuel", "Système visuel",
           ("palette", "typographies", "bibliothèque de composants",
            "thème clair/sombre"),
           2, "Le système de composants conditionne la vitesse de toutes les pages."),
        _c("auth", "Comptes & autorisations",
           ("y a-t-il des comptes", "méthode d'authentification",
            "rôles et ce que chacun peut faire"),
           3, "Les autorisations traversent toutes les couches. Les ajouter "
              "après coup revient à réécrire les accès aux données."),
        _c("arborescence", "Écrans & navigation",
           ("liste des écrans", "navigation principale", "responsive"),
           2, "Un écran oublié en spec est un écran improvisé en build."),
    ),
    "api_service": (
        _c("contrat_api", "Contrat d'API",
           ("style : REST / GraphQL / RPC", "ressources et opérations",
            "format des erreurs", "pagination et filtrage"),
           3, "Le contrat est ce que consomment les autres. Le changer casse "
              "leurs intégrations."),
        _c("auth", "Authentification & quotas",
           ("méthode d'authentification", "portées et permissions",
            "limitation de débit"),
           3, "Une API sans politique d'accès est une API qu'on ne peut pas ouvrir."),
        _c("versionnage", "Versionnage & compatibilité",
           ("stratégie de version", "politique de rupture", "dépréciation"),
           2, "Sans politique, la première évolution casse un client."),
    ),
    "cli": (
        _c("ergonomie_cli", "Ergonomie de commande",
           ("commandes et sous-commandes", "options principales",
            "mode interactif ou non", "comportement sans argument"),
           3, "La surface de commande est l'interface utilisateur : elle se "
              "conçoit, elle ne s'accumule pas."),
        _c("sorties", "Sorties & codes de retour",
           ("format lisible humain", "format machine (JSON ?)",
            "codes de sortie", "verbosité et silence"),
           2, "Un CLI se compose avec d'autres outils. Sans format machine ni "
              "code de retour, il ne se scripte pas."),
    ),
    "pipeline_donnees": (
        _c("sources", "Sources & fraîcheur",
           ("origines des données", "fréquence de rafraîchissement",
            "que faire d'une source indisponible", "fenêtre de rattrapage"),
           3, "La fraîcheur est la promesse du pipeline. Non spécifiée, elle "
              "n'est jamais tenue ni mesurée."),
        _c("schema", "Schéma & qualité",
           ("schéma d'entrée et de sortie", "validation",
            "que faire d'un enregistrement invalide"),
           3, "Un pipeline sans politique d'invalide propage silencieusement."),
        _c("reprise", "Idempotence & reprise",
           ("rejouable sans doublon ?", "reprise après échec partiel",
            "état persistant"),
           3, "Tout pipeline finit par échouer en cours. Ce qui compte est ce "
              "qui se passe au redémarrage."),
    ),
    "mobile": (
        _c("plateformes", "Plateformes & distribution",
           ("iOS, Android, ou les deux", "versions minimales",
            "natif ou cross-platform", "distribution store"),
           3, "Le choix conditionne la stack entière et le coût de publication."),
        _c("hors_ligne", "Hors-ligne & synchronisation",
           ("fonctionne sans réseau ?", "synchronisation",
            "résolution de conflit"),
           3, "Le mobile perd le réseau. Ce n'est pas un cas limite, c'est le cas."),
        _c("permissions", "Permissions & notifications",
           ("permissions demandées", "notifications push", "vie privée"),
           2, "Chaque permission est un point de refus utilisateur à justifier."),
    ),
    "bibliotheque": (
        _c("api_publique", "Surface publique",
           ("ce qui est exporté", "ce qui reste interne",
            "ergonomie d'appel type"),
           3, "Tout ce qui est public devient un engagement de compatibilité."),
        _c("compatibilite", "Compatibilité & packaging",
           ("versions du langage supportées", "dépendances acceptables",
            "publication et versionnage"),
           2, "Une dépendance lourde dans une bibliothèque se paie chez tous "
              "ses utilisateurs."),
    ),
    "agent_ia": (
        _c("capacites", "Capacités & garde-fous",
           ("ce que l'agent peut faire", "ce qu'il ne doit JAMAIS faire",
            "validation humaine requise ?"),
           3, "Un agent sans interdit explicite finit par tout tenter."),
        _c("evaluation", "Évaluation",
           ("comment on mesure qu'il fait bien", "jeu de test",
            "critère d'échec"),
           3, "Sans mesure, la qualité d'un agent est une impression."),
        _c("cout", "Modèle & coût",
           ("modèle utilisé", "budget de tokens ou d'appels", "latence acceptable"),
           2, "Le coût par exécution décide de ce qui est déployable."),
    ),
    "generique": (),
}

#: Ce qu'on montre à l'utilisateur pour choisir, et ce que le modèle infère.
LIBELLES_PROFIL = {
    "site_web": "Site web / vitrine / landing",
    "application_web": "Application web (comptes, données, écrans)",
    "api_service": "API ou service backend",
    "cli": "Outil en ligne de commande",
    "pipeline_donnees": "Pipeline / traitement de données",
    "mobile": "Application mobile",
    "bibliotheque": "Bibliothèque / package",
    "agent_ia": "Agent IA / fonctionnalité LLM",
    "generique": "Autre",
}


def categories_du_profil(profil: str) -> tuple[Categorie, ...]:
    """Le socle, puis les catégories propres au profil.

    L'ordre compte : le socle d'abord, parce qu'un projet dont l'objectif est
    flou n'a pas besoin qu'on lui demande sa palette.
    """
    return SOCLE + PROFILS.get(profil, ())


def categorie_par_id(profil: str, id: str) -> Categorie | None:
    for c in categories_du_profil(profil):
        if c.id == id:
            return c
    return None
