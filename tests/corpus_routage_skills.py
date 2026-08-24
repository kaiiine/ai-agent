"""Deux jeux de référence pour le routage des skills, et la raison d'en avoir deux.

`REGLAGE` sert à construire et à régler. `TENU_A_L_ECART` a été écrit APRÈS, avec
d'autres formulations pour les mêmes intentions, et n'a jamais servi à ajuster
quoi que ce soit.

Cette séparation n'est pas un ornement méthodologique : elle a invalidé un
mécanisme entier. Une détection d'intention par lexique de verbes atteignait
22/22 sur `REGLAGE` et 7/16 sur `TENU_A_L_ECART` — la regex n'était que la liste
des verbes du premier jeu. Un jeu unique aurait fait expédier ce mécanisme comme
un succès.

Les deux jeux sont délibérément SYMÉTRIQUES : le même domaine y est demandé une
fois en production et une fois en relecture. C'est le seul moyen de voir qu'un
routeur confond « écris une API FastAPI » et « relis mon API FastAPI ».
"""
from __future__ import annotations

REGLAGE: list[tuple[str, str]] = [
    # ── produire ─────────────────────────────────────────────────────────────
    ("crée une API FastAPI",                          "python"),
    ("écris un backend en Python avec Django",        "python"),
    ("fais-moi un site en Next.js",                   "nextjs"),
    ("crée un composant React",                       "frontend"),
    ("développe un serveur en Go",                    "go"),
    ("écris un CLI en Rust",                          "rust"),
    ("monte une app Vue avec Pinia",                  "vue"),
    ("modélise un igloo dans Blender",                "blender"),
    ("refais le site avec le style d'Apple",          "apple-design"),
    ("ajoute une scène Three.js animée",              "threedee"),
    # ── relire ───────────────────────────────────────────────────────────────
    ("relis mon code Python",                         "python-reviewer"),
    ("revois mes hooks React",                        "react-reviewer"),
    ("audite la sécurité de mon app",                 "security-reviewer"),
    ("vérifie mes requêtes SQL Postgres",             "database-reviewer"),
    ("relis mon code TypeScript",                     "typescript-reviewer"),
    ("simplifie ce code trop verbeux",                "code-simplifier"),
    ("supprime le code mort du projet",               "refactor-cleaner"),
    ("cherche les erreurs avalées en silence",        "silent-failure-hunter"),
    ("relis mon API FastAPI",                         "fastapi-reviewer"),
    ("écris les tests avant le code",                 "tdd-guide"),
    # ── réparer ──────────────────────────────────────────────────────────────
    ("mon build TypeScript ne compile plus",          "build-error-resolver"),
    ("mon build React plante avec Vite",              "react-build-resolver"),
]

TENU_A_L_ECART: list[tuple[str, str]] = [
    ("monte-moi un projet Next.js avec App Router",   "nextjs"),
    ("j'ai besoin d'un microservice Go",              "go"),
    ("code une extension Blender en Python",          "blender"),
    ("fabrique une interface React moderne",          "frontend"),
    ("un backend Express en TypeScript",              "node_backend"),
    ("une appli Svelte avec des stores",              "svelte"),
    ("passe mon code Rust en async tokio",            "rust"),
    ("donne-moi un avis sur mes composants React",    "react-reviewer"),
    ("est-ce que mon schéma Postgres tient la route", "database-reviewer"),
    ("y a-t-il des failles dans mon application",     "security-reviewer"),
    ("mes types TypeScript sont-ils corrects",        "typescript-reviewer"),
    ("ce module est illisible, allège-le",            "code-simplifier"),
    ("des erreurs sont attrapées puis ignorées",      "silent-failure-hunter"),
    ("le bundler Vite renvoie une erreur",            "react-build-resolver"),
    ("tsc refuse de compiler mon projet",             "build-error-resolver"),
    ("quelles fonctions ne sont plus appelées",       "refactor-cleaner"),
]
