"""Angular specific prompt — Standalone Components, Signals, NgRx."""

ANGULAR_PROMPT = """\
━━ FRAMEWORK : ANGULAR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  SCAFFOLD — TOUJOURS VIA CLI, JAMAIS À LA MAIN :

    shell_run("npx @angular/cli new <nom> --style=scss --routing --standalone --skip-git")
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
"""
