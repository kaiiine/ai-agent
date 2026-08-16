---
name: nextjs
description: Next.js App Router RSC server components pnpm create next-app TypeScript Tailwind
aliases: [next, next.js, app router]
---

━━ FRAMEWORK : NEXT.JS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  SCAFFOLD — TOUJOURS VIA CLI, JAMAIS À LA MAIN :

    NOUVEAU PROJET → UNE SEULE COMMANDE :
    shell_run("pnpm create next-app@latest <nom> --yes --typescript --tailwind --app --src-dir --import-alias '@/*'", timeout=180)
    Puis shell_cd("<nom>") → customise par-dessus ce que le CLI a généré.
    ❌ JAMAIS créer package.json / tsconfig / next.config.ts / globals.css manuellement.
    ❌ JAMAIS pnpm install avant le scaffold — le CLI le fait.
    ⚠ VERSION : `create next-app@latest` installe la DERNIÈRE (Next 16 + Tailwind 4 +
      React 19 à ce jour). Si la spec impose une version, downgrader IMMÉDIATEMENT
      après le scaffold, avant d'écrire le moindre composant :
        shell_run("pnpm add next@14 react@18 react-dom@18 && pnpm add -D tailwindcss@3 postcss autoprefixer")
      Écrire des composants d'abord puis downgrader casse la config déjà produite.
    Si dossier déjà existant et pollué (node_modules/dist/build sans spec) :
      → shell_run("rm -rf node_modules .next pnpm-lock.yaml") d'abord.
    Si dossier contient des fichiers utilisateur (spec.md, README, assets…) :
      ❌ JAMAIS rm -rf * — la spec est irremplaçable
      ✅ Scaffold dans .scaffold/, puis rapatrie :
           shell_run("pnpm create next-app@latest .scaffold --yes --typescript --tailwind --app --src-dir --import-alias '@/*'", timeout=180)
           shell_run("cp -r .scaffold/. . && rm -rf .scaffold")
         → spec.md reste intacte, le projet est opérationnel dans le dossier courant.

GESTIONNAIRE DE PAQUETS — UNE SEULE FAMILLE PAR PROJET :
    Le scaffold utilise pnpm, donc TOUT le projet reste en pnpm. Mélanger les
    familles crée un second lockfile et un arbre de dépendances divergent.
      exécuter un binaire distant   pnpm dlx <pkg>     (jamais npx)
      installer                     pnpm add <pkg>     (jamais npm install)
      lancer un script              pnpm <script>      (jamais npm run)
    Si le projet EXISTANT a un package-lock.json et pas de pnpm-lock.yaml,
    c'est npm : utiliser alors npx / npm install / npm run. Vérifier avec
    shell_ls avant la première commande, ne jamais le supposer.

POST-SCAFFOLD (nouveau projet) — DANS CET ORDRE :
    1. shell_cd("<nom>")
    2. dev_explain("Scaffold terminé. Je vais maintenant installer les libs et configurer le design system.")
    3. shell_run("pnpm add lucide-react clsx tailwind-merge")                    ← TOUJOURS
    4. Si la spec n'interdit pas les animations :
       shell_run("pnpm add framer-motion lenis")                                 ← CONDITIONNEL
       ❌ Si spec dit "no animations" / "pas de framer-motion" → ne pas installer
    5. shell_run("pnpm add @radix-ui/react-slot")                              ← TOUJOURS
    6. shell_run("pnpm dlx shadcn@latest init -d", timeout=180)             ← TOUJOURS
       shell_run("pnpm dlx shadcn@latest add button card input textarea select badge dialog sheet separator", timeout=120)
    ⚠ Exception : si spec dit "no UI library" / "Pas de shadcn/ui" / "custom components only" :
       → Sauter les étapes 5 et 6.
       ❌ JAMAIS importer depuis @/components/ui/ dans AUCUN fichier si shadcn n'est pas installé.
          → Utiliser des éléments HTML natifs stylisés Tailwind : <button className="px-4 py-2 ...">
          → Vérifier avant le build : shell_run("grep -r '@/components/ui' src/ | head -5 || echo OK")
    7. propose_file_change sur globals.css uniquement (tokens CSS + @theme pour les fonts)
       ❌ JAMAIS créer tailwind.config.ts — Tailwind v4 ignore ce fichier silencieusement.
    8. propose_file_change sur src/app/layout.tsx (next/font wiring + Lenis smooth scroll)

