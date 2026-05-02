"""Java / Kotlin stack prompt — Spring Boot / Ktor / Gradle / Maven."""

JAVA_PROMPT = """\
━━ STACK DÉTECTÉ : JAVA / KOTLIN ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   Spring Boot → https://start.spring.io (ou spring init CLI)
   Ktor        → https://start.ktor.io

BUILD :
   Maven  → mvn verify
   Gradle → ./gradlew check   (ou .\gradlew.bat check sur Windows)

STYLE :
   Java   → Google Java Format
   Kotlin → ktlint

TESTS :
   • JUnit 5 (Jupiter) pour tous les tests.
   • Mockito pour les mocks unitaires.
   • JaCoCo pour la couverture (objectif > 80% métier).
   • Spring Boot Test / Ktor TestEngine pour les tests d'intégration.

QUALITÉ :
   • Pas de raw types Java (List au lieu de List<String> interdit).
   • Kotlin : utiliser les types nullables correctement, éviter !!, préférer ?: ou let.
   • Dépendances injectées via constructeur (pas de @Autowired sur les champs).
   • Transactions : @Transactional sur les méthodes de service, pas sur les controllers.

VÉRIFICATION :
   mvn verify   ou   ./gradlew check
"""
