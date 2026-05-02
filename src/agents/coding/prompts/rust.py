"""Rust stack prompt."""

RUST_PROMPT = """\
━━ STACK DÉTECTÉ : RUST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCAFFOLDING :
   cargo new <nom>    (binaire)
   cargo new --lib <nom>   (bibliothèque)
   cargo init         (dans le dossier courant)

PIPELINE OBLIGATOIRE (dans cet ordre) :
   cargo fmt && cargo check && cargo clippy -- -D warnings && cargo test

ERREURS :
   • Binaires / apps : anyhow (anyhow::Result, context(), with_context())
   • Bibliothèques    : thiserror (#[derive(Error)])
   • .unwrap() et .expect() interdits en code de prod — utilise ? ou match.

ASYNC :
   • tokio par défaut : #[tokio::main], tokio::spawn, tokio::time::sleep.
   • Jamais std::thread::sleep dans du code async.

PERF :
   • Mesurer avec cargo build --release, pas le mode debug.
   • Profiler avec cargo flamegraph si un bottleneck est suspecté.

VÉRIFICATION :
   cargo fmt && cargo check && cargo clippy -- -D warnings && cargo test
   cargo build --release   (validation finale)
"""
