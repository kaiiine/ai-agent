"""Surface CLI `/mcp` (DESIGN §9, corrigé par les addenda v2.2 §B et v2.3 §G).

Dispatcher SYNCHRONE : le REPL d'Axon l'est, et `MCPRuntime` fournit déjà le pont
vers la boucle asyncio. Les fonctions de rendu sont pures et renvoient du texte —
elles se testent sans serveur, sans terminal et sans Rich.

Deux informations n'existaient jusqu'ici que dans le runtime, sans surface :

  - **les collisions de nom runtime.** Un tool ignoré est un tool invisible pour
    le modèle. `/mcp tools` le nomme, et `/mcp list` distingue « exposés » de
    « découverts » dès que les deux diffèrent.
  - **les trois niveaux de nommage.** `remote_name` (appel MCP), `public_name`
    (identité stable : index, provenance, logs) et nom runtime (ce que voit le
    modèle). C'est la table de correspondance dont on a besoin quand un log de
    provenance et une trace de function-calling ne portent pas le même
    identifiant.
"""

from __future__ import annotations

from src.mcp_client.models import (
    DiagnosticReport,
    DiagnosticStep,
    MCPServerConfig,
    MCPServerState,
    MCPToolRef,
    ToolDiff,
)
from src.mcp_client.registry import runtime_tool_name

_USAGE = """\
/mcp list                    état de tous les serveurs déclarés
/mcp add <nom> [cmd args…]   ajoute un serveur (assistant si cmd omise) puis le teste
/mcp remove <nom>            retire le serveur et désindexe ses tools
/mcp enable <nom>            active, connecte et indexe
/mcp disable <nom>           désactive et désindexe
/mcp test <nom> [--deep]     diagnostic par étapes ; --deep sonde un tool read-only
/mcp tools <nom>             schémas et table des trois noms
/mcp refresh <nom>           re-tools/list sans redémarrer le processus
/mcp restart <nom>           redémarre le sous-processus puis resynchronise"""

_STATE_ORDER = {
    MCPServerState.READY: 0, MCPServerState.DEGRADED: 1, MCPServerState.CONNECTING: 2,
    MCPServerState.DISCONNECTED: 3, MCPServerState.ERROR: 4, MCPServerState.DISABLED: 5,
}


# ── helpers de rendu ────────────────────────────────────────────────────────────
def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) if rows else len(headers[i])
              for i in range(len(headers))]
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    for row in rows:
        lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(lines)


def _duration(step) -> str:
    return f" ({step.duration_ms:.0f} ms)" if step.duration_ms is not None else ""


def _symbol(ok: bool | None) -> str:
    return "✓" if ok is True else ("✗" if ok is False else "⚠")


# ── rendus ──────────────────────────────────────────────────────────────────────
def render_status_table(runtime) -> str:
    """`TOOLS` vaut `exposés/découverts` dès que les deux diffèrent : un tool
    découvert mais non exposé est inatteignable pour le modèle, et ce serait
    invisible avec un simple compteur. `ROUTING` dit si les DEUX étages sont
    indexés — des tools exposés avec un étage 1 manquant restent exécutables mais
    plus difficiles à sélectionner.

    Aucune ligne de ce rendu n'affirme une cause qu'elle n'a pas vérifiée : la
    collision n'est nommée que s'il y en a une, et l'écart inexpliqué est présenté
    comme tel."""
    status = runtime.status()
    if not status:
        return "Aucun serveur MCP déclaré. `/mcp add <nom>` pour en ajouter un."

    rows, with_collision, unexplained, degraded = [], [], [], []
    for name in sorted(status, key=lambda n: (_STATE_ORDER.get(status[n].state, 9), n)):
        rt = status[name]
        discovered, exposed = len(runtime.discovered(name)), len(runtime.exposed(name))
        if discovered == 0:
            tools = "-"
        elif discovered == exposed:
            tools = str(discovered)
        else:
            tools = f"{exposed}/{discovered}"
            (with_collision if runtime.collisions(name) else unexplained).append(name)

        reason = runtime.index_state(name)
        if discovered == 0:
            routing = "-"
        elif reason:
            routing = "étage 2"
            degraded.append((name, reason))
        else:
            routing = "ok"
        rows.append([name, rt.state.value, tools, routing, rt.last_error or "-"])

    out = _table(["NAME", "STATE", "TOOLS", "ROUTING", "LAST ERROR"], rows)
    if with_collision:
        out += ("\n\nTOOLS = exposés/découverts. Collision de nom runtime sur "
                f"{', '.join(with_collision)} : `/mcp tools <nom>` liste les tools ignorés.")
    if unexplained:
        out += ("\n\nTOOLS = exposés/découverts. Écart sans cause identifiée sur "
                f"{', '.join(unexplained)} : `/mcp tools <nom>` pour le détail.")
    for name, reason in degraded:
        out += (f"\n\nROUTING {name} : étage 1 indisponible — {reason}.\n"
                "Les tools restent exposés et exécutables, la sélection passe par "
                "l'étage 2 seul.")
    return out


