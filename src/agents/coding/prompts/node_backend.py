"""Node.js backend stack prompt — Express / NestJS / Fastify."""

NODE_BACKEND_PROMPT = """\
━━ STACK DÉTECTÉ : NODE.JS BACKEND ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   NestJS   → npx @nestjs/cli new <nom>
   Express  → pnpm init && pnpm add express && pnpm add -D typescript @types/express ts-node-dev
   Fastify  → pnpm create fastify@latest <nom>

ARCHITECTURE :
   routes/controllers → services/use-cases → repositories/DAL → schemas/DTOs
   Jamais de logique métier dans les controllers.

AUTH :
   • JWT avec httponly cookies ou sessions — jamais localStorage.
   • Refresh token rotation.

BASE DE DONNÉES :
   • ORM avec migrations versionnées (Prisma, TypeORM, Drizzle).
   • Transactions pour toute opération multi-tables.

VALIDATION :
   • Zod (préféré), Joi, ou class-validator (NestJS).
   • Valider TOUTE entrée à la frontière (body, params, query, headers).

TESTS :
   • Unitaires : Jest ou Vitest.
   • Intégration : vraie BDD de test, pas de mock repository.

ASYNC :
   • Handlers async par défaut.
   • Toujours await les Promises, jamais .then().catch() imbriqués.
   • Wrapper global d'erreurs pour éviter les unhandled rejections.

VÉRIFICATION :
   pnpm run build   ou   npx tsc --noEmit
   pnpm test
"""