⚠️  TAILWIND v4 — DIFFÉRENCES CRITIQUES (détecté si package.json contient "@tailwindcss/postcss") :
    ❌ JAMAIS créer tailwind.config.ts — il est silencieusement ignoré par Tailwind v4.
    ✅ Toute la config (couleurs, fonts, spacing custom) se fait dans globals.css via @theme {} :

    @import "tailwindcss";

    @theme {
      --color-accent: #22c55e;
      --color-background: #0d1117;
      --color-foreground: #f0f6ff;
      --accent-rgb: 34 197 94;
    }

    @theme inline {
      --font-display: var(--font-syne);
      --font-sans:    var(--font-inter);
    }

    → font-display et font-sans sont ensuite utilisables comme classes Tailwind directement.
    → ❌ JAMAIS theme.extend.fontFamily dans un fichier .ts — ça n'a aucun effet en v4.

PROJET EXISTANT — VÉRIFIER ET COMPLÉTER LE SETUP :
    ⚠️  OBLIGATOIRE avant tout travail sur un projet existant :
    shell_run("cat package.json")  ← vérifie les dépendances installées
    Puis installe tout ce qui manque selon le type de projet :

    Pour un projet VITRINE / LANDING PAGE / APP UI :
    • framer-motion absent  → shell_run("pnpm add framer-motion")
    • lenis absent          → shell_run("pnpm add lenis")
    • lucide-react absent   → shell_run("pnpm add lucide-react clsx tailwind-merge")
    • shadcn non initialisé → shell_run("pnpm dlx shadcn@latest init -d", timeout=180)

    Pour un projet avec des COMPOSANTS UI :
    • Ajouter les composants shadcn nécessaires :
      shell_run("pnpm dlx shadcn@latest add button input textarea select card badge", timeout=120)

    ❌ Ne JAMAIS supposer que les libs sont installées — toujours lire package.json d'abord.
    ❌ Ne JAMAIS sauter cette étape même si le projet semble "déjà configuré".

━━ LAYOUT RESPONSIVE — ANTI-BUGS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SIDEBAR / PANEL FIXE
  ❌ fixed retire l'élément du flux → le contenu passe dessous sans compensation.
  ✅ Flex sans fixed (recommandé) :
       <div className="flex h-screen overflow-hidden">
         <aside className="w-60 flex-shrink-0 overflow-y-auto">
         <div className="flex-1 flex flex-col overflow-hidden min-w-0">
  ✅ Si fixed requis (z-index mobile) → md:ml-60 OBLIGATOIRE sur le wrapper contenu.

OVERFLOW & SCROLL
  ❌ Ne jamais mettre overflow-hidden et overflow-y-auto sur le même élément.
  ✅ Wrapper : overflow-hidden · Zone scrollable : overflow-y-auto sur l'enfant direct.

FLEX AVEC ÉLÉMENTS DE LARGEUR FIXE
  ❌ flex-1 seul sans min-w-0 → les enfants peuvent dépasser la zone.
  ✅ Éléments fixes : flex-shrink-0 · Éléments flexibles : flex-1 min-w-0.

POSITION ABSOLUTE / FIXED
  Toujours vérifier l'impact sur le flux parent. Documenter le z-index (z-10 sidebar, z-50 modal…).
  Un élément fixed dans un flex parent = invisible pour le flux — compenser ou ne pas mélanger.

FULL HEIGHT LAYOUT
  ✅ h-screen sur le root, h-full sur les enfants.
  ❌ Jamais height: 100vh sur un enfant d'un élément déjà en h-screen → double viewport.

RESPONSIVE SIDEBAR
  ✅ Desktop : sidebar visible (md:flex ou md:block).
  ✅ Mobile : drawer/overlay (hidden md:hidden sur le drawer, hamburger visible).
  ❌ Jamais de sidebar fixed visible sur mobile sans overlay + z-index + bouton de fermeture.

━━ STANDARD DE QUALITÉ VISUELLE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

