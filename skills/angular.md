---
name: angular
description: Angular NgModule RxJS standalone components signals inject
aliases: [ng]
---

━━ FRAMEWORK : ANGULAR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  SCAFFOLD — TOUJOURS VIA CLI, JAMAIS À LA MAIN :

    shell_run("pnpm dlx @angular/cli new <nom> --style=scss --routing --standalone --skip-git")
    Puis shell_cd("<nom>")
    ❌ JAMAIS créer angular.json / tsconfig / package.json à la main.

STANDALONE COMPONENTS (défaut Angular 17+) :
    • @Component({ standalone: true, imports: [...] }) — pas de NgModules sauf héritage legacy.
    • inject() dans le corps de la classe — éviter le constructor injection verbeux.
    • Signals pour le state local : signal(), computed(), effect().
    • input() / output() signals — remplacent @Input() / @Output().

ROUTING :
    • provideRouter(routes) dans main.ts · Routes définies dans app.routes.ts.
    • Lazy-loading : loadComponent(() => import('./feat/feat.component').then(m => m.FeatComponent))
    • Guards avec inject() : canActivate: [() => inject(AuthGuard).canActivate()]

STATE GLOBAL :
    • Simple → signals partagés dans un service injectable { providedIn: 'root' }.
    • Complexe → NgRx Signals Store : signalStore() avec withState(), withMethods().

FORMULAIRES :
    • Toujours Reactive Forms (FormBuilder, FormGroup, FormControl) — jamais Template-driven.
    • Validators : Validators.required, Validators.email, custom validators en fonctions pures.

STYLE :
    • SCSS avec variables CSS custom properties dans styles.scss.
    • Angular Material si composants UI complexes : ng add @angular/material.
    • Tailwind : ng add @ngneat/tailwind ou config manuelle via postcss.

⚠ GESTIONNAIRE DE PAQUETS — une seule famille par projet :
  pnpm dlx <pkg> (jamais npx) · pnpm add (jamais npm install) · pnpm <script> (jamais npm run).
  Projet EXISTANT avec package-lock.json et sans pnpm-lock.yaml → c'est npm :
  utiliser npx / npm install / npm run. Vérifier avec shell_ls, ne jamais supposer.
