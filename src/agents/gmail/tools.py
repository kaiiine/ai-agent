from langchain_core.tools import tool
from src.infra.google_auth import get_gmail_service
from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import base64
import os
import re
from email.utils import parsedate_to_datetime

# --- Brouillon global ---
#
# Un seul brouillon par PROCESSUS : deux fils de conversation qui rédigent en
# parallèle s'écrasent. C'est assumé pour l'instant — le flux brouillon → relecture
# → confirmation est mono-utilisateur par nature — mais `_CHAMPS` rend la liste
# explicite pour qu'un futur passage à un brouillon par thread n'oublie rien.
_CHAMPS = ("to", "cc", "bcc", "subject", "body",
           "pieces_jointes", "repondre_a", "thread_id", "references")

_draft: dict = {c: None for c in _CHAMPS} | {"has_draft": False}


def _vider_brouillon() -> None:
    _draft.update({c: None for c in _CHAMPS})
    _draft["has_draft"] = False


def _build_html(body: str, subject: str) -> str:
    """Wrap le corps en HTML avec le template Axon (dark + orange).

    La conversion passe par `src.infra.markdown_rendu`, partagée avec les Docs et
    Slack. Deux défauts mesurés disparaissent avec elle :

      · la liste d'extensions était `["nl2br", "fenced_code"]` — sans `tables`.
        Un tableau markdown, que tout rapport contient, arrivait en PIPES BRUTS
        dans un paragraphe ;
      · les règles de typographie vivaient dans une balise `<style>` placée
        DANS un `<td>`. Gmail l'accepte aujourd'hui, plusieurs clients dont
        Outlook l'ignorent, et une règle ignorée rend le rapport nu sans que
        personne le sache. Tout est désormais en style EN LIGNE.
    """
    from src.infra.markdown_rendu import en_html
    body_html = en_html(body)
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

    from src.infra.markdown_rendu import en_texte

    corps = _draft["body"]
    alternatif = MIMEMultipart("alternative")
    # La version texte comptait autant que la version HTML et recevait le markdown
    # BRUT — donc les dièses et les astérisques, pour tout client en mode texte et
    # tout lecteur d'écran. Elle est maintenant rendue, elle aussi.
    alternatif.attach(MIMEText(en_texte(corps), "plain", "utf-8"))
    alternatif.attach(MIMEText(_build_html(corps, _draft["subject"]), "html", "utf-8"))

    jointes = [p for p in (_draft["pieces_jointes"] or []) if p]
    if jointes:
        msg = MIMEMultipart("mixed")
        msg.attach(alternatif)
    else:
        msg = alternatif

    msg["to"] = _draft["to"]
    msg["subject"] = _draft["subject"]
    if _draft["cc"]:
        msg["cc"] = _draft["cc"]
    if _draft["bcc"]:
        msg["bcc"] = _draft["bcc"]

    # Sans ces deux en-têtes, une réponse arrive comme un NOUVEAU fil chez le
    # destinataire — l'échange se disperse au lieu de se suivre.
    if _draft["repondre_a"]:
        msg["In-Reply-To"] = _draft["repondre_a"]
        msg["References"] = _draft["references"] or _draft["repondre_a"]

    manquantes = []
    for chemin in jointes:
        p = Path(chemin).expanduser()
        if not p.is_file():
            manquantes.append(str(p))
            continue
        piece = MIMEBase("application", "octet-stream")
        piece.set_payload(p.read_bytes())
        encoders.encode_base64(piece)
        piece.add_header("Content-Disposition", "attachment", filename=p.name)
        msg.attach(piece)
    if manquantes:
        # Envoyer un mail en annonçant une pièce jointe qui n'y est pas serait la
        # même faute que compter un asset non téléchargé.
        return f"Envoi annulé — pièce(s) jointe(s) introuvable(s) : {', '.join(manquantes)}"

    corps_api: dict = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if _draft["thread_id"]:
        corps_api["threadId"] = _draft["thread_id"]

    service = get_gmail_service()
    res = service.users().messages().send(userId="me", body=corps_api).execute()

    to, n = _draft["to"], len(jointes)
    _vider_brouillon()
    suffixe = f" · {n} pièce(s) jointe(s)" if n else ""
    return f"Email envoyé à {to} — ID: `{res.get('id')}`{suffixe}"