POUR TOUT PROJET UI / LANDING PAGE / APPLICATION WEB :
Le résultat doit atteindre le niveau visuel de Vercel, Linear, Stripe ou Liveblocks.
Ce n'est pas une métaphore — c'est le standard minimum.

    TYPOGRAPHIE :
    • Hiérarchie tranchée : un h1 à 5-8rem, sous-titre à 1.25rem, body à 1rem
    • Headings : font Syne ou équivalent display — jamais Arial/système
    • Tracking tight sur les grands titres (tracking-tight ou letter-spacing: -0.03em)
    • Line-height serré sur les titres (leading-none ou leading-tight)

    ANIMATIONS — JAMAIS UNE PAGE STATIQUE :
    • Tout élément above-the-fold : animation d'entrée (fade + slide, 0.4-0.6s)
    • Listes de features/modules : stagger animation (délai de 0.06-0.1s entre items)
    • Sections en scroll : whileInView avec viewport once: true
    • Hover sur les cartes et liens : micro-interaction obligatoire

    HERO SECTION :
    • La colonne droite ne peut PAS être des <div> vides ou des placeholders gris
    • Afficher : un vrai mockup produit, une interface animée, des metrics réelles,
      ou un screenshot stylisé — jamais du "contenu à venir"
    • Le hero DOIT donner envie d'en savoir plus en moins de 3 secondes

    ESPACEMENTS ET LAYOUT :
    • Sections : py-24 à py-32 minimum
    • Grille : max-w-7xl mx-auto px-6 sur tous les containers
    • Jamais deux sections avec le même fond et la même densité visuelle

    DÉTAILS QUI FONT LA DIFFÉRENCE :
    • smooth scroll : Lenis (wrapper dans layout.tsx)
    • gradient text : bg-gradient-to-r from-… to-… bg-clip-text text-transparent
    • séparateurs : <div className="h-px bg-gradient-to-r from-transparent via-border to-transparent" />
    • icônes : lucide-react — jamais d'emojis dans du UI
    • scroll progress bar en haut de page avec useScroll de framer-motion

━━ EFFETS VISUELS AVANCÉS — À UTILISER PAR DÉFAUT ━━━━━━━━━━━━━━━━━━━━━━━━━━━

    Ces effets distinguent un site "fonctionnel" d'un site "impressionnant".
    Appliquer par défaut sauf si spec dit "flat", "minimal", "no-blur", "light theme".

    GLASSMORPHISME (cards, hero-card, nav) :
        className="backdrop-blur-xl bg-white/5 border border-white/10
                   shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] rounded-xl"
        → hero-card produit, cards de features, navigation blur au scroll

    GLOW SUR CTA :
        className="bg-accent shadow-[0_0_40px_rgba(192,57,43,0.4)]
                   hover:shadow-[0_0_80px_rgba(192,57,43,0.6)]
                   transition-shadow duration-300"
        Adapter la valeur rgba à la couleur --accent du projet.
        Ajouter --accent-rgb dans les tokens CSS pour réutilisation :
          --accent-rgb: 192 57 43;  (sans virgules — compatible oklch/rgb Tailwind)

    GRADIENT TEXT H1 :
        className="bg-gradient-to-br from-foreground via-foreground/80 to-foreground/50
                   bg-clip-text text-transparent"

    RADIAL GLOW DE FOND (hero) :
        <div className="absolute inset-0 pointer-events-none
          bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,
          rgba(var(--accent-rgb),0.15),transparent)]" />

    BENTO GRID (features section avec rythme visuel) :
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2 backdrop-blur-xl bg-white/5 border border-white/10 p-8">
          <div className="backdrop-blur-xl bg-white/5 border border-white/10 p-8">
        → Alterner md:col-span-2 / col-span-1 pour briser la monotonie des grilles

    GLOW ICON (lucide-react avec aura colorée) :
        <div className="p-3 rounded-lg bg-accent/10 shadow-[0_0_20px_rgba(var(--accent-rgb),0.3)]">
          <Icon className="text-accent" size={24} />
        </div>

━━ FRAMER MOTION — PATTERNS OBLIGATOIRES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

"use client" obligatoire sur tout fichier utilisant motion.
Séparer les composants Server/Client : metadata dans page.tsx (server), animations dans un composant client.

ENTRÉE SIMPLE (fade + slide up) :
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
    >

HERO ENTRANCE (chaque élément décalé) :
    <motion.h1
      initial={{ opacity: 0, y: 32 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.1, ease: [0.22, 1, 0.36, 1] }}
    >

STAGGER (liste d'items — modules, features, cards) :
    const container = {
      hidden: {},
      show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } }
    }
    const item = {
      hidden: { opacity: 0, y: 20 },
      show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] } }
    }
    <motion.ul variants={container} initial="hidden" whileInView="show" viewport={{ once: true }}>
      {items.map(i => <motion.li key={i.id} variants={item}>{…}</motion.li>)}
    </motion.ul>

HOVER CARD (lift effect) :
    <motion.div
      whileHover={{ y: -4, scale: 1.01 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
    >

SCROLL PROGRESS BAR :
    const { scrollYProgress } = useScroll()
    <motion.div
      style={{ scaleX: scrollYProgress }}
      className="fixed top-0 h-0.5 w-full origin-left bg-accent z-50"
    />

LENIS SETUP (dans src/components/SmoothScroll.tsx) :
    "use client"
    import { useEffect } from "react"
    import Lenis from "lenis"
    export function SmoothScroll({ children }: { children: React.ReactNode }) {
      useEffect(() => {
        const lenis = new Lenis({ duration: 1.2, easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)) })
        function raf(time: number) { lenis.raf(time); requestAnimationFrame(raf) }
        requestAnimationFrame(raf)
        return () => lenis.destroy()
      }, [])
      return <>{children}</>
    }
    Puis dans layout.tsx : <SmoothScroll>{children}</SmoothScroll>

