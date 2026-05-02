"""Frontend stack prompt — React / Next.js / Angular / Vue / Svelte / Three.js."""

FRONTEND_PROMPT = """\
━━ STACK DÉTECTÉ : FRONTEND ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING (nouveau projet) :
   Next.js  → pnpm create next-app@latest <nom> --yes --typescript --tailwind --app --src-dir
   Vite     → pnpm create vite@latest <nom> -- --template react-ts
   Angular  → npx @angular/cli new <nom> --style=scss --routing
   Vue      → pnpm create vue@latest <nom>
   Svelte   → pnpm create svelte@latest <nom>
   3D/immersif → pnpm create vite@latest <nom> -- --template react-ts  puis pnpm add three @react-three/fiber @react-three/drei

LIBRAIRIES À INSTALLER D'EMBLÉE sur tout projet vitrine / marketing / portfolio :
   pnpm add framer-motion clsx tailwind-merge
   pnpm add @radix-ui/react-slot lucide-react
   pnpm add lenis                          # smooth scroll sans conflit WebGL
   Pour les polices premium → next/font (Geist, Inter, Cal Sans)

━━ DESIGN SYSTEM — EN PREMIER, avant tout composant ━━━━━━━━━━━━━━━━━━━━━━━━━━

   • Édite globals.css + tailwind.config(.ts) AVANT les composants.
   • Palette 3-5 couleurs en tokens CSS HSL (1 primaire, 2-3 neutres, 1-2 accents).
   ❌ className="text-white bg-[#ff6600]"
   ✅ className="text-foreground bg-primary"

   FOND DARK RICHE — ne jamais laisser un bg #000 ou bg-gray-950 nu :
   globals.css :
     body {
       background: radial-gradient(ellipse 80% 80% at 50% -20%, hsla(217,89%,61%,0.18), transparent),
                   radial-gradient(ellipse 60% 60% at 80% 80%, hsla(280,70%,50%,0.12), transparent),
                   hsl(222 84% 5%);
     }

   TEXTURE GRID (overlay SVG inline, z-0) :
     .bg-grid::before {
       content: "";
       position: absolute; inset: 0; z-index: 0;
       background-image: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%239C92AC' fill-opacity='0.04'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
     }

   BRUIT SVG (grain — ajouter sur hero/card sections) :
     .noise::after {
       content: "";
       position: absolute; inset: 0; z-index: 0; opacity: .035; border-radius: inherit;
       background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
     }

━━ CSS EFFECTS AVANCÉS — À UTILISER SYSTÉMATIQUEMENT ━━━━━━━━━━━━━━━━━━━━━━━━

GLASSMORPHISM (cartes, modals, badges) :
   .glass {
     background: rgba(255,255,255,0.04);
     backdrop-filter: blur(12px) saturate(160%);
     -webkit-backdrop-filter: blur(12px) saturate(160%);
     border: 1px solid rgba(255,255,255,0.08);
     border-radius: 16px;
   }
   Tailwind : className="bg-white/[0.04] backdrop-blur-xl border border-white/[0.08] rounded-2xl"

BORDURE GRADIENT ANIMÉE avec @property (badge, card, hero CTA) :
   globals.css :
     @property --angle {
       syntax: '<angle>'; initial-value: 0deg; inherits: false;
     }
     .border-gradient {
       --border-width: 1px;
       border: var(--border-width) solid transparent;
       background: linear-gradient(hsl(222 84% 5%), hsl(222 84% 5%)) padding-box,
                   conic-gradient(from var(--angle), #6366f1, #8b5cf6, #a78bfa, #6366f1) border-box;
       animation: rotate-gradient 4s linear infinite;
     }
     @keyframes rotate-gradient { to { --angle: 360deg; } }

TEXT SHIMMER (titres hero) :
   globals.css :
     .shimmer {
       background: linear-gradient(90deg, #6366f1 0%, #a78bfa 40%, #e2e8f0 60%, #6366f1 100%);
       background-size: 200% auto;
       -webkit-background-clip: text;
       background-clip: text;
       color: transparent;
       animation: shimmer 3s linear infinite;
     }
     @keyframes shimmer { to { background-position: 200% center; } }
   Tailwind + motion variant :
     <span className="bg-gradient-to-r from-violet-400 via-purple-300 to-slate-200
                      bg-[length:200%_auto] bg-clip-text text-transparent
                      animate-[shimmer_3s_linear_infinite]">Titre</span>

GLOW / SPOTLIGHT (hover sur carte ou hero) :
   Au survol injecter un radial-gradient centré sur cursor coords (onMouseMove → CSS vars --mx --my) :
     style={{ background: `radial-gradient(600px circle at var(--mx) var(--my), rgba(99,102,241,0.12), transparent 60%)` }}

━━ FRAMER-MOTION — PATTERNS AVANCÉS OBLIGATOIRES ━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. SCROLL-LINKED ANIMATIONS (useScroll + useTransform + useSpring) :
   "use client"
   import { useScroll, useTransform, useSpring, motion } from "framer-motion"

   const { scrollYProgress } = useScroll()
   const smoothProgress = useSpring(scrollYProgress, { stiffness: 80, damping: 20, restDelta: 0.001 })

   // Chaîner plusieurs valeurs depuis un seul scroll :
   const y       = useTransform(smoothProgress, [0, 1], [0, -80])
   const opacity = useTransform(smoothProgress, [0, 0.2, 0.8, 1], [1, 1, 0.8, 0])
   const scale   = useTransform(smoothProgress, [0, 0.5], [1, 0.95])
   <motion.div style={{ y, opacity, scale }} />

   // Barre de progression globale :
   <motion.div
     style={{ scaleX: smoothProgress }}
     className="fixed top-0 left-0 right-0 h-1 bg-gradient-to-r from-violet-500 to-purple-500 origin-left z-50"
   />

2. useInView pour stagger d'entrée :
   import { useInView } from "framer-motion"
   const ref = useRef(null)
   const isInView = useInView(ref, { once: true, margin: "-100px" })
   <motion.div
     ref={ref}
     initial={{ opacity: 0, y: 40 }}
     animate={isInView ? { opacity: 1, y: 0 } : {}}
     transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
   />

   Stagger de liste (variants parent + enfants) :
   const container = { hidden: {}, show: { transition: { staggerChildren: 0.08 } } }
   const item = { hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0, transition: { duration: 0.5 } } }
   <motion.ul variants={container} initial="hidden" animate="show">
     {items.map(i => <motion.li key={i} variants={item}>{i}</motion.li>)}
   </motion.ul>

3. AnimatePresence pour les transitions de page/modal :
   <AnimatePresence mode="wait">
     <motion.div
       key={route}
       initial={{ opacity: 0, y: 12 }}
       animate={{ opacity: 1, y: 0 }}
       exit={{ opacity: 0, y: -12 }}
       transition={{ duration: 0.25 }}
     />
   </AnimatePresence>

4. CARTE 3D TILT (perspective au survol) :
   const x = useMotionValue(0), y = useMotionValue(0)
   const rotateX = useSpring(useTransform(y, [-0.5, 0.5], [8, -8]), { stiffness: 300, damping: 30 })
   const rotateY = useSpring(useTransform(x, [-0.5, 0.5], [-8, 8]), { stiffness: 300, damping: 30 })
   function onMouseMove(e) {
     const rect = e.currentTarget.getBoundingClientRect()
     x.set((e.clientX - rect.left) / rect.width - 0.5)
     y.set((e.clientY - rect.top) / rect.height - 0.5)
   }
   <motion.div
     style={{ rotateX, rotateY, transformStyle: "preserve-3d", perspective: 800 }}
     onMouseMove={onMouseMove}
     onMouseLeave={() => { x.set(0); y.set(0) }}
   />

5. FLOATING PARTICLES — composant utilitaire à créer dans components/ui/floating-particles.tsx :
   Particules flottantes avec positions aléatoires, animations loop indépendantes :
   const particles = Array.from({ length: 20 }, (_, i) => ({
     id: i,
     x: Math.random() * 100, y: Math.random() * 100,
     size: Math.random() * 3 + 1,
     duration: Math.random() * 8 + 6,
     delay: Math.random() * 4,
   }))
   // Rendu dans un div absolute inset-0 pointer-events-none :
   particles.map(p => (
     <motion.div
       key={p.id}
       className="absolute rounded-full bg-violet-400/30"
       style={{ left: `${p.x}%`, top: `${p.y}%`, width: p.size, height: p.size }}
       animate={{ y: [0, -30, 0], opacity: [0, 0.7, 0] }}
       transition={{ duration: p.duration, delay: p.delay, repeat: Infinity, ease: "easeInOut" }}
     />
   ))

━━ COMPOSANTS UTILITAIRES — CRÉER SYSTÉMATIQUEMENT ━━━━━━━━━━━━━━━━━━━━━━━━━

components/ui/section-divider.tsx :
   Ligne SVG ondulée ou dégradé de séparation entre sections (pas de <hr> nu).
   <div className="relative h-px w-full my-0">
     <div className="absolute inset-0 bg-gradient-to-r from-transparent via-violet-500/50 to-transparent" />
   </div>

components/ui/badge.tsx :
   Badge pill glassmorphism + border-gradient optionnel :
   <span className="inline-flex items-center gap-1.5 rounded-full px-3 py-1
                    text-xs font-medium tracking-wide
                    bg-violet-500/10 border border-violet-500/20 text-violet-300">

components/ui/animated-counter.tsx :
   Compteur animé avec useSpring sur une valeur numérique.

━━ TERMINAL DEMO — PATTERN COMPLET ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Pour les sections "comment ça marche" ou "démo produit" — JAMAIS une capture statique.
Créer un terminal animé multi-phase dans components/terminal-demo.tsx :

Types de lignes : "command" | "output" | "success" | "error" | "diff_add" | "diff_remove" | "comment"
Structure :
  const PHASES: Phase[] = [
    { id: 0, lines: [
        { type: "command",    text: "$ axon \"améliore le composant Hero\"", delay: 0 },
        { type: "comment",    text: "# Analyse du projet en cours...",       delay: 600 },
        { type: "output",     text: "  → 3 fichiers trouvés",                delay: 1000 },
    ]},
    { id: 1, lines: [
        { type: "diff_remove", text: "-  <h1 className='text-2xl'>Titre</h1>", delay: 0 },
        { type: "diff_add",    text: "+  <h1 className='shimmer text-5xl font-bold'>Titre</h1>", delay: 300 },
    ]},
    { id: 2, lines: [
        { type: "success",    text: "✓ Build réussi — 0 erreurs",            delay: 0 },
    ]},
  ]

Animations :
  • Chaque ligne apparaît avec AnimatePresence + stagger sur le delay
  • Curseur clignotant en fin de phase active (animate={{ opacity: [1,0,1] }} transition={{ repeat: Infinity }})
  • Auto-avancement de phase après N ms ou sur bouton "Étape suivante"
  • diff_add → bg-emerald-950/40 text-emerald-400, diff_remove → bg-red-950/40 text-red-400
  • Scrollbar custom dark sur le terminal (max-h-64 overflow-y-auto)
  • Header terminal : 3 dots (rouge/jaune/vert) + titre centré

━━ SECTIONS HERO — RECETTE COMPLÈTE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Structure obligatoire d'un hero de qualité prod :
  1. <FloatingParticles />  (absolute inset-0 z-0)
  2. Fond grid ou noise (::before)
  3. Badge pill animé avec AnimatePresence (ex: "Nouveau — v2.0 disponible →")
  4. Titre H1 avec texte shimmer OU gradient clip + animation entrance
  5. Sous-titre 1-2 lignes, couleur muted, max-w-xl mx-auto text-center
  6. 2 CTA : primary (bg-primary) + secondary (ghost/glass)
  7. Social proof : avatars empilés + "X+ utilisateurs" ou logos clients
  8. Preview/screenshot : section terminale animée OU image avec border-gradient + drop-shadow
  → Toute la section dans un <section className="relative overflow-hidden min-h-screen flex items-center">

━━ THREE.JS & 3D IMMERSIF ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Stack : @react-three/fiber (R3F) + @react-three/drei + three.
Post-processing : @react-three/postprocessing.
Scroll 3D : gsap + @gsap/react ou @react-three/drei ScrollControls.

RÈGLES R3F :
   • Canvas dans composant client ("use client" Next.js).
   • useFrame() pour animations — jamais requestAnimationFrame direct.
   • Géométries lourdes → useMemo(). Matériaux partagés → useRef() hors composant.
   • Lumières : ambientLight (0.3-0.5) + directionalLight pour ombres.
   • ombres : shadowMap sur Canvas, castShadow + receiveShadow sur meshes.
   • <Suspense> + Loader pour gltf, <PerformanceMonitor> de drei.

MOTIFS 3D COURANTS :
   • Fond de particules : useFrame(({ clock }) => { points.current.rotation.y = clock.elapsed * 0.05 })
   • Scroll storytelling : useScroll() de drei + position/rotation interpolée.
   • Shader custom : <shaderMaterial> avec uniforms (uTime, uMouse) — GLSL inline.
   • Modèle animé : useGLTF() + useAnimations() de drei.
   • Environnement HDR : <Environment preset="city"|"sunset"> de drei.
   • Tilt distorsion survol : vertex shader avec uMouse uniforms.

POST-PROCESSING :
   <EffectComposer>
     <Bloom luminanceThreshold={0.3} intensity={1.5} />
     <ChromaticAberration offset={[0.002, 0.002]} />
     <Vignette darkness={0.5} />
   </EffectComposer>

PERF :
   • > 100 objets identiques → <Instances> ou InstancedMesh.
   • dpr={[1, 2]} sur Canvas (pas de 3x mobile).
   • dispose() géométries/matériaux dans cleanup useEffect.

━━ RÈGLES GÉNÉRALES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

COMPOSANTS :
   • Atomiques < 150 lignes JSX, HTML sémantique (<main> <header> <section> <article>).
   • Sections aérées : py-20 md:py-32, max-w-6xl mx-auto px-6.
   • Typographie : tracking-tight sur titres, font-medium sur sous-titres.
   • Hover transitions 150-200ms cubic-bezier(0.16,1,0.3,1).
   • Responsive mobile-first partout.
   • Fetching : SWR ou RSC — jamais fetch() dans useEffect.

SEO :
   • <title> < 60 car., <meta description> < 160 car., 1 seul H1, alt sur images.

VÉRIFICATION VISUELLE (étape 6b obligatoire) :
   shell_run("pkill -f 'next dev' || true && pnpm dev > /tmp/dev.log 2>&1 &")
   shell_run("sleep 5") puis browser_screenshot("http://localhost:3000")
   Corriger chaque audit.issue avant de passer à la suite :
   • text_cropped        → agrandir le conteneur, retirer overflow:hidden
   • not_centered        → ajouter mx-auto, vérifier max-w + padding
   • outside_viewport    → corriger flex/grid ou largeur fixe
   • empty_section       → contenu manquant ou composant non rendu
   • broken_image        → vérifier src et chemin public/

VÉRIFICATION BUILD :
   pnpm run build   ou   npx tsc --noEmit
"""
