from langchain_core.tools import tool
#from src.agents.gmail.gmail_client import get_gmail_service
from src.infra.google_auth import get_gmail_service
from email.mime.text import MIMEText
import base64

# --- Brouillon global ---
_draft = {"to": None, "subject": None, "body": None, "has_draft": False}

def _draft_markdown(prefix="📤 Brouillon"):
    return (
        f"## {prefix}\n"
        f"**À :** {_draft['to']}\n"
        f"**Sujet :** {_draft['subject']}\n\n"
        f"{_draft['body']}\n\n"
        f"**🎯 Actions proposées :**\n"
        f"- Modifier : `Change l'adresse/sujet/corps ...`\n"
        f"- Envoyer : `Envoie-le` (appelle `gmail_confirm_send`)\n"
    )

@tool
def gmail_search(query: str = "newer_than:7d", max_results: int = 7) -> str:
    """
    Recherche et liste les emails Gmail selon un filtre (date, expéditeur, objet, statut).

    Utilise ce tool quand l'utilisateur veut :
    - voir ses derniers emails ou mails non lus
    - chercher un mail d'une personne précise
    - trouver un email avec un sujet particulier
    - consulter sa boîte de réception récente

    Mots-clés : mail, email, gmail, boîte, réception, non lu, message, expéditeur, objet

    **Args:**
        - `query` (str, optionnel) : Requête Gmail.  
          Exemples :
            * `"newer_than:7d"` (par défaut) → 7 derniers jours
            * `"is:unread"` → mails non lus
            * `"from:alice@gmail.com"` → mails d’Alice
            * `"subject:urgent"` → objet contenant "urgent"
        - `max_results` (int, optionnel) : Nombre de mails à lister (défaut 7, conseillé ≤10)

    **Returns:**
        - Chaîne Markdown listant les mails trouvés, numérotés avec :
            * Expéditeur
            * Objet
            * Date
        - Retourne `"📭 Aucun mail trouvé."` si la boîte est vide selon la requête.

    **Raises:**
        - `googleapiclient.errors.HttpError` si l’API Gmail échoue
        - Erreurs réseau en cas d’absence de connexion

    **Example:**
        ```python
        gmail_search("is:unread", max_results=5)
        ```
    """
    service = get_gmail_service()
    res = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    msgs = res.get("messages", [])
    if not msgs:
        return "📭 Aucun mail trouvé."
    out = ["# 📬 Derniers mails", ""]
    for i, m in enumerate(msgs, 1):
        meta = service.users().messages().get(
            userId="me", id=m["id"], format="metadata", metadataHeaders=["From","Subject","Date"]
        ).execute()
        headers = {h["name"]: h["value"] for h in meta["payload"]["headers"]}
        out.append(f"**{i}.** **De :** {headers.get('From','?')}  \n"
                   f"**Objet :** {headers.get('Subject','(sans sujet)')}  \n"
                   f"**Date :** {headers.get('Date','?')}\n")
    return "\n".join(out)

