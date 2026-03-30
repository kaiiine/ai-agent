"""Jira tools — lecture et gestion des tickets via l'API REST v3."""
from __future__ import annotations

import os
from typing import Optional
from requests.auth import HTTPBasicAuth
import requests
from langchain_core.tools import tool


# === CLIENT ===

def _auth() -> tuple[str, HTTPBasicAuth]:
    """Retourne (base_url, auth) pour l'API Jira."""
    url = os.getenv("JIRA_URL", "").rstrip("/")
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_API_KEY", "")
    if not url or not email or not token:
        raise RuntimeError("JIRA_URL, JIRA_EMAIL et JIRA_API_KEY sont requis dans .env")
    return url, HTTPBasicAuth(email, token)


def _api_version() -> str:
    """Détecte la version API disponible (v3 d'abord, fallback v2)."""
    base, auth = _auth()
    for v in ("3", "2"):
        try:
            r = requests.get(
                f"{base}/rest/api/{v}/myself",
                auth=auth,
                headers={"Accept": "application/json"},
                timeout=10,
            )
            if r.status_code == 200:
                return v
        except Exception:
            continue
    return "3"


_API_VERSION_CACHE: str | None = None


def _api(path: str) -> str:
    global _API_VERSION_CACHE
    if _API_VERSION_CACHE is None:
        _API_VERSION_CACHE = _api_version()
    base, _ = _auth()
    return f"{base}/rest/api/{_API_VERSION_CACHE}/{path.lstrip('/')}"


