from langchain_core.tools import tool
from src.infra.google_auth import get_gmail_service
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
import os

# --- Brouillon global ---
_draft = {"to": None, "subject": None, "body": None, "has_draft": False}


def _build_html(body: str, subject: str) -> str:
    """Wrap le corps en HTML avec le template Axon (dark + orange). Markdown → HTML."""
    import markdown as _md
    body_html = _md.markdown(body, extensions=["nl2br", "fenced_code"])
    sender_name = os.getenv("USER_NAME", "Axon")
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{subject}</title>
</head>
<body style="margin:0;padding:0;background-color:#111111;font-family:'Courier New',Courier,monospace;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color:#111111;padding:32px 0;">
    <tr>
      <td align="center">
        <table width="580" cellpadding="0" cellspacing="0" style="background-color:#1a1a1a;border:1px solid #FF8700;border-radius:4px;overflow:hidden;">

          <!-- Header -->
          <tr>
            <td style="background-color:#111111;padding:20px 32px;border-bottom:1px solid #FF8700;">
              <span style="color:#FF8700;font-size:13px;font-weight:bold;letter-spacing:6px;text-transform:uppercase;">A · X · O · N</span>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px;color:#e0e0e0;font-size:14px;line-height:1.8;">
              <style>
                p {{ margin: 0 0 14px 0; }}
                strong {{ color: #FF8700; }}
                em {{ color: #cccccc; font-style: italic; }}
                ul, ol {{ padding-left: 20px; margin: 0 0 14px 0; }}
                li {{ margin-bottom: 6px; }}
                code {{ background: #222; color: #FF8700; padding: 1px 5px; border-radius: 3px; font-family: 'Courier New', monospace; font-size: 13px; }}
                pre {{ background: #222; border-left: 3px solid #FF8700; padding: 12px 16px; border-radius: 3px; overflow: auto; }}
                pre code {{ background: none; padding: 0; color: #e0e0e0; }}
                a {{ color: #FF8700; }}
                blockquote {{ border-left: 3px solid #FF8700; margin: 0 0 14px 0; padding-left: 16px; color: #999; }}
              </style>
              {body_html}
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:16px 32px 24px;border-top:1px solid #2a2a2a;">
              <span style="color:#555555;font-size:11px;font-family:'Courier New',Courier,monospace;">
                — {sender_name} · envoyé via Axon
              </span>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _do_send() -> str:
    """Envoie réellement le brouillon en cours avec template HTML Axon."""
    if not _draft["has_draft"]:
        return "Aucun brouillon en cours à envoyer."
    if not _draft["to"] or not _draft["subject"] or not _draft["body"]:
        return "Brouillon incomplet (to/subject/body requis)."

    msg = MIMEMultipart("alternative")
    msg["to"] = _draft["to"]
    msg["subject"] = _draft["subject"]

    msg.attach(MIMEText(_draft["body"], "plain", "utf-8"))
    msg.attach(MIMEText(_build_html(_draft["body"], _draft["subject"]), "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service = get_gmail_service()
    res = service.users().messages().send(userId="me", body={"raw": raw}).execute()

    to = _draft["to"]
    _draft.update({"to": None, "subject": None, "body": None, "has_draft": False})
    return f"Email envoyé à {to} — ID: `{res.get('id')}`"


def _draft_summary() -> str:
    return f"Brouillon enregistré — À : {_draft['to']} · Objet : {_draft['subject']}"

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
    return _draft_summary()

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
        return "Aucun brouillon en cours. Dis par ex. “Écris un mail à …” pour en créer un."
    if field not in {"to", "subject", "body"}:
        return "Champ invalide. Utilise 'to', 'subject' ou 'body'."
    _draft[field] = value
    return _draft_summary()

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
    return _do_send()