def _draft_summary() -> str:
    extra = []
    if _draft["cc"]:
        extra.append(f"Cc : {_draft['cc']}")
    if _draft["pieces_jointes"]:
        extra.append(f"{len(_draft['pieces_jointes'])} pièce(s) jointe(s)")
    suffixe = (" · " + " · ".join(extra)) if extra else ""
    return (f"Brouillon enregistré — À : {_draft['to']} · "
            f"Objet : {_draft['subject']}{suffixe}")

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

    # UN seul aller-retour pour toutes les en-têtes. Avant, c'était un `get` PAR
    # message : huit allers-retours pour sept mails, et c'est ce qui donnait
    # l'impression que l'agent traînait sur Gmail.
    entetes: dict[str, dict] = {}

    def _recolte(request_id, reponse, exception):
        if exception is None and reponse:
            entetes[request_id] = {
                h["name"]: h["value"] for h in reponse["payload"]["headers"]}

    lot = service.new_batch_http_request(callback=_recolte)
    for m in msgs:
        lot.add(service.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date"]), request_id=m["id"])
    lot.execute()

    rows = []
    for i, m in enumerate(msgs, 1):
        headers = entetes.get(m["id"], {})
        sender = headers.get("From", "?")
        subject = headers.get("Subject", "(sans sujet)")
        date = headers.get("Date", "?")
        rows.append(f"| {i} | `{m['id']}` | {sender} | {subject} | {date} |")
    table = (
        "| # | ID | De | Objet | Date |\n"
        "|---|----|----|-------|------|\n"
        + "\n".join(rows)
    )
    return f"📬 **{len(rows)} mail(s)**\n\n{table}"

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
def gmail_send_email(to: str, subject: str, body: str, cc: str = "",
                     bcc: str = "", pieces_jointes: list[str] | None = None) -> str:
    """
    Prépare un brouillon d’email Gmail (sans l’envoyer) pour révision avant envoi.

    Utilise ce tool quand l’utilisateur veut :
    - écrire un email, un mail, un message à quelqu’un
    - rédiger un email à envoyer via Gmail
    - composer une réponse à un mail

    Mots-clés : envoyer mail, écrire email, rédiger message, gmail, email, destinataire, sujet

    Le corps s'écrit en MARKDOWN : titres, **gras**, listes, tableaux et liens sont
    mis en forme dans le mail envoyé, en HTML comme en version texte.

    **Args:**
        - `to` (str) : Adresse du destinataire (plusieurs séparées par des virgules)
        - `subject` (str) : Objet du mail
        - `body` (str) : Corps du message, en markdown
        - `cc` (str, optionnel) : copie
        - `bcc` (str, optionnel) : copie cachée
        - `pieces_jointes` (list[str], optionnel) : chemins de fichiers à joindre

    **Returns:**
        - Markdown affichant le brouillon créé et rappelant les prochaines actions possibles
    """
    _vider_brouillon()
    _draft.update({
        "to": to, "subject": subject, "body": body,
        "cc": cc or None, "bcc": bcc or None,
        "pieces_jointes": list(pieces_jointes or []) or None,
        "has_draft": True,
    })
    return _draft_summary()


@tool
def gmail_reply(message_id: str, body: str, tous: bool = False) -> str:
    """
    Prépare une RÉPONSE à un mail existant, dans le même fil de discussion.

    Utilise ce tool quand l'utilisateur veut :
    - répondre à un mail reçu
    - donner suite à un message précis
    - relancer dans une conversation existante

    Mots-clés : répondre, réponse, mail, fil, conversation, relancer, suite

    À la différence de gmail_send_email, la réponse porte les en-têtes
    `In-Reply-To` et `References` et le `threadId` d'origine : elle s'affiche donc
    DANS la conversation chez le destinataire, au lieu d'ouvrir un fil séparé.

    Args:
        message_id: identifiant du mail auquel répondre (via gmail_search)
        body: corps de la réponse, en markdown
        tous: True pour répondre à tous (met les autres destinataires en copie)
    Returns:
        Résumé du brouillon, à confirmer avec gmail_confirm_send
    """
    service = get_gmail_service()
    msg = service.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["From", "To", "Cc", "Subject", "Message-ID", "References"],
    ).execute()
    h = {k["name"].lower(): k["value"] for k in msg["payload"]["headers"]}

    objet = h.get("subject", "(sans objet)")
    if not objet.lower().startswith("re:"):
        objet = f"Re: {objet}"

    identifiant = h.get("message-id", "")
    _vider_brouillon()
    _draft.update({
        "to": h.get("from", ""),
        "cc": (h.get("cc") if tous else None) or None,
        "subject": objet,
        "body": body,
        "repondre_a": identifiant or None,
        "references": " ".join(x for x in (h.get("references"), identifiant) if x) or None,
        "thread_id": msg.get("threadId"),
        "has_draft": True,
    })
    return f"{_draft_summary()} · réponse dans le fil"

@tool
def gmail_edit_draft(field: str, value: str) -> str:
    """
    Modifie un champ (destinataire, sujet ou corps) du brouillon email en cours.

    Utilise ce tool quand l’utilisateur veut :
    - corriger l’adresse, l’objet ou le texte d’un mail déjà rédigé
    - changer quelque chose dans le brouillon avant envoi

    Mots-clés : modifier mail, corriger email, brouillon, changer destinataire, modifier sujet

    **Args:**
        - `field` (str) : Champ à modifier (`"to"`, `"cc"`, `"bcc"`, `"subject"`, `"body"`)
        - `value` (str) : Nouvelle valeur

    **Returns:**
        - Markdown avec le brouillon mis à jour ou un message d’erreur si aucun brouillon actif
    """
    if not _draft["has_draft"]:
        return "Aucun brouillon en cours. Dis par ex. “Écris un mail à …” pour en créer un."
    if field not in {"to", "cc", "bcc", "subject", "body"}:
        return "Champ invalide. Utilise 'to', 'cc', 'bcc', 'subject' ou 'body'."
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
