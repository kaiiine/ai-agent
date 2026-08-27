"""Quels outils sont liés pour une requête ?  python outils_pour.py "ta phrase" """
import sys

from src.orchestrator.registry import build_all_tools
from src.orchestrator.tool_retriever import TOOL_GROUPS, ToolRetriever

question = " ".join(sys.argv[1:])
if not question:
    sys.exit('usage : python outils_pour.py "ta phrase"')

retriever = ToolRetriever(build_all_tools())
classes, rangs = retriever._rank_groups_detaille(question)
noms = [o.name for o in retriever.get(question)]
appartenance = {t: g for g, s in TOOL_GROUPS.items() for t in s.tools}

print()
print("  groupes élus :", ", ".join(f"{g}(rang {rangs.get(g, '?')})" for g in classes))
print(f"  {len(noms)} outils liés — sur {len(appartenance)} qui existent")
print()
par_groupe: dict[str, list[str]] = {}
for nom in noms:
    par_groupe.setdefault(appartenance.get(nom, "épinglé/MCP"), []).append(nom)
for groupe, dedans in par_groupe.items():
    print(f"    {groupe:<16} {', '.join(dedans)}")
