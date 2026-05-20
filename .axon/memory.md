# Axon Memory — ai-agent
*Généré automatiquement. Ne pas éditer manuellement.*

## ENVIRONNEMENT UTILISATEUR
Dossier home : /home/kaine/
Projets personnels : /home/kaine/Documents/projets-perso/
Quand l'utilisateur dit "dans mon dossier projets-perso" ou "dans mes projets" → chemin absolu = /home/kaine/Documents/projets-perso/<nom-projet>

## 2026-04-27
Architecture Next.js 14 App Router : composants avec état (useState, useEffect) → "use client". Composants statiques (Header, Features) → Server Components par défaut.

## 2026-04-28
framer-motion 12.x : transition.ease doit être un tableau de nombres [0.4, 0, 0.2, 1] as const, pas une chaîne "easeInOut". Pour afficher des accolades JSX dans du JSX → entités HTML (&#123; &#125;).

## 2026-04-29
next.config.mjs : utiliser JSDoc /** @type {import('next').NextConfig} */ au lieu de import type pour éviter SyntaxError avec Turbopack. Images Unsplash → ajouter images.remotePatterns dans next.config.

## 2026-04-30
shoes-showcase-website : projet Next.js 16.2.4 + React 19.2.4 + Tailwind CSS v4 + Framer Motion + GSAP + ScrollTrigger + React Three Fiber. Design : noir #0a0a0a, orange #f97316. Assets dans /public/. Page produit dynamique /shoe/[id] avec modèle 3D GLB animé via GSAP ScrollTrigger.

## 2026-05-04
shoes-showcase-website audit — problèmes critiques : Hero.tsx (setState in useEffect + Math.random() in JSX), Navbar.tsx (setState in useEffect), async client component. Score 7.5/10.

## 2026-05-05
exo_cyber1-mécanismes-sécurité.html : barre de navigation (#navigation) masquée par défaut (display:none), affichée via JS dans initQuiz() et restartQuiz() avec style.display = 'flex'.

## 2026-05-06
TP3 VQE H2 (PennyLane) : distance d'équilibre 0.700 Å, énergie -1.136189 Ha. Ansatz hardware-efficient (Ry + CNOT, 2 couches), optimisation BFGS, 20 runs. Notebook : /home/kaine/Documents/EPF/quantum-computing/QbitSoft x EPF - TP3 - Version Etudiant.ipynb

## 2026-05-18
Présentation IA en entreprise 2025 : 29 slides, 7 sections. Fichiers : /tmp/slides/intelligence_artificielle_en_entreprise_.html et .pptx

## 2026-05-19
Projet MiloPlus : /home/kaine/projets-perso/miloplus (⚠ créé au mauvais chemin — devrait être /home/kaine/Documents/projets-perso/miloplus). Stack : Next.js 16.2.4 + Tailwind CSS, polices Syne + Inter, couleurs #ffffff/#111111/#c0392b, 4 sections (Hero, Plateforme 8 modules, IA terminal, Contact). Build OK.
