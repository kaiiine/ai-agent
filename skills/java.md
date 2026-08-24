---
name: java
description: Builds and scaffolds Java projects from scratch: Spring Boot, Maven, Gradle, JUnit, Kotlin, Ktor.
aliases: [spring, maven, gradle]
---

━━ STACK DÉTECTÉ : JAVA / KOTLIN ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   Spring Boot → https://start.spring.io (ou spring init CLI)
   Ktor        → https://start.ktor.io
   Vérifier le gestionnaire du dépôt AVANT de choisir : pom.xml ou build.gradle.
   Ne jamais en introduire un second.

DISPOSITION (Spring Boot) :
   controller/   HTTP uniquement : valider l'entrée, appeler un service, rendre
                 un DTO. Aucune règle métier, aucun accès au repository.
   service/      la logique métier, et le seul endroit qui porte @Transactional.
   repository/   les interfaces Spring Data. Jamais appelées depuis un controller.
   dto/          ce qui entre et sort de l'API — jamais l'entité JPA elle-même,
                 sinon le schéma de la base devient le contrat public.
   entity/       les entités JPA.

BUILD :
   Maven  → mvn verify
   Gradle → ./gradlew check   (ou .\gradlew.bat check sur Windows)

JPA / HIBERNATE — les pièges qui coûtent le plus :
   • N+1 : une boucle qui traverse une relation LAZY déclenche une requête par
     élément. Corriger par @EntityGraph ou une requête JOIN FETCH, jamais en
     passant la relation en EAGER.
   • LazyInitializationException : l'entité a quitté la transaction. La réponse
     est de mapper vers un DTO DANS le service, pas d'ouvrir une session en vue.
   • equals/hashCode sur une entité : les baser sur une clé métier, jamais sur
     l'id généré — il est nul avant le flush.
   • @Transactional ne s'applique pas à un appel interne (this.methode()) :
     le proxy Spring n'est pas traversé.

QUALITÉ :
   • Injection par CONSTRUCTEUR, pas @Autowired sur les champs — un champ injecté
     ne peut pas être final et rend la classe intestable sans conteneur.
   • Pas de raw types (List au lieu de List<String> interdit).
   • Records pour les DTO et les valeurs immuables ; pas de classe à 6 getters.
   • Optional en type de RETOUR uniquement — jamais en paramètre ni en champ.
   • Exceptions : une exception métier typée par cas, traduite en statut HTTP
     par un @RestControllerAdvice. Jamais de catch(Exception) muet.
   • Kotlin : types nullables corrects, éviter !!, préférer ?: ou let.

TESTS :
   • JUnit 5 (Jupiter) pour tous les tests.
   • Mockito pour les mocks unitaires — mocker les collaborateurs, pas le sujet.
   • @DataJpaTest pour la couche repository, @WebMvcTest pour un controller seul,
     @SpringBootTest seulement quand le contexte entier est nécessaire (lent).
   • Testcontainers pour une vraie base en intégration, jamais H2 en mémoire si
     la prod est PostgreSQL — les dialectes divergent silencieusement.
   • JaCoCo pour la couverture (objectif > 80% métier).

CONFIGURATION :
   application.yml par profil (application-dev.yml, application-prod.yml).
   Jamais de secret en dur : variables d'environnement, avec un défaut qui
   échoue bruyamment plutôt qu'un défaut permissif.

VÉRIFICATION :
   mvn verify   ou   ./gradlew check
