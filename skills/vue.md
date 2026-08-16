---
name: vue
description: Vue Nuxt Composition API Pinia TypeScript pnpm
aliases: [nuxt, vue3]
---

━━ FRAMEWORK : VUE / NUXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  SCAFFOLD — TOUJOURS VIA CLI, JAMAIS À LA MAIN :

    Vue (SPA) : shell_run("pnpm create vue@latest <nom>")
                → Sélectionner : TypeScript ✓ · Vue Router ✓ · Pinia ✓ · ESLint ✓
    Nuxt (SSR): shell_run("pnpm create nuxt@latest <nom>")
    Puis shell_cd("<nom>") && shell_run("pnpm install")
    ❌ JAMAIS créer vite.config / package.json à la main.

COMPOSITION API — TOUJOURS <script setup lang="ts"> :
    • ref(), reactive(), computed(), watch(), watchEffect(), onMounted()
    • defineProps<{ title: string }>() · defineEmits<{ click: [id: number] }>()
    • composables/ pour la logique réutilisable : useMyLogic() → retourne refs + méthodes.
    ❌ Jamais Options API sauf héritage legacy.

PINIA (state global) :
    • defineStore('id', () => { ... }) — setup syntax, pas options syntax.
    • State : const count = ref(0) · Actions : fonctions normales · Getters : computed().
    • storeToRefs() pour destructurer sans perdre la réactivité.

NUXT (si projet SSR/fullstack) :
    • useAsyncData() / useFetch() pour le data fetching serveur.
    • composables/ auto-importés · plugins/ pour modules globaux.
    • server/api/<route>.ts pour les API routes côté serveur.
    • Metadata : useHead({ title, meta }) ou definePageMeta({ layout, middleware }).

TAILWIND AVEC VUE/NUXT :
    Vue  : pnpm add -D tailwindcss postcss autoprefixer && pnpm dlx tailwindcss init -p
    Nuxt : pnpm add -D @nuxtjs/tailwindcss puis modules: ['@nuxtjs/tailwindcss'] dans nuxt.config.ts

⚠ GESTIONNAIRE DE PAQUETS — une seule famille par projet :
  pnpm dlx <pkg> (jamais npx) · pnpm add (jamais npm install) · pnpm <script> (jamais npm run).
  Projet EXISTANT avec package-lock.json et sans pnpm-lock.yaml → c'est npm :
  utiliser npx / npm install / npm run. Vérifier avec shell_ls, ne jamais supposer.
