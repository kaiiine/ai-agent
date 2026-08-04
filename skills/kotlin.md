---
name: kotlin
description: Kotlin Ktor Spring Boot Gradle app from scratch existing repo continuation coroutines PostgreSQL Exposed JUnit MockK ktlint
aliases: [kt, ktor, kotlin-jvm, spring-kotlin]
---

━━ STACK: KOTLIN ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GOAL:
Build or continue production-ready Kotlin applications.

MODE DETECTION:
- If no Kotlin project exists: scaffold from scratch.
- If build.gradle.kts, settings.gradle.kts, pom.xml, src/main/kotlin, or src/test/kotlin exists: continue the existing repo.
- Never overwrite an existing project blindly.

EXISTING REPO — FIRST ACTIONS:
1. Read:
   - settings.gradle.kts
   - build.gradle.kts
   - gradle.properties
   - src/main/kotlin structure
   - README.md if present
2. Detect framework:
   - Ktor if Application.kt uses embeddedServer, routing, install(ContentNegotiation)
   - Spring Boot if @SpringBootApplication exists
   - CLI if main() + no server framework
3. Run verification before changes:
   - ./gradlew test or ./gradlew check
4. Preserve existing architecture, naming, packages, and dependency style.
5. Make minimal targeted changes.

FROM SCRATCH — DEFAULT CHOICE:
- Backend/API app → Ktor + Gradle Kotlin DSL
- Enterprise CRUD/API → Spring Boot Kotlin
- CLI/tooling app → Kotlin JVM + Clikt

FROM SCRATCH — REQUIRED STRUCTURE:
src/main/kotlin/
  Application.kt
  routes/
  services/
  repositories/
  models/
  dto/
  config/

src/test/kotlin/
  routes/
  services/

KOTLIN RULES:
- Prefer val over var.
- Use data classes for DTOs/value objects.
- Use sealed classes/interfaces for finite states.
- Avoid !! unless unavoidable and explained.
- Use explicit nullable types.
- Use constructor injection.
- Keep routes/controllers thin.
- Business logic goes in services.
- Persistence logic goes in repositories.

COROUTINES:
- Use suspend functions for async service/repository operations.
- Never use GlobalScope.
- Prefer coroutineScope/supervisorScope.
- Use Dispatchers.IO only for blocking IO.
- Use delay(), never Thread.sleep() inside coroutines.

KTOR DEFAULTS:
- Engine: Netty.
- Serialization: kotlinx.serialization.
- JSON: ContentNegotiation.
- Routing split by feature.
- Error handling via StatusPages.
- Config via application.conf or environment variables.
- Never expose stack traces in production responses.

SPRING BOOT KOTLIN DEFAULTS:
- Constructor injection only.
- Controllers stay thin.
- @Transactional on services, not controllers.
- Use configuration properties.
- Avoid field injection.
- Use Spring Boot Test only for integration tests.

DATABASE:
- PostgreSQL by default for API apps.
- Use Exposed or JOOQ for Ktor.
- Use Spring Data JPA for Spring Boot unless user asks otherwise.
- Never hardcode credentials.
- Use env vars for DB URL/user/password.

TESTING:
- JUnit 5 by default.
- MockK for mocks.
- Ktor: testApplication { ... }.
- Spring: @WebMvcTest for controllers, @SpringBootTest only for integration.
- Add tests for new service logic.

QUALITY:
- Use ktlint or detekt if already configured.
- Do not introduce a new linter if the repo has a clear existing standard.
- Keep package names consistent.
- Avoid large files; split by feature.

COMMANDS:
Existing repo:
  ./gradlew test
  ./gradlew check
  ./gradlew build

If wrapper missing:
  gradle test
  gradle check

SECURITY:
- Never commit secrets.
- Do not log Authorization, cookies, tokens, passwords, API keys.
- Validate external input.
- Use httpOnly secure cookies or Authorization: Bearer depending on architecture.

VERIFICATION BEFORE CLOSING:
- Run ./gradlew check if available.
- If check is too broad, run ./gradlew test.
- Summarize changed files and why.