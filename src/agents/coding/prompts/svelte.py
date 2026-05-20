"""Svelte / SvelteKit specific prompt — Runes, SvelteKit routing."""

SVELTE_PROMPT = """\
━━ FRAMEWORK : SVELTE / SVELTEKIT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  SCAFFOLD — TOUJOURS VIA CLI, JAMAIS À LA MAIN :

    SvelteKit : shell_run("pnpm create svelte@latest <nom>")
                → Skeleton project · TypeScript ✓ · ESLint ✓ · Prettier ✓
    Puis shell_cd("<nom>") && shell_run("pnpm install")
    ❌ JAMAIS créer svelte.config.js / package.json à la main.

SVELTE 5 — RUNES (défaut) :
    • State      : let count = $state(0)
    • Derived    : let doubled = $derived(count * 2)
    • Effects    : $effect(() => { console.log(count) })
    • Props      : let { name, age = 18 } = $props()
    • Events     : <button onclick={() => count++}> — pas de on:click Svelte 4.
    ❌ Pas les stores Svelte 4 (writable/readable) pour le state local — utilise $state.
    ✅ Stores Svelte 4 encore valides pour le state global partagé entre composants.

SVELTEKIT ROUTING :
    • +page.svelte · +layout.svelte · +page.ts (load) · +page.server.ts (server load + actions).
    • Form actions dans +page.server.ts — préférer aux API routes pour les mutations.
    • API routes : src/routes/api/<route>/+server.ts → export const GET: RequestHandler = ...

TAILWIND AVEC SVELTEKIT :
    pnpm add -D tailwindcss postcss autoprefixer
    npx tailwindcss init -p
    Ajouter dans svelte.config.js : vitePlugin({ ... }) avec postcss: true.
    globals.css : @tailwind base; @tailwind components; @tailwind utilities;
"""
