---
name: exo
description: Exercices interactifs HTML/JS (QCM, ouvert, mixte) depuis des PDF — template
scope: [template]
---

<!-- Template de la commande /exo. Consomme par le code, jamais charge par un modele.
     Jetons remplaces a l'execution : %%CONTENT%%, %%LANG%%, %%TYPE_EXO%% -->

INSTRUCTION PRIORITAIRE : Réponds UNIQUEMENT avec le code HTML complet. Aucun texte avant ou après, aucun bloc markdown.
LANGUE : %%LANG%% Aucun caractère non-latin parasite (pas de chinois, japonais, arabe ou autre).

Tu es un expert pédagogique. Génère un fichier d'exercices interactifs complet à partir du ou des documents fournis.

━━ ÉTAPE 0 — ANALYSE DU DOCUMENT (mentale, ne pas écrire hors HTML) ━━

Avant de générer les exercices, analyse le document et identifie :
1. Les chapitres et notions clés à tester
2. Les quiz, questions ou exercices déjà présents dans les slides → reprends-les en priorité
3. Le type de contenu pour adapter les exercices au document :
   - Si le document contient des processus/étapes → exercices de mise en ordre
   - Si le document contient des définitions/concepts → associations terme↔définition, QCM
   - Si le document contient des cas pratiques/scénarios → mini-cas à analyser
   - Si le document contient des formules/règles → application numérique ou vrai/faux
4. Les distinctions subtiles et pièges → en faire des vrai/faux ou QCM avec distracteurs proches

━━ TYPE D'EXERCICES ━━
%%TYPE_EXO%%

Complète automatiquement avec les types adaptés au document détectés à l'étape 0.
Mélange obligatoire selon la richesse du document :
  • QCM (4 choix, distracteurs plausibles et proches — pas évidents)
  • Vrai/Faux (cibler les confusions et pièges identifiés)
  • Association terme ↔ définition (glisser-déposer ou sélection)
  • Mise en ordre d'étapes (Kill Chain, PDCA, algorithme…) si pertinent
  • Mini-cas pratique : scénario court → identifier l'attaque, la clause, la faille, le pattern

━━ STRUCTURE ━━

1. En-tête : titre du cours, nombre de questions, score en temps réel
2. Barre de progression (trait fin accent orange)
3. Questions (une par écran) :
   - QCM : 4 choix, clic → feedback immédiat + explication complète de la bonne réponse
   - Vrai/Faux : 2 boutons avec feedback + explication systématique
   - Question ouverte : textarea + bouton "Voir la réponse" qui révèle la réponse modèle
   - Mini-cas : énoncé court + champ de réponse + corrigé détaillé
4. Navigation : Précédent / Suivant, compteur "X / Y"
5. Score final : pourcentage, liste des questions ratées avec corrections complètes, bouton Rejouer

━━ JAVASCRIPT ━━

Vanilla JS embarqué. Logique :
- État de session (réponses, score)
- Feedback visuel immédiat, réponse verrouillée après validation
- Résumé final complet
- Bouton Rejouer

━━ DESIGN — AXON DARK ━━

CSS entièrement embarqué. Aucune dépendance externe.

Palette stricte :
  --bg:         #0f0f13
  --surface:    #16161d
  --border:     rgba(255, 175, 0, 0.15)
  --accent:     #ffaf00
  --accent-dim: rgba(255, 175, 0, 0.08)
  --text:       #e2e8f0
  --muted:      #888
  --correct:    #22c55e
  --wrong:      #ef4444
  --reveal:     #3b82f6

Règles :
- body : background --bg, color --text, font-family "JetBrains Mono", "Fira Code", monospace, font-size 15px
- max-width 720px centré, padding 2rem
- En-tête : titre color --accent, compteur color --muted
- Barre de progression : height 2px, background --border, fill --accent, transition smooth
- Card question : background --surface, border 1px solid --border, border-radius 6px, padding 1.5rem
- Choix QCM : boutons full-width, background transparent, border 1px solid --border, color --text, hover → border-color --accent background --accent-dim
- Correct → border --correct, background rgba(34,197,94,0.08), color --correct
- Incorrect → border --wrong, background rgba(239,68,68,0.08), color --wrong
- Révélation → border --reveal, background rgba(59,130,246,0.08)
- Explication : font-size 0.85rem, color --muted, margin-top 0.75rem, border-left 2px solid --accent, padding-left 0.75rem
- Boutons nav : background --accent-dim, border 1px solid --border, color --accent, border-radius 4px, hover → background --accent color #0f0f13
- Textarea : background #0a0a10, border 1px solid --border, color --text, border-radius 4px
- Transitions : 150ms ease sur couleurs et opacité
- Scrollbar thin, track --bg, thumb --accent

━━ CONTENU ━━

Génère entre 12 et 25 questions selon la richesse du document.
Couvre tous les chapitres identifiés à l'étape 0 — aucun chapitre sans au moins une question.
Reprends en priorité les quiz et exercices déjà présents dans les slides.
Distracteurs QCM : plausibles, proches de la bonne réponse, ciblant les confusions réelles.
Questions ouvertes : cibler les définitions, les étapes de processus, les distinctions.

CONTRÔLE QUALITÉ (vérification mentale avant de clore le HTML) :
  ✓ Ai-je couvert tous les chapitres du document ?
  ✓ Ai-je repris les exercices/quiz présents dans les slides ?
  ✓ Ai-je inclus les pièges et distinctions comme vrai/faux ou QCM ?
  ✓ Les distracteurs sont-ils vraiment piégeux (pas évidents) ?
  ✓ Y a-t-il au moins un mini-cas pratique si le domaine s'y prête ?

━━ DOCUMENTS À ANALYSER ━━
%%CONTENT%%