@tool
def gmail_summarize(message_id: str) -> str:
    """
    Lit et résume le contenu complet d'un email Gmail à partir de son identifiant.

    Utilise ce tool quand l'utilisateur veut :
    - lire le contenu d'un mail en détail
    - savoir ce que dit un email précis
    - résumer un message reçu

    Mots-clés : mail, email, lire, contenu, résumé, corps du message, détail

    **Args:**
        - `message_id` (str) : Identifiant Gmail du message à résumer  
          (obtenu via `gmail_search()` ou depuis l’URL Gmail).

    **Returns:**
        - Chaîne Markdown avec :
            * Expéditeur, Objet, Date
            * Extrait généré par Gmail
            * Début du corps (max 1000 caractères)

    **Raises:**
        - Erreurs API Gmail si l’ID est invalide ou introuvable

    **Note:**
        - HTML → texte brut automatique
        - Corps tronqué pour éviter les réponses trop longues
    """
    service = get_gmail_service()
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

    headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
    snippet = msg.get("snippet", "")
    body_parts = []

    def extract_parts(payload):
        if "body" in payload and "data" in payload["body"]:
            body_parts.append(base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore"))
        for part in payload.get("parts", []):
            extract_parts(part)

    extract_parts(msg["payload"])
    body_text = "\n".join(body_parts)

    return (
        f"# 📨 Résumé du mail\n"
        f"**De :** {headers.get('From')}  \n"
        f"**Objet :** {headers.get('Subject')}  \n"
        f"**Date :** {headers.get('Date')}  \n\n"
        f"**Extrait :**\n{snippet}\n\n"
        f"**Corps (début) :**\n{body_text[:1000]}{'...' if len(body_text) > 1000 else ''}"
    )

@tool
def gmail_send_email(to: str, subject: str, body: str) -> str:
    """
    Prépare un brouillon d’email Gmail (sans l’envoyer) pour révision avant envoi.

    Utilise ce tool quand l’utilisateur veut :
    - écrire un email, un mail, un message à quelqu’un
    - rédiger un email à envoyer via Gmail
    - composer une réponse à un mail

    Mots-clés : envoyer mail, écrire email, rédiger message, gmail, email, destinataire, sujet

    **Args:**
        - `to` (str) : Adresse du destinataire
        - `subject` (str) : Objet du mail
        - `body` (str) : Corps du message (texte brut)

    **Returns:**
        - Markdown affichant le brouillon créé et rappelant les prochaines actions possibles
    """
    _draft["to"] = to
    _draft["subject"] = subject
    _draft["body"] = body
    _draft["has_draft"] = True
    return _draft_markdown(prefix="📤 Brouillon enregistré")

@tool
def gmail_edit_draft(field: str, value: str) -> str:
    """
    Modifie un champ (destinataire, sujet ou corps) du brouillon email en cours.

    Utilise ce tool quand l’utilisateur veut :
    - corriger l’adresse, l’objet ou le texte d’un mail déjà rédigé
    - changer quelque chose dans le brouillon avant envoi

    Mots-clés : modifier mail, corriger email, brouillon, changer destinataire, modifier sujet

    **Args:**
        - `field` (str) : Champ à modifier (`"to"`, `"subject"`, `"body"`)
        - `value` (str) : Nouvelle valeur

    **Returns:**
        - Markdown avec le brouillon mis à jour ou un message d’erreur si aucun brouillon actif
    """
    if not _draft["has_draft"]:
        return "⚠️ Aucun brouillon en cours. Dis par ex. “Écris un mail à …” pour en créer un."
    if field not in {"to", "subject", "body"}:
        return "⚠️ Champ invalide. Utilise 'to', 'subject' ou 'body'."
    _draft[field] = value
    return _draft_markdown(prefix="✏️ Brouillon mis à jour")

@tool
def gmail_confirm_send() -> str:
    """
    Envoie définitivement le brouillon Gmail en cours après validation.

    Utilise ce tool quand l'utilisateur veut :
    - confirmer et envoyer le mail rédigé
    - valider l'envoi d'un email

    Mots-clés : envoyer mail, confirmer envoi, valider email, expédier, send

    **Returns:**
        - Confirmation avec l’ID Gmail du message envoyé
        - Message d’erreur si brouillon absent ou incomplet

    **Raises:**
        - Erreurs d’authentification Gmail ou réseau
        - Erreurs API Gmail en cas de problème d’envoi
    """
    if not _draft["has_draft"]:
        return "⚠️ Aucun brouillon en cours à envoyer."
    if not _draft["to"] or not _draft["subject"] or not _draft["body"]:
        return "⚠️ Brouillon incomplet (to/subject/body requis)."

    service = get_gmail_service()
    msg = MIMEText(_draft["body"])
    msg["to"] = _draft["to"]
    msg["subject"] = _draft["subject"]
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    res = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    _draft.update({"to": None, "subject": None, "body": None, "has_draft": False})
    return f"✅ Email envoyé ! ID: `{res.get('id')}`"