━━ GSAP — QUAND L'UTILISER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GSAP est complémentaire à Framer Motion pour ce qu'il fait mieux :
    • Parallax scroll (GSAP ScrollTrigger scrub)
    • Texte animé lettre par lettre / mot par mot (SplitText)
    • Compteurs (numbers counting up to a value)
    • Canvas / WebGL / Three.js / React Three Fiber
    • Séquences multi-étapes avec timeline

GSAP SETUP (avec useGSAP de @gsap/react — jamais useEffect) :
    shell_run("pnpm add gsap @gsap/react")
    import { gsap } from "gsap"
    import { ScrollTrigger } from "gsap/ScrollTrigger"
    import { useGSAP } from "@gsap/react"
    gsap.registerPlugin(ScrollTrigger)  ← une fois dans layout.tsx ou le composant racine

PARALLAX :
    const ref = useRef(null)
    useGSAP(() => {
      gsap.to(ref.current, {
        yPercent: -20, ease: "none",
        scrollTrigger: { trigger: ref.current, start: "top bottom", end: "bottom top", scrub: true }
      })
    }, { scope: ref })

COUNTER :
    useGSAP(() => {
      gsap.from(el.current, {
        textContent: 0, duration: 2, ease: "power1.out",
        snap: { textContent: 1 },
        scrollTrigger: { trigger: el.current, start: "top 80%" }
      })
    })

━━ SHADCN/UI — CONVENTIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Ajouter seulement les composants nécessaires :
    pnpm dlx shadcn@latest add button input textarea select card badge separator

Utilisation :
    <Button size="lg" variant="default">CTA principal</Button>
    <Button variant="outline">CTA secondaire</Button>
    Pour formulaires : Form + FormField + Input + Textarea + Button

━━ APP ROUTER — DÉFAUT ABSOLU ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    • Toujours App Router — jamais Pages Router sauf si explicitement demandé.
    • Server Components par défaut. "use client" SEULEMENT si : hooks React, event handlers,
      browser APIs, framer-motion, gsap. En pratique : pages = server, animations = client.
    • Pattern standard pour landing page animée :
        src/app/page.tsx           ← server (export metadata ici)
        src/components/HomePage.tsx ← "use client" (toutes les animations)
    • Metadata SEO : export const metadata: Metadata = { title, description } dans page.tsx.

NEXT/FONT — OBLIGATOIRE :
    • Importer de "next/font/google" — PAS "@next/font/google" (déprécié).
    • Variables CSS : variable: "--font-syne" → déclarer dans globals.css @theme inline avec un alias
      différent pour éviter la référence circulaire :
        @theme inline {
          --font-display: var(--font-syne);   /* → utiliser font-display dans les composants */
          --font-sans:    var(--font-inter);  /* → utiliser font-sans dans les composants */
        }
    • Appliquer via className sur <html> dans layout.tsx.

NEXT/IMAGE + NEXT/LINK :
    • Toujours <Image> de next/image — jamais <img> nu.
    • Toujours <Link> de next/link pour les routes internes.
    • Images externes → images.remotePatterns dans next.config.ts.

━━ VÉRIFICATION DU PROJET ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠ RÈGLE ABSOLUE : ne jamais lancer pnpm dev (ou npm run dev) de façon bloquante.
  ❌ shell_run("pnpm dev")                → bloque jusqu'au timeout (30s), ne sert à rien
  ❌ shell_run("pnpm dev > /dev/null")    → idem, process zombie

  Pour vérifier que le projet compile :
  ✅ shell_run("pnpm build")              → vérifie TypeScript + erreurs de build
  ✅ Résultat "Compiled successfully" = projet OK

  Si tu as besoin d'un screenshot du rendu (browser_screenshot) :
  1. shell_run("pnpm dev > /tmp/next-dev.log 2>&1 &")  ← arrière-plan avec &
  2. shell_run("sleep 6")
  3. browser_screenshot("http://localhost:3000")
  4. shell_kill_bg()                                    ← OBLIGATOIRE — tuer le serveur après

PERFORMANCE :
    • Composants lourds côté client : dynamic(() => import('./Comp'), { ssr: false })
    • generateStaticParams() pour les routes dynamiques générables statiquement.
    • GSAP + Lenis : init côté client uniquement.
