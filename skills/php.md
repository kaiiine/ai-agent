---
name: php
description: Builds and scaffolds PHP projects from scratch: Laravel, Symfony, Composer, PHPUnit, Pest, PSR standards. Use when writing new PHP code.
aliases: [laravel, symfony, composer, artisan]
---

━━ STACK DÉTECTÉ : PHP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   Laravel  → composer create-project laravel/laravel <nom>
              php artisan serve
   Symfony  → symfony new <nom> --webapp     (ou composer create-project symfony/skeleton)
              symfony serve
   Vérifier composer.json AVANT de choisir : ne jamais introduire un framework
   dans un projet qui n'en a pas.

BASES :
   • declare(strict_types=1); en tête de CHAQUE fichier. Sans lui, PHP convertit
     silencieusement "abc" en 0 et une comparaison devient fausse sans erreur.
   • Autoload PSR-4 via composer.json, jamais de require manuel.
   • Typer les propriétés, les paramètres et les retours. PHP 8 le permet
     partout : un paramètre non typé est une régression volontaire.
   • === et !== par défaut. == compare après conversion et surprend toujours.

LARAVEL :
   • Un controller mince : valider (FormRequest), déléguer, rendre. La logique
     va dans un service ou une action, pas dans le controller.
   • Eloquent N+1 : with() sur toute relation lue en boucle. Activer
     Model::preventLazyLoading() en dev — l'erreur vaut mieux que la lenteur.
   • Migrations réversibles : down() écrit et testé. Jamais de modification
     manuelle d'une migration déjà jouée en prod.
   • Validation par FormRequest, jamais $request->all() passé à create() —
     c'est l'assignation de masse.
   • Jobs en file pour tout ce qui dépasse la seconde : mail, PDF, appel externe.

SYMFONY :
   • Injection par constructeur, autowiring par défaut. Pas de $container->get().
   • Doctrine : QueryBuilder pour les requêtes non triviales, et fetch join
     explicite plutôt que de compter sur le lazy loading.
   • Les entités ne sortent jamais telles quelles d'une API : DTO + Serializer.
   • Les routes en attributs PHP 8, pas en YAML, sauf projet déjà en YAML.

QUALITÉ :
   composer require --dev phpstan/phpstan
   vendor/bin/phpstan analyse --level=6 src      (viser 8 sur un projet neuf)
   vendor/bin/php-cs-fixer fix                   (PSR-12)

TESTS :
   vendor/bin/phpunit          ou    vendor/bin/pest
   • Base de test jetable (sqlite en mémoire ou base dédiée), jamais celle de dev.
   • Laravel : RefreshDatabase sur les tests qui touchent la base.

SÉCURITÉ :
   • Requêtes préparées TOUJOURS — jamais de concaténation dans du SQL.
   • password_hash() / password_verify(), jamais md5 ni sha1.
   • Échapper en sortie : {{ }} de Blade et {{ }} de Twig échappent, {!! !!} et
     |raw ne le font pas. Ne les utiliser que sur du contenu qu'on a produit.
   • Jamais de secret dans .env versionné : .env.example versionné, .env ignoré.

VÉRIFICATION :
   vendor/bin/phpstan analyse && vendor/bin/phpunit
