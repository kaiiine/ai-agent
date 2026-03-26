from langchain_core.tools import tool
from configs.config import MAIL_SETTINGS
from imap_tools import MailBox, AND
from itertools import islice
from src.agents.email.emailAgent import EmailAgent

def connect():
    mb = MailBox(MAIL_SETTINGS['imap_host'])
    mb.login(MAIL_SETTINGS['imap_user'], MAIL_SETTINGS['imap_password'], MAIL_SETTINGS['imap_folder'])
    return mb

@tool
def list_unread_emails(agent) -> str:
    """Liste les e-mails non lus (UID, sujet, date, expéditeur)."""
    with connect() as mb:
        unread_iter = mb.fetch(AND(seen=False), headers_only=True, mark_seen=False, reverse=True)
        emails = list(islice(unread_iter, 5))  # Limité à 5 pour la vitesse
        if not emails:
            result = "📭 **Aucun message non lu.**"
        else:
            # Formatage direct en Markdown - pas besoin d'LLM !
            result = f"📧 **{len(emails)} emails non lus :**\n\n"
            result += "| UID | Sujet | Date | Expéditeur |\n"
            result += "|-----|-------|------|------------|\n"
            
            for mail in emails:
                # Tronquer le sujet si trop long
                subject = mail.subject[:50] + "..." if len(mail.subject) > 50 else mail.subject
                result += f"| `{mail.uid}` | {subject} | {mail.date.strftime('%d/%m %H:%M')} | {mail.from_} |\n"
        return result

# Prend l'agent en paramètre
def make_email_tools(agent):

    @tool
    def list_unread_email() -> str:
        """Liste les e-mails non lus (UID, sujet, date, expéditeur)."""
        return agent.list_unread_emails()

    @tool
    def list_all_emails() -> str:
        """Liste tous les e-mails (lus et non lus) avec leur statut."""
        return agent.list_all_emails()

    @tool
    def list_sent_emails() -> str:
        """Liste les emails envoyés récemment."""
        return agent.list_sent_emails()

    @tool
    def summarize_email(uid: str) -> str:
        """Résume un e-mail donné son UID."""
        return agent.summarize_email(uid)

    @tool
    def view_sent_email(uid: str) -> str:
        """Affiche le contenu complet d'un email envoyé en utilisant son UID."""
        return agent.view_sent_email(uid)

    @tool
    def mark_email_as_read(uid: str) -> str:
        """Marque un e-mail comme lu en utilisant son UID."""
        return agent.mark_email_as_read(uid)

    @tool
    def compose_email(recipient: str, subject_hint: str, content_request: str) -> str:
        """Compose automatiquement un email selon les instructions données. 
        Args:
            recipient: L'adresse email du destinataire
            subject_hint: Le sujet ou thème de l'email
            content_request: Ce que doit contenir l'email
        """
        return agent.compose_email(recipient, subject_hint, content_request)

    @tool
    def send_email(recipient: str, subject: str, body: str) -> str:
        """Envoie un email après validation de l'utilisateur.
        Args:
            recipient: L'adresse email du destinataire
            subject: L'objet de l'email
            body: Le corps du message
        """
        return agent.send_email(recipient, subject, body)

    @tool
    def test_smtp_connection() -> str:
        """Teste la connexion SMTP pour diagnostiquer les problèmes d'envoi d'emails."""
        return agent.test_smtp_connection()

    return [list_unread_email, list_all_emails, list_sent_emails, summarize_email, view_sent_email, mark_email_as_read, compose_email, send_email, test_smtp_connection]
