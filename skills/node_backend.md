---
name: node_backend
description: Node.js Express NestJS Fastify REST API backend TypeScript JWT Prisma
aliases: [express, nestjs, node]
---

━━ STACK DÉTECTÉ : NODE.JS BACKEND ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   NestJS   → pnpm dlx @nestjs/cli new <nom>
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
   pnpm run build   ou   pnpm exec tsc --noEmit
   pnpm test

⚠ GESTIONNAIRE DE PAQUETS — une seule famille par projet :
  pnpm dlx <pkg> (jamais npx) · pnpm add (jamais npm install) · pnpm <script> (jamais npm run).
  Projet EXISTANT avec package-lock.json et sans pnpm-lock.yaml → c'est npm :
  utiliser npx / npm install / npm run. Vérifier avec shell_ls, ne jamais supposer.