def _get_account_id() -> str:
    """Retourne l'account ID de l'utilisateur courant via /myself."""
    base, auth = _auth()
    global _API_VERSION_CACHE
    if _API_VERSION_CACHE is None:
        _API_VERSION_CACHE = _api_version()
    r = requests.get(
        f"{base}/rest/api/{_API_VERSION_CACHE}/myself",
        auth=auth,
        headers={"Accept": "application/json"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json().get("accountId", "")


def _get(path: str, params: dict | None = None) -> dict:
    _, auth = _auth()
    r = requests.get(
        _api(path),
        auth=auth,
        headers={"Accept": "application/json"},
        params=params or {},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    _, auth = _auth()
    r = requests.post(
        _api(path),
        auth=auth,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"Jira API error {r.status_code}: {detail}")
    return r.json() if r.content else {}


def _put(path: str, body: dict) -> dict:
    _, auth = _auth()
    r = requests.put(
        _api(path),
        auth=auth,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json=body,
        timeout=15,
    )
    r.raise_for_status()
    return r.json() if r.content else {}


# === HELPERS === 

def _fmt_issue(issue: dict) -> dict:
    """Formate un issue Jira en dict lisible."""
    f = issue.get("fields", {})
    assignee = f.get("assignee") or {}
    reporter = f.get("reporter") or {}
    priority = f.get("priority") or {}
    status = f.get("status") or {}
    issuetype = f.get("issuetype") or {}
    sprint_field = f.get("customfield_10020")  
    sprint_name = None
    if isinstance(sprint_field, list) and sprint_field:
        sprint_name = sprint_field[-1].get("name")

    return {
        "key": issue.get("key"),
        "summary": f.get("summary"),
        "type": issuetype.get("name"),
        "status": status.get("name"),
        "priority": priority.get("name"),
        "assignee": assignee.get("displayName"),
        "reporter": reporter.get("displayName"),
        "sprint": sprint_name,
        "created": (f.get("created") or "")[:10],
        "updated": (f.get("updated") or "")[:10],
        "due": f.get("duedate"),
        "story_points": f.get("customfield_10016"),
        "description_text": _extract_text(f.get("description")),
        "url": f"{os.getenv('JIRA_URL', '').rstrip('/')}/browse/{issue.get('key')}",
    }


def _extract_text(doc: dict | None) -> str:
    """Extrait le texte brut d'un document Atlassian Document Format."""
    if not doc or not isinstance(doc, dict):
        return ""
    parts = []
    for block in doc.get("content", []):
        for inline in block.get("content", []):
            if inline.get("type") == "text":
                parts.append(inline.get("text", ""))
    return " ".join(parts).strip()


def _get_board_id(project_key: str) -> int | None:
    """Récupère le board ID d'un projet via l'Agile API."""
    base, auth = _auth()
    try:
        r = requests.get(
            f"{base}/rest/agile/1.0/board",
            auth=auth,
            headers={"Accept": "application/json"},
            params={"projectKeyOrId": project_key},
            timeout=10,
        )
        if r.status_code == 200:
            values = r.json().get("values", [])
            if values:
                return values[0].get("id")
    except Exception:
        pass
    return None


def _agile_issues(project_key: str, max_results: int = 50) -> list[dict]:
    """Récupère les tickets via l'Agile API (fallback quand search est bloqué)."""
    base, auth = _auth()
    board_id = _get_board_id(project_key)
    if not board_id:
        return []
    results = []
    for endpoint in ("backlog", "issue"):
        try:
            r = requests.get(
                f"{base}/rest/agile/1.0/board/{board_id}/{endpoint}",
                auth=auth,
                headers={"Accept": "application/json"},
                params={"maxResults": max_results},
                timeout=15,
            )
            if r.status_code == 200:
                issues = r.json().get("issues", [])
                if issues:
                    return [_fmt_issue(i) for i in issues]
        except Exception:
            continue
    return results


def _jql(jql: str, fields: str, max_results: int = 50) -> list[dict]:
    base, auth = _auth()
    params = {"jql": jql, "fields": fields, "maxResults": max_results}
    headers = {"Accept": "application/json"}
    for url in [
        f"{base}/rest/api/2/search",
        f"{base}/rest/api/3/issue/search",
        f"{base}/rest/api/3/search",
    ]:
        try:
            r = requests.get(url, auth=auth, headers=headers, params=params, timeout=15)
            if r.status_code == 200:
                return [_fmt_issue(i) for i in r.json().get("issues", [])]
        except Exception:
            continue
    import re
    m = re.search(r'project\s*=\s*["\']?(\w+)["\']?', jql, re.IGNORECASE)
    if m:
        return _agile_issues(m.group(1), max_results)
    raise RuntimeError("Aucun endpoint de recherche Jira disponible sur cette instance.")


# === TOOLS ===

_FIELDS = (
    "summary,status,assignee,reporter,priority,issuetype,"
    "created,updated,duedate,customfield_10016,customfield_10020,description"
)

# Noms possibles pour le type "sous-tâche" selon la langue du projet Jira
_SUBTASK_ALIASES = ("Sous-tâche", "Sub-task", "Subtask", "subtask", "sous-tâche")


@tool("jira_get_my_issues")
def jira_get_my_issues(status: Optional[str] = None, limit: int = 20) -> dict:
    """
    Retourne les tickets Jira assignés à l'utilisateur courant.

    Utilise ce tool quand l'utilisateur veut :
    - voir ses tâches Jira en cours
    - savoir ce qui lui est assigné
    - consulter son backlog personnel
    - voir ses tickets ouverts / en cours / à faire

    Mots-clés : jira, tickets, tâches assignées, mon backlog, mes issues, ce que j'ai à faire

    Args:
        status: filtre optionnel sur le statut ("To Do", "In Progress", "Done", etc.)
        limit: nombre max de tickets (défaut 20)
    Returns:
        {"status": "ok", "count": N, "issues": [...]}
    """
    try:
        account_id = _get_account_id()
        jql = f'assignee = "{account_id}"' if account_id else "assignee = currentUser()"
        if status:
            jql += f' AND status = "{status}"'
        jql += " ORDER BY updated DESC"
        try:
            issues = _jql(jql, _FIELDS, limit)
        except RuntimeError:
            myself = _get("myself")
            display_name = myself.get("displayName", "")
            projects_data = _get("project/search", {"maxResults": 50})
            issues = []
            for p in projects_data.get("values", []):
                for issue in _agile_issues(p["key"], limit):
                    assignee = issue.get("assignee") or ""
                    if assignee and assignee == display_name:
                        issues.append(issue)
        return {"status": "ok", "count": len(issues), "issues": issues}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_get_issue")
def jira_get_issue(key: str) -> dict:
    """
    Retourne les détails complets d'un ticket Jira.

    Utilise ce tool quand l'utilisateur mentionne un ticket par sa clé (ex: PROJ-123).
        _put(f"issue/{issue_key}", {"fields": {"parent": {"key": epic_key}}})

    Args:
        key: clé du ticket (ex: "PROJ-42")
    Returns:
        {"status": "ok", "issue": {...}}
    """
    try:
        raw = _get(f"issue/{key}", {"fields": _FIELDS})
        return {"status": "ok", "issue": _fmt_issue(raw)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_search_issues")
def jira_search_issues(jql: str, limit: int = 30) -> dict:
    """
    Recherche des tickets Jira avec une requête JQL libre.

    Utilise ce tool quand l'utilisateur veut chercher des tickets avec des critères précis.

    Exemples de JQL :
    - "project = MON_PROJET AND status = 'In Progress'"
    - "assignee = currentUser() AND priority = High"
    - "text ~ 'login bug' AND created >= -7d"
    - "sprint in openSprints() AND project = WEB"

    Args:
        jql: requête JQL
        limit: nombre max de résultats (défaut 30)
    Returns:
        {"status": "ok", "count": N, "issues": [...]}
    """
    try:
        issues = _jql(jql, _FIELDS, limit)
        return {"status": "ok", "count": len(issues), "issues": issues}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_get_project_summary")
def jira_get_project_summary(project_key: str) -> dict:
    """
    Retourne un résumé de l'avancement d'un projet Jira : tickets par statut, sprint actif, points.

    Utilise ce tool quand l'utilisateur veut :
    - voir l'avancement global d'un projet
    - savoir combien de tickets sont terminés / en cours / à faire
    - avoir une vue d'ensemble d'un projet

    Mots-clés : avancement projet, progression, état du projet, résumé, bilan jira

    Args:
        project_key: clé du projet (ex: "WEB", "BACKEND", "APP")
    Returns:
        {"status": "ok", "project": "...", "by_status": {...}, "by_type": {...}, "sprint": {...}}
    """
    try:
        all_issues = _jql(f"project = {project_key} ORDER BY updated DESC", _FIELDS, 200)

        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        total_points = 0
        done_points = 0

        for issue in all_issues:
            st = issue["status"] or "Unknown"
            tp = issue["type"] or "Unknown"
            by_status[st] = by_status.get(st, 0) + 1
            by_type[tp] = by_type.get(tp, 0) + 1
            pts = issue.get("story_points") or 0
            total_points += pts
            if st.lower() in ("done", "closed", "resolved", "terminé"):
                done_points += pts

        active_sprint = None
        try:
            sprint_issues = _jql(
                f"project = {project_key} AND sprint in openSprints()",
                "customfield_10020",
                1,
            )
            if sprint_issues and sprint_issues[0].get("sprint"):
                active_sprint = {"name": sprint_issues[0]["sprint"]}
        except Exception:
            active_sprint = None  

        completion_pct = round(done_points / total_points * 100) if total_points else None

        return {
            "status": "ok",
            "project": project_key,
            "total_issues": len(all_issues),
            "by_status": by_status,
            "by_type": by_type,
            "story_points": {
                "total": total_points,
                "done": done_points,
                "completion_pct": completion_pct,
            },
            "active_sprint": active_sprint,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_get_sprint_issues")
def jira_get_sprint_issues(project_key: str, limit: int = 50) -> dict:
    """
    Retourne tous les tickets du sprint actif d'un projet.

    Utilise ce tool quand l'utilisateur veut :
    - voir ce qui est dans le sprint courant
    - connaître les tâches du sprint actif
    - savoir qui fait quoi dans le sprint

    Mots-clés : sprint, sprint actif, sprint en cours, tickets du sprint

    Args:
        project_key: clé du projet (ex: "WEB")
        limit: nombre max de tickets (défaut 50)
    Returns:
        {"status": "ok", "sprint": "...", "issues": [...]}
    """
    try:
        try:
            issues = _jql(
                f"project = {project_key} AND sprint in openSprints() ORDER BY status ASC",
                _FIELDS,
                limit,
            )
            sprint_name = issues[0]["sprint"] if issues else None
        except Exception:
            issues = _jql(
                f'project = {project_key} AND status in ("To Do", "In Progress") ORDER BY updated DESC',
                _FIELDS,
                limit,
            )
            sprint_name = None
        return {
            "status": "ok",
            "board_type": "scrum" if sprint_name else "kanban",
            "sprint": sprint_name,
            "count": len(issues),
            "issues": issues,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_create_issue")
def jira_create_issue(
    project_key: str,
    summary: str,
    issue_type: str = "Task",
    description: Optional[str] = None,
    assignee_account_id: Optional[str] = None,
    priority: Optional[str] = None,
    parent_key: Optional[str] = None,
) -> dict:
    """
    Crée un nouveau ticket Jira dans un projet.

    Utilise ce tool quand l'utilisateur veut :
    - créer un ticket, une tâche, un bug ou une story Jira
    - ajouter une issue dans un projet
    - ouvrir un nouveau ticket
    - créer une sous-tâche sous un ticket existant

    Mots-clés : créer ticket jira, nouvelle tâche jira, ouvrir une issue, ajouter un ticket, sous-tâche, subtask

    Args:
        project_key: clé du projet (ex: "KAN")
        summary: titre du ticket
        issue_type: type de ticket ("Tâche", "Bug", "Story", "Epic", "Spike", "Sous-tâche") — défaut "Task". Pour une sous-tâche, utilise "Sous-tâche" ou "Subtask" (le code gère la traduction automatiquement)
        description: description optionnelle
        assignee_account_id: account ID Jira de l'assigné (optionnel)
        priority: priorité ("Highest", "High", "Medium", "Low", "Lowest") — optionnel
        parent_key: clé du ticket parent (obligatoire si issue_type="Subtask", ex: "KAN-27")

    IMPORTANT — règles sur les sous-tâches :
    - Une Sous-tâche peut être créée sous N'IMPORTE quel type de ticket (Task, Story, Bug…).
    - Ne jamais créer une Task indépendante à la place d'une Sous-tâche demandée.
    - Ne jamais refuser sous prétexte que le parent n'est pas une Story.
    Returns:
        {"status": "ok", "key": "KAN-42", "url": "..."}
    """
    try:
        item = {"summary": summary, "issue_type": issue_type, "description": description, "priority": priority, "parent_key": parent_key}
        result = _create_single(project_key, item)
        if assignee_account_id:
            key_tmp = result.get("key", "")
            try:
                _, auth = _auth()
                requests.put(_api(f"issue/{key_tmp}/assignee"), auth=auth,
                             headers={"Content-Type": "application/json"},
                             json={"accountId": assignee_account_id}, timeout=10)
            except Exception:
                pass
        key = result.get("key", "")
        base, _ = _auth()
        return {
            "status": "ok",
            "key": key,
            "url": f"{base}/browse/{key}",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _build_description_doc(text: str) -> dict:
    """Convertit un texte en Atlassian Document Format (ADF)."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    content = [
        {"type": "paragraph", "content": [{"type": "text", "text": p}]}
        for p in paragraphs
    ]
    return {"type": "doc", "version": 1, "content": content or [{"type": "paragraph", "content": []}]}


def _create_single(project_key: str, item: dict, epic_key: str | None = None) -> dict:
    """Crée un seul ticket et retourne son résultat brut."""
    issue_type = item.get("issue_type", "Story")
    fields: dict = {
        "project": {"key": project_key},
        "summary": item["summary"],
        "issuetype": {"name": issue_type},
    }

    if item.get("description"):
        fields["description"] = _build_description_doc(item["description"])

    if item.get("priority"):
        fields["priority"] = {"name": item["priority"]}

    # Les sous-tâches nécessitent un champ "parent" obligatoire
    if issue_type in _SUBTASK_ALIASES:
        parent_key = item.get("parent_key") or epic_key
        if not parent_key:
            raise ValueError("Une sous-tâche nécessite un 'parent_key' (ex: 'KAN-42')")
        fields["parent"] = {"key": parent_key}
        # Essaie les noms possibles selon la langue du projet Jira
        for type_name in ("Sous-tâche", "Sub-task", "Subtask"):
            fields["issuetype"] = {"name": type_name}
            try:
                return _post("issue", {"fields": fields})
            except RuntimeError:
                continue
        raise RuntimeError("Impossible de créer la sous-tâche : aucun type 'Sous-tâche'/'Sub-task'/'Subtask' trouvé dans ce projet.")
    elif epic_key:
        fields["customfield_10014"] = epic_key

    return _post("issue", {"fields": fields})


@tool("jira_create_issues_bulk")
def jira_create_issues_bulk(project_key: str, issues: list) -> dict:
    """
    Crée plusieurs tickets Jira en une seule fois, en respectant la hiérarchie Epic → Story → Task → Subtask.

    Utilise ce tool quand l'utilisateur veut :
    - importer une liste de tickets dans un projet
    - créer plusieurs user stories, tâches ou bugs d'un coup
    - mettre en place un backlog complet avec des epics et des stories
    - ajouter plusieurs tickets en masse dans un projet Jira

    Mots-clés : créer plusieurs tickets, importer des tickets, backlog, user stories, liste de tâches jira

    BEST PRACTICES à respecter :
    - Créer les Epics en premier, puis lier les Stories/Tasks à leurs Epics via epic_key
    - User Stories : format "En tant que <rôle>, je veux <action>, afin de <bénéfice>"
    - Bugs : format "Le système <fait quoi> alors qu'il devrait <faire quoi>"
    - Tasks : format verbe à l'infinitif ("Configurer la base de données", "Implémenter l'API")

    Args:
        project_key: clé du projet (ex: "KAN")
        issues: liste de dicts avec les champs suivants :
            - summary (str, obligatoire) : titre du ticket
            - issue_type (str) : "Epic", "Story", "Task", "Bug", "Subtask" (défaut: "Story")
            - description (str, optionnel) : description complète
            - priority (str, optionnel) : "Highest", "High", "Medium", "Low", "Lowest"
            - epic_name (str, optionnel) : nom court de l'epic (pour les Epics uniquement)
            - epic_key (str, optionnel) : clé de l'epic parent (ex: "KAN-1") pour lier une Story à un Epic
            - parent_key (str, obligatoire si Subtask) : clé du ticket parent (ex: "KAN-42") pour les sous-tâches
    Returns:
        {"status": "ok", "created": [{"key", "summary", "type", "url"}, ...], "errors": [...]}
    """
    created = []
    errors = []
    ordered = sorted(issues, key=lambda x: 0 if x.get("issue_type") == "Epic" else 1)

    for item in ordered:
        summary = item.get("summary", "").strip()
        if not summary:
            continue
        try:
            result = _create_single(project_key, item, epic_key=item.get("epic_key"))
            key = result.get("key", "")
            base, _ = _auth()
            created.append({
                "key": key,
                "summary": summary,
                "type": item.get("issue_type", "Story"),
                "url": f"{base}/browse/{key}",
            })
        except Exception as e:
            try:
                item_copy = {k: v for k, v in item.items() if k != "epic_key"}
                result = _create_single(project_key, item_copy)
                key = result.get("key", "")
                base, _ = _auth()
                created.append({
                    "key": key,
                    "summary": summary,
                    "type": item.get("issue_type", "Story"),
                    "url": f"{base}/browse/{key}",
                    "note": "Epic link non supporté sur cette instance",
                })
            except Exception as e2:
                errors.append({"summary": summary, "error": str(e2)})

    return {
        "status": "ok" if not errors else "partial",
        "created_count": len(created),
        "created": created,
        "errors": errors,
    }


@tool("jira_list_projects")
def jira_list_projects() -> dict:
    """
    Liste tous les projets Jira accessibles.

    Utilise ce tool quand l'utilisateur veut connaître les projets disponibles sur Jira.

    Mots-clés : projets jira, liste des projets, quels projets sur jira

    Returns:
        {"status": "ok", "projects": [{"key", "name", "type"}, ...]}
    """
    try:
        data = _get("project/search", {"maxResults": 100, "orderBy": "name"})
        projects = [
            {
                "key": p.get("key"),
                "name": p.get("name"),
                "type": p.get("projectTypeKey"),
                "url": f"{os.getenv('JIRA_URL', '').rstrip('/')}/browse/{p.get('key')}",
            }
            for p in data.get("values", [])
        ]
        return {"status": "ok", "count": len(projects), "projects": projects}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_add_comment")
def jira_add_comment(key: str, comment: str) -> dict:
    """
    Ajoute un commentaire sur un ticket Jira.

    Utilise ce tool quand l'utilisateur veut commenter un ticket.

    Args:
        key: clé du ticket (ex: "PROJ-42")
        comment: texte du commentaire
    Returns:
        {"status": "ok", "comment_id": "..."}
    """
    try:
        body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}],
                    }
                ],
            }
        }
        result = _post(f"issue/{key}/comment", body)
        return {"status": "ok", "comment_id": result.get("id")}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_transition_issue")
def jira_transition_issue(key: str, status_name: str) -> dict:
    """
    Change le statut d'un ticket Jira (ex: "In Progress" → "Done").

    Utilise ce tool quand l'utilisateur veut :
    - marquer un ticket comme terminé
    - passer un ticket en cours
    - changer le statut d'une tâche

    Mots-clés : changer statut jira, marquer terminé, passer en cours, transition ticket

    Args:
        key: clé du ticket (ex: "PROJ-42")
        status_name: nom du statut cible (ex: "In Progress", "Done", "To Do")
    Returns:
        {"status": "ok", "transitioned_to": "..."}
    """
    try:
        transitions = _get(f"issue/{key}/transitions")
        target = status_name.lower()
        transition_id = None
        matched_name = None
        for t in transitions.get("transitions", []):
            if t["to"]["name"].lower() == target or target in t["to"]["name"].lower():
                transition_id = t["id"]
                matched_name = t["to"]["name"]
                break
        if not transition_id:
            available = [t["to"]["name"] for t in transitions.get("transitions", [])]
            return {
                "status": "error",
                "error": f"Statut '{status_name}' introuvable. Disponibles : {available}",
            }
        base, auth = _auth()
        r = requests.post(
            f"{base}/rest/api/3/issue/{key}/transitions",
            auth=auth,
            headers={"Content-Type": "application/json"},
            json={"transition": {"id": transition_id}},
            timeout=15,
        )
        r.raise_for_status()
        return {"status": "ok", "transitioned_to": matched_name}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_get_workload")
def jira_get_workload(project_key: Optional[str] = None, limit: int = 100) -> dict:
    """
    Retourne la répartition du travail par assigné dans un projet (ou tous les projets).

    Utilise ce tool quand l'utilisateur veut :
    - voir qui fait quoi dans l'équipe
    - connaître la charge de travail de chaque membre
    - avoir une vue de la répartition des tickets

    Mots-clés : charge de travail, répartition équipe, qui travaille sur quoi, workload

    Args:
        project_key: clé du projet (optionnel, tous si absent)
        limit: nombre max de tickets analysés
    Returns:
        {"status": "ok", "by_assignee": {"Prénom Nom": {"total": N, "by_status": {...}}}}
    """
    try:
        try:
            jql = "sprint in openSprints()"
            if project_key:
                jql += f" AND project = {project_key}"
            issues = _jql(jql, _FIELDS, limit)
        except Exception:
            # Kanban fallback
            jql = 'status in ("To Do", "In Progress")'
            if project_key:
                jql += f" AND project = {project_key}"
            issues = _jql(jql, _FIELDS, limit)

        by_assignee: dict[str, dict] = {}
        for issue in issues:
            name = issue.get("assignee") or "Non assigné"
            if name not in by_assignee:
                by_assignee[name] = {"total": 0, "by_status": {}}
            by_assignee[name]["total"] += 1
            st = issue["status"] or "Unknown"
            by_assignee[name]["by_status"][st] = by_assignee[name]["by_status"].get(st, 0) + 1

        return {"status": "ok", "by_assignee": by_assignee}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_assign_issue")
def jira_assign_issue(key: str, user_name: Optional[str] = None) -> dict:
    """
    Assigne un ticket Jira à l'utilisateur courant ou à une autre personne.

    Utilise ce tool quand l'utilisateur veut :
    - s'assigner un ticket ("assigne-moi le ticket", "assigne-le moi")
    - assigner un ticket à quelqu'un d'autre
    - changer l'assigné d'un ticket

    Mots-clés : assigner ticket jira, m'assigner, changer l'assigné, assigner à moi

    Args:
        key: clé du ticket (ex: "KAN-8")
        user_name: nom de la personne à qui assigner (si absent → assigne à l'utilisateur courant)
    Returns:
        {"status": "ok", "assigned_to": "Prénom Nom", "account_id": "..."}
    """
    try:
        if not user_name:
            account_id = _get_account_id()
        else:
            results = _get("user/search", {"query": user_name, "maxResults": 5})
            if not results:
                return {"status": "error", "error": f"Aucun utilisateur trouvé pour '{user_name}'"}
            account_id = results[0].get("accountId", "")
            user_name = results[0].get("displayName", user_name)

        _, auth = _auth()
        r = requests.put(
            _api(f"issue/{key}/assignee"),
            auth=auth,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"accountId": account_id},
            timeout=15,
        )
        r.raise_for_status()
        return {"status": "ok", "assigned_to": user_name or "toi", "key": key}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_update_issue")
def jira_update_issue(
    key: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    issue_type: Optional[str] = None,
) -> dict:
    """
    Met à jour les champs d'un ticket Jira existant.

    Utilise ce tool quand l'utilisateur veut :
    - modifier le titre ou la description d'un ticket
    - changer la priorité d'un ticket
    - mettre à jour un ticket existant

    Mots-clés : modifier ticket jira, mettre à jour, changer le titre, éditer un ticket

    Args:
        key: clé du ticket (ex: "KAN-8")
        summary: nouveau titre (optionnel)
        description: nouvelle description (optionnel)
        priority: nouvelle priorité ("Highest", "High", "Medium", "Low", "Lowest") (optionnel)
        issue_type: nouveau type ("Task", "Bug", "Story") (optionnel)
    Returns:
        {"status": "ok", "key": "..."}
    """
    try:
        fields: dict = {}
        if summary:
            fields["summary"] = summary
        if description:
            fields["description"] = {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
            }
        if priority:
            fields["priority"] = {"name": priority}
        if issue_type:
            fields["issuetype"] = {"name": issue_type}
        if not fields:
            return {"status": "error", "error": "Aucun champ à mettre à jour fourni"}

        _put(f"issue/{key}", {"fields": fields})
        return {"status": "ok", "key": key, "updated_fields": list(fields.keys())}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_get_issue_comments")
def jira_get_issue_comments(key: str, limit: int = 20) -> dict:
    """
    Récupère les commentaires d'un ticket Jira.

    Utilise ce tool quand l'utilisateur veut :
    - lire les commentaires d'un ticket
    - voir les échanges sur une issue
    - consulter l'historique de discussion d'un ticket

    Mots-clés : commentaires ticket jira, voir les échanges, historique ticket

    Args:
        key: clé du ticket (ex: "KAN-8")
        limit: nombre max de commentaires (défaut 20)
    Returns:
        {"status": "ok", "comments": [{"author", "text", "created"}, ...]}
    """
    try:
        data = _get(f"issue/{key}/comment", {"maxResults": limit, "orderBy": "created"})
        comments = []
        for c in data.get("comments", []):
            author = (c.get("author") or {}).get("displayName", "?")
            created = (c.get("created") or "")[:10]
            text = _extract_text(c.get("body"))
            comments.append({"author": author, "created": created, "text": text})
        return {"status": "ok", "count": len(comments), "comments": comments}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_search_users")
def jira_search_users(query: str) -> dict:
    """
    Recherche des utilisateurs Jira par nom ou email.

    Utilise ce tool quand l'utilisateur veut trouver l'account ID d'une personne pour l'assigner.

    Args:
        query: nom ou email à rechercher
    Returns:
        {"status": "ok", "users": [{"name", "email", "account_id"}, ...]}
    """
    try:
        results = _get("user/search", {"query": query, "maxResults": 10})
        users = [
            {
                "name": u.get("displayName"),
                "email": u.get("emailAddress"),
                "account_id": u.get("accountId"),
            }
            for u in results
            if not u.get("accountType") == "app"
        ]
        return {"status": "ok", "count": len(users), "users": users}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_move_issue")
def jira_move_issue(key: str, target_project_key: str) -> dict:
    """
    Déplace un ticket vers un autre projet Jira.

    Utilise ce tool quand l'utilisateur veut déplacer un ticket d'un projet à un autre.

    Args:
        key: clé du ticket source (ex: "KAN-8")
        target_project_key: clé du projet cible (ex: "WEB")
    Returns:
        {"status": "ok", "new_key": "WEB-12"}
    """
    try:
        result = _post(f"issue/{key}/move", {"project": {"key": target_project_key}})
        return {"status": "ok", "new_key": result.get("key", ""), "target_project": target_project_key}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_delete_issue")
def jira_delete_issue(key: str) -> dict:
    """
    Supprime définitivement un ticket Jira.

    Utilise ce tool quand l'utilisateur veut :
    - supprimer un ticket en doublon
    - effacer un ticket créé par erreur

    ⚠ Action irréversible — demander confirmation avant d'appeler ce tool.

    Args:
        key: clé du ticket à supprimer (ex: "KAN-29")
    Returns:
        {"status": "ok", "deleted": "KAN-29"}
    """
    try:
        base, auth = _auth()
        r = requests.delete(
            _api(f"issue/{key}"),
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if r.status_code in (200, 204):
            return {"status": "ok", "deleted": key}
        return {"status": "error", "error": f"{r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@tool("jira_link_to_epic")
def jira_link_to_epic(issue_key: str, epic_key: str) -> dict:
    """
    Lie un ticket (Story, Task) à un Epic existant.

    Utilise ce tool quand l'utilisateur veut :
    - rattacher un ticket à un Epic
    - organiser les tickets sous un Epic parent
    - lier des USE à leur US Epic

    Mots-clés : lier à l'epic, rattacher à l'epic, mettre sous l'epic, organiser tickets

    Args:
        issue_key: clé du ticket à lier (ex: "KAN-25")
        epic_key: clé de l'Epic parent (ex: "KAN-10")
    Returns:
        {"status": "ok", "issue": "KAN-25", "epic": "KAN-10"}
    """
    try:
        try:
            _put(f"issue/{issue_key}", {"fields": {"customfield_10014": epic_key}})
            return {"status": "ok", "issue": issue_key, "epic": epic_key}
        except Exception:
            pass
        _put(f"issue/{issue_key}", {"fields": {"parent": {"key": epic_key}}})
        return {"status": "ok", "issue": issue_key, "epic": epic_key}
    except Exception as e:
        return {"status": "error", "error": str(e)}
