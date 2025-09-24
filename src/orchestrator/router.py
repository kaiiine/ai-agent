from pydantic import BaseModel, Field, ValidationError
from typing import List
from src.llm.models import make_llm
from src.orchestrator.registry import get_names, catalog_text

class RouteDecision(BaseModel):
    agent: str = Field(..., description="agent target")
    confidence: float = Field(..., ge=0, le=1)
    rationale: str
    plan: List[str] = []

ROUTER_SYS = """
Tu es un **orchestrateur de tools** et générateur de réponse.

🎯 Règle absolue :
- Réponds **UNIQUEMENT** en **Markdown valide**.
- Commence toujours par `# Réponse` (si en français) ou `# Answer` (si en anglais).
- Utilise des sous-sections avec `##`.
- Utilise des listes à puces `-` pour les points clés.
- Mets en **gras** les éléments importants.
- Utilise des blocs de code ``` pour les exemples de code ou commandes.

🌍 Langue :
- Si l'utilisateur écrit en français → réponds en français.
- Sinon → réponds en anglais.
- Ne réponds JAMAIS en chinois ni dans toute autre langue.

📋 Instructions :
1. Si un outil est nécessaire, appelle-le et utilise son résultat dans ta réponse.
2. Sinon, réponds directement en suivant le format Markdown.

🕐 Date et temps (PRIORITÉ ABSOLUE) :
- Pour TOUTE question impliquant une date, commence TOUJOURS par get_current_time
- Utilise l'année retournée par get_current_time dans tes recherches
- Exemples déclencheurs : "A quelle date...", "Quand...", "date de...", "manifestation", "événement"
- Workflow obligatoire : get_current_time → web_research_report avec année courante → réponse

Demande d'information :
- Si l'utilisateur pose une question factuelle, utilise un outil de recherche web.
- Répond toujours de manière complète, détaillée et structurée.
- N'invente jamais rien, effectue toujours des recherches si nécessaire.

Load Documents :
- Utiliser drive_* uniquement pour chercher/lister/supprimer des fichiers.
- Pour créer/éditer du contenu, utiliser google_docs_* ou create_presentation().
- Ne pas appeler drive_* si tu as déjà l’id/url renvoyé par un tool de création.

Rapport:
- Si l'utilisateur demande un rapport, crée un Google Doc avec google_docs_create()
  et ajoute le contenu avec google_docs_add_text() ou google_docs_add_bullets().

❌ Ne réponds JAMAIS en texte brut. Ne saute pas le formatage Markdown.
"""


def build_router(conf_threshold: float = 0.6, llm=None):
    llm = llm or make_llm()
    agents = get_names()
    catalog = catalog_text()

    def router(state):
        # Historique complet => le LLM a le contexte
        history = state["messages"]
        sys = ROUTER_SYS + f"\n{catalog}\n\nRéponds en JSON. Agents: {', '.join(agents)}"
        # (optionnel) continuité: informer quel était l'agent précédent
        if state.get("intent"):
            sys += f"\nAgent précédent: {state['intent']} (garder si cohérent)."

        messages = [{"role": "system", "content": sys}] + history
        raw = llm.invoke(messages).content
        cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()

        try:
            decision = RouteDecision.model_validate_json(cleaned)
        except ValidationError:
            decision = RouteDecision(agent="search", confidence=0.3,
                                     rationale="JSON invalide → fallback search")

        if decision.agent not in agents:
            decision.agent = "search"
            decision.confidence = min(decision.confidence, 0.5)
            decision.rationale += " (agent inconnu → search)"

        # Continuité si confiance faible et agent précédent cohérent
        if decision.confidence < conf_threshold and state.get("intent"):
            decision.agent = state["intent"]
            decision.rationale += " (confiance faible → continuité)"

        state["intent"] = decision.agent
        state.setdefault("route_history", []).append(
            f"router->{decision.agent} (conf={decision.confidence:.2f})"
        )
        state["artifacts"] = state.get("artifacts", []) + [{
            "type": "route_plan",
            "agent": decision.agent,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
            "plan": decision.plan,
        }]
        return state

    return router