def render_tools(server: str, discovered: list[MCPToolRef],
                 exposed: list[MCPToolRef],
                 collisions: list[tuple[MCPToolRef, str]]) -> str:
    """Les TROIS noms côte à côte — c'est la table de correspondance de debug."""
    if not discovered:
        return f"{server} : aucun tool découvert (serveur non connecté ou sans tool)."

    exposed_names = {ref.public_name for ref in exposed}
    rows = [[
        ref.remote_name,
        ref.public_name,
        runtime_tool_name(ref.public_name) if ref.public_name in exposed_names else "—",
        ref.risk_level,
        (ref.description or "").splitlines()[0][:60],
    ] for ref in discovered]

    header = f"{server} — {len(discovered)} tools découverts, {len(exposed_names)} exposés"
    out = header + "\n\n" + _table(
        ["REMOTE", "PUBLIC (identité)", "RUNTIME (modèle)", "RISK", "DESCRIPTION"], rows)

    if collisions:
        out += f"\n\n⚠ {len(collisions)} tool(s) ignoré(s) — collision de nom runtime :"
        for ref, conflict in collisions:
            out += (f"\n  {ref.public_name} → {runtime_tool_name(ref.public_name)}"
                    f" (déjà pris par {conflict})")
        out += "\n  Ces tools ne sont PAS atteignables par le modèle."
    return out


def _routing_step(runtime, server: str) -> DiagnosticStep:
    """Un serveur peut être parfaitement connecté et rester mal sélectionnable :
    l'état d'indexation est une étape de diagnostic à part entière."""
    reason = runtime.index_state(server)
    if reason:
        return DiagnosticStep("routing index", False,
                              f"étage 1 indisponible ({reason}) — repli sur l'étage 2, "
                              "tools exposés et exécutables")
    return DiagnosticStep("routing index", True, "étages 1 et 2 indexés")


def render_diagnostic(report: DiagnosticReport) -> str:
    lines = [f"/mcp test {report.server}", ""]
    label_width = max((len(s.label) for s in report.steps), default=0)
    for step in report.steps:
        lines.append(f"{_symbol(step.ok)} {step.label.ljust(label_width)}   "
                     f"{step.detail}{_duration(step)}")
    return "\n".join(lines)


def render_diff(server: str, diff: ToolDiff) -> str:
    if diff.is_empty:
        return f"{server} : index déjà à jour, aucun changement de tool."
    parts = []
    for label, refs in (("ajoutés", diff.added), ("retirés", diff.removed),
                        ("modifiés", diff.changed)):
        if refs:
            parts.append(f"  {label} ({len(refs)}) : "
                         + ", ".join(r.remote_name for r in refs))
    return f"{server} : index resynchronisé.\n" + "\n".join(parts)


# ── assistant d'ajout ───────────────────────────────────────────────────────────
def interactive_add_server(name: str, spec: list[str], prompt) -> MCPServerConfig:
    """`spec` non vide = forme directe `/mcp add <nom> <commande> [args…]`.
    Sinon on demande le minimum : commande, arguments, capacités, sonde.

    Aucun secret n'est saisi ici : la config accepte `"${VAR}"`, résolu au
    lancement — un secret en clair dans le fichier serait un secret versionnable."""
    if spec:
        command, args = spec[0], spec[1:]
    else:
        # Pas d'exemple nommant un lanceur ou un serveur particulier : la
        # connaissance d'un serveur donné n'entre que par la config.
        command = (prompt(f"commande à lancer pour '{name}' : ") or "").strip()
        args = (prompt("arguments séparés par des espaces (vide si aucun) : ") or "").split()

    if not command:
        raise ValueError("commande vide : impossible de déclarer le serveur")

    hint = (prompt("capacités en mots-clés (améliore le routing) : ") or "").strip() if not spec else ""
    probe = (prompt("tool read-only pour /mcp test --deep (vide si inconnu) : ") or "").strip() \
        if not spec else ""

    cfg = MCPServerConfig(name=name, command=command, args=list(args), capabilities_hint=hint)
    if probe:
        cfg.health.probe_tool = probe
    return cfg


# ── dispatcher ──────────────────────────────────────────────────────────────────
def handle_mcp(args: list[str], runtime, *, prompt=input) -> str:
    """Point d'entrée de `/mcp`. Renvoie du texte prêt à afficher."""
    try:
        match args:
            case [] | ["help"]:
                return _USAGE

            case ["list"]:
                return render_status_table(runtime)

            case ["add", name, *spec]:
                cfg = interactive_add_server(name, list(spec), prompt)
                runtime.add(cfg)
                # Un serveur ajouté sans diagnostic laisse l'utilisateur découvrir
                # la panne au premier appel de tool : on enchaîne sur le test.
                return (f"{name} ajouté à {runtime.config_path}.\n\n"
                        + render_diagnostic(runtime.diagnose(name)))

            case ["remove", name]:
                diff = runtime.remove(name)
                return f"{name} retiré.\n" + render_diff(name, diff)

            case ["enable", name]:
                diff = runtime.enable(name)
                return f"{name} activé.\n" + render_diff(name, diff)

            case ["disable", name]:
                diff = runtime.disable(name)
                return f"{name} désactivé.\n" + render_diff(name, diff)

            case ["test", name, *flags] if set(flags) <= {"--deep"}:
                report = runtime.diagnose(name, deep="--deep" in flags)
                # Nouveau rapport plutôt qu'un append : muter l'objet rendu par le
                # runtime le ferait grossir à chaque appel de `/mcp test`.
                return render_diagnostic(DiagnosticReport(
                    server=report.server,
                    steps=list(report.steps) + [_routing_step(runtime, name)]))

            case ["tools", name]:
                return render_tools(name, runtime.discovered(name),
                                    runtime.exposed(name), runtime.collisions(name))

            case ["refresh", name]:
                return render_diff(name, runtime.refresh(name))

            case ["restart", name]:
                return render_diff(name, runtime.restart(name))

            case _:
                return _USAGE
    except KeyError as exc:
        return f"Serveur MCP inconnu : {exc.args[0] if exc.args else ''}\n\n{_USAGE}"
    except Exception as exc:
        return f"erreur /mcp : {exc}"
