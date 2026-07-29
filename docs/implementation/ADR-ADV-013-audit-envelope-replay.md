# ADR-ADV-013 — Enveloppe d'audit versionnée & replay exact (V1)

**Statut** : accepté (Lot 10). Détails complets : `axon-advisor-current-state.md §10.7`.

## Enveloppe
```
AdvisorAuditEnvelope {
    audit_schema_version   # version explicite ; version inconnue -> erreur (pas de migration silencieuse)
    audit_id               # sha256(request_id | request_fingerprint)
    request_id
    request_fingerprint    # sha256(canonical(requête SANS request_id)) — contenu métier
    created_at             # métadonnée : hors identité, hors payload_checksum
    payload_checksum       # sha256(canonical(payload))
    payload                # requête, snapshots de config, batch adapté, évaluations,
                           # recommandation, trail Combo, be_run_id
}
```
`RecommendationResponse` reste **gelée** : l'audit est un artefact parallèle
(`run_pipeline -> PipelineRunResult{recommendation, trace}`).

## Sérialisation canonique
Réutilise `domain.serialization` (Lot 1), étendue une fois pour les `float`
**diagnostiques non monétaires** (features → chaîne canonique). La sécurité
monétaire reste garantie par les contrats (`Decimal` obligatoire).

## Snapshots de config
Le payload archive le **contenu exact** des configs consommées + leur checksum.
Le replay les reconstruit depuis l'archive (fichier temporaire + loader réel),
**jamais** depuis `configs/advisor/*.json` courant → replay autonome dans le temps.

## `REPLAY_EXACT` (seul mode V1)
```
load -> version -> payload_checksum -> snapshots -> reconstruit requête/configs/batch
     -> rejoue le pipeline déterministe -> compare le résultat MÉTIER à l'archive
```
Sortie structurée `ReplayResult{matches, differences}` (exploitable hors tests).
Aucun appel bookmaker/Betting Engine/Gateway ; aucune config courante consultée.
« Identique » = métier déterministe (hors `created_at`/durée/chemin).

## Idempotence & collisions
Même `request_id`+contenu → même `audit_id` → idempotent. Même `request_id`+contenu
différent → `REQUEST_ID_CONTENT_MISMATCH`. Même `audit_id`+payload divergent →
`DUPLICATE_AUDIT_DIVERGENT`. `created_at` ne casse jamais l'idempotence.

## Quatre états Combo (archivés, jamais déduits des PortfolioLine)
`ComboMaterializationStatus` {NOT_APPLICABLE, NO_CANDIDATE, MATERIALIZED,
BLOCKED_SIZING_NOT_AVAILABLE} + `ComboBookmakerAcceptanceStatus` {NOT_VERIFIED,
ACCEPTED, REJECTED} + `combo_builder_invoked` + `combo_signal`. Sizing COMBO NON résolu.

## Hors scope
`COMPARE_CURRENT`/drift, migrations de schéma, replay cross-version de code
incompatible (V1 snapshotte données+configs, pas l'exécutable Python).
