# ADR-ADV-012 — Persistance d'audit (V1)

**Statut** : accepté (Lot 10). Détails complets : `axon-advisor-current-state.md §10.7`.

## Décision
Store **JSONL append-only** : une `AdvisorAuditEnvelope` JSON canonique par ligne,
encapsulée derrière `audit.store.JsonlAuditStore` (`append` / `get` / `iter_records`).

## Alternatives rejetées en V1
- **SQLite** : schéma SQL + migrations à porter, surdimensionné pour un flux
  append-only inspectable.
- **Base Axon existante** : couplage indésirable du domaine Advisor à une base.

Toutes deux pourront être introduites **derrière la même frontière** `JsonlAuditStore`
sans toucher au domaine d'audit.

## Emplacement
`audit_store_path` **injectable** (tests : `tmp_path`). Défaut repo-local
`var/advisor/audits/audit.jsonl` (`var/` déjà gitignoré), porté par
`configs/advisor/audit_policy.json` (versionné, checksum validé). **`~/.axon`
interdit** (interdiction stable, refusée par le loader). Aucun chemin utilisateur
absolu codé en dur.

## Intégrité & robustesse
- `payload_checksum = sha256(canonical(payload))` — intégrité de l'archive, jamais
  un pointeur vers l'état disque courant.
- Reader STRICT : JSON invalide, champ absent, version inconnue, checksum incorrect,
  snapshot corrompu, doublon contradictoire → erreur stable (jamais de réparation).
- Append-only, aucun overwrite. Idempotence par `audit_id` ; collision
  `REQUEST_ID_CONTENT_MISMATCH` / `DUPLICATE_AUDIT_DIVERGENT`.
- **Concurrence multi-processus hors scope V1** (mono-processus ; backend
  transactionnel futur possible derrière la frontière).

## Hors scope
Migrations de schéma, drift analysis, SQLite/base Axon/cloud, réplication,
locking distribué, chiffrement custom, rétention/purge.
