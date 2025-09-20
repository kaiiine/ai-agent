from configs.config import MAIL_SETTINGS
from imap_tools import MailBox, AND
from itertools import islice
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
from src.llm.models import make_llm


class EmailAgent:
    def __init__(self):
        self.host = MAIL_SETTINGS['imap_host']
        self.user = MAIL_SETTINGS['imap_user']
        self.password = MAIL_SETTINGS['imap_password']
        self.folder = MAIL_SETTINGS['imap_folder']
        self.email_llm = make_llm()  # LLM dédié aux emails
        
        # Cache simple pour éviter les appels répétés
        self._cache = {}
        self._cache_ttl = 30  # 30 secondes

    def connect(self):
        return MailBox(self.host).login(self.user, self.password, self.folder)
    
    def list_all_emails(self) -> str:
        """Liste tous les emails avec formatage Markdown direct."""
        with self.connect() as mb:
            all_emails_iter = mb.fetch(headers_only=True, mark_seen=False, reverse=True)
            emails = list(islice(all_emails_iter, 10))
            if not emails:
                return "📭 **Aucun message trouvé.**"
            
            # Formatage direct en Markdown
            result = f"📬 **{len(emails)} emails récents :**\n\n"
            result += "| UID | Sujet | Date | Expéditeur | Statut |\n"
            result += "|-----|-------|------|------------|--------|\n"
            
            for mail in emails:
                subject = mail.subject[:40] + "..." if len(mail.subject) > 40 else mail.subject
                status = "✅ Lu" if mail.seen else "🔵 Non lu"
                result += f"| `{mail.uid}` | {subject} | {mail.date.strftime('%d/%m %H:%M')} | {mail.from_} | {status} |\n"
            
            return result

    def list_unread_emails(self) -> str:
        """Liste les emails non lus avec formatage Markdown direct."""
        # Vérifier le cache
        cache_key = "unread_emails"
        if cache_key in self._cache:
            timestamp, data = self._cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return data + "\n\n*⚡ (Données en cache)*"
        
        with self.connect() as mb:
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
            
            # Mettre en cache
            self._cache[cache_key] = (time.time(), result)
            return result

    def list_sent_emails(self) -> str:
        """Liste les emails envoyés récemment."""
        try:
            # Se connecter au dossier des emails envoyés
            with MailBox(self.host).login(self.user, self.password, "Sent") as mb:
                sent_iter = mb.fetch(headers_only=True, mark_seen=False, reverse=True)
                emails = list(islice(sent_iter, 10))
                if not emails:
                    return "📤 Aucun email envoyé trouvé."
                
                print(f"📤 J'ai trouvé {len(emails)} emails envoyés...")
                return json.dumps([
                    {
                        "uid": mail.uid,
                        "subject": mail.subject,
                        "date": mail.date.strftime("%Y-%m-%d %H:%M"),
                        "to": mail.to[0] if mail.to else "Destinataire inconnu",
                        "status": "📤 Envoyé"
                    } for mail in emails
                ], ensure_ascii=False)
        except Exception as e:
            # Essayer avec d'autres noms de dossiers communs
            for folder_name in ["INBOX.Sent", "Sent Items", "Éléments envoyés", "[Gmail]/Sent Mail"]:
                try:
                    with MailBox(self.host).login(self.user, self.password, folder_name) as mb:
                        sent_iter = mb.fetch(headers_only=True, mark_seen=False, reverse=True)
                        emails = list(islice(sent_iter, 10))
                        if emails:
                            print(f"📤 J'ai trouvé {len(emails)} emails envoyés dans {folder_name}...")
                            return json.dumps([
                                {
                                    "uid": mail.uid,
                                    "subject": mail.subject,
                                    "date": mail.date.strftime("%Y-%m-%d %H:%M"),
                                    "to": mail.to[0] if mail.to else "Destinataire inconnu",
                                    "status": "📤 Envoyé"
                                } for mail in emails
                            ], ensure_ascii=False)
                except:
                    continue
            
            return f"❌ Impossible d'accéder aux emails envoyés. Dossier introuvable. Erreur: {str(e)}"

    def summarize_email(self, uid: str) -> str:
        
        with self.connect() as mb:
            mail = next(mb.fetch(AND(uid=uid), mark_seen=False), None)

        if not mail:
            return f"Aucun e-mail trouvé pour l'UID {uid}."
        print(f"📧 Résumé de l'e-mail UID {uid} de {mail.from_}...")
        prompt = (
            f"De : {mail.from_}\nDate : {mail.date}\nSujet : {mail.subject}\n\n"
            f"{mail.text or mail.html}\n\n"
            "Résume cet e-mail de façon claire et concise."
        )
        return self.email_llm.invoke(prompt).content

    def view_sent_email(self, uid: str) -> str:
        """Affiche le contenu d'un email envoyé en utilisant son UID."""
        # Essayer différents dossiers d'emails envoyés
        for folder_name in ["Sent", "INBOX.Sent", "Sent Items", "Éléments envoyés", "[Gmail]/Sent Mail"]:
            try:
                with MailBox(self.host).login(self.user, self.password, folder_name) as mb:
                    mail = next(mb.fetch(AND(uid=uid), mark_seen=False), None)
                    if mail:
                        print(f"📤 Consultation de l'email envoyé UID {uid}...")
                        content = f"""
**📤 Email Envoyé**

**À :** {', '.join(mail.to) if mail.to else 'Destinataire inconnu'}
**Date :** {mail.date.strftime('%Y-%m-%d %H:%M')}
**Sujet :** {mail.subject}

**Contenu :**
{mail.text or mail.html or 'Contenu non disponible'}
"""
                        return content.strip()
            except:
                continue
        
        return f"❌ Aucun email envoyé trouvé pour l'UID {uid}."

    def mark_email_as_read(self, uid: str) -> str:
        """Marque un email comme lu en utilisant son UID."""
        with self.connect() as mb:
            # Récupérer l'email pour vérifier qu'il existe
            mail = next(mb.fetch(AND(uid=uid)), None)
            if not mail:
                return f"❌ Aucun e-mail trouvé pour l'UID {uid}."
            
            # Marquer comme lu en ajoutant le flag SEEN
            mb.flag(uid, ['\\Seen'], True)
            return f"✅ E-mail de {mail.from_} (sujet: {mail.subject}) marqué comme lu."
        

    def compose_email(self, recipient: str, subject_hint: str, content_request: str) -> str:
        """Compose un email automatiquement selon les instructions données."""
        print(f"✍️ Rédaction d'un email pour {recipient} sur le sujet: {subject_hint}")
        
        prompt = f"""Tu es l'assistant IA de Quentin Dufour. Tu rédiges cet email AU NOM de Quentin Dufour.

**Instructions importantes :**
- Tu écris à la première personne comme si c'était Quentin qui écrivait
- Tu n'es PAS Quentin, tu écris POUR lui
- Signe toujours "Quentin Dufour" (et pas son alias) mais ne te présente jamais comme étant Quentin
- Si tu as des questions ou des infos supplémentaires, demande à Quentin avant de finaliser l'email
- Attends TOUJOURS que Quentin valide avant d'envoyer l'email

**Destinataire :** {recipient}
**Sujet souhaité :** {subject_hint}
**Contenu demandé :** {content_request}

Rédige un email complet avec :
1. Un objet précis, engageant et professionnel
2. Une formule de politesse d'ouverture personnalisée
3. Le contenu principal bien structuré avec des paragraphes clairs
4. Une formule de politesse de fermeture appropriée
5. Signature "Quentin Dufour"

Structure le contenu avec des paragraphes séparés par des doubles sauts de ligne.
Utilise un ton professionnel mais chaleureux.

Réponds UNIQUEMENT au format JSON suivant :
{{
    "subject": "Objet de l'email précis et engageant",
    "body": "Corps de l'email avec formules de politesse\\n\\nParagraphe 1\\n\\nParagraphe 2\\n\\nFormule de fermeture\\n\\nQuentin Dufour"
}}"""

        response = self.email_llm.invoke(prompt).content
        
        try:
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            
            return response.strip()
        except Exception as e:
            return json.dumps({
                "subject": f"À propos de : {subject_hint}",
                "body": f"Bonjour,\\n\\nJ'espère que vous allez bien.\\n\\n{content_request}\\n\\nN'hésitez pas à me recontacter si vous avez des questions.\\n\\nCordialement,\\nQuentin Dufour"
            }, ensure_ascii=False)

    def send_email(self, recipient: str, subject: str, body: str) -> str:
        """Envoie un email HTML bien structuré après validation."""
        try:
            # Configuration SMTP
            smtp_host = MAIL_SETTINGS["smtp_host"]
            smtp_port = MAIL_SETTINGS["smtp_port"]
            
            print(f"🔄 Tentative d'envoi vers {recipient}...")
            print(f"📡 Serveur SMTP: {smtp_host}:{smtp_port}")
            html_body = self._convert_to_html(body)
            msg = MIMEMultipart('alternative')
            msg['From'] = self.user
            msg['To'] = recipient
            msg['Subject'] = subject
            
            text_part = MIMEText(body, 'plain', 'utf-8')
            html_part = MIMEText(html_body, 'html', 'utf-8')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.set_debuglevel(0)  # Mettre à 1 pour voir les détails
                server.starttls()
                server.login(self.user, self.password)
                result = server.send_message(msg)
            
            print("L'email s'envoie...")
            time.sleep(2)
            
            verification_result = self._verify_email_sent(subject, recipient)
            
            return f"✅ Email envoyé avec succès à {recipient}\n{verification_result}"
            
        except smtplib.SMTPAuthenticationError as e:
            return f"❌ Erreur d'authentification SMTP: {str(e)}\n💡 Vérifiez votre mot de passe d'application Gmail"
        except smtplib.SMTPRecipientsRefused as e:
            return f"❌ Destinataire refusé: {str(e)}\n💡 Vérifiez l'adresse email du destinataire"
        except smtplib.SMTPServerDisconnected as e:
            return f"❌ Connexion serveur fermée: {str(e)}\n💡 Vérifiez vos paramètres SMTP"
        except Exception as e:
            return f"❌ Erreur lors de l'envoi: {str(e)}\n💡 Type d'erreur: {type(e).__name__}"

    def _verify_email_sent(self, subject: str, recipient: str) -> str:
        """Vérifie si l'email envoyé apparaît dans le dossier des envoyés."""
        try:
            for folder_name in ["[Gmail]/Sent Mail", "Sent", "INBOX.Sent", "Sent Items"]:
                try:
                    with MailBox(self.host).login(self.user, self.password, folder_name) as mb:
                        recent_emails = list(islice(mb.fetch(headers_only=True, reverse=True), 5))
                        for mail in recent_emails:
                            if mail.subject == subject and recipient in str(mail.to):
                                return f"✅ Email confirmé dans le dossier '{folder_name}'"
                except:
                    continue
            
            return "⚠️ Email envoyé mais non trouvé dans les dossiers d'envoi (peut prendre quelques minutes)"
        except Exception as e:
            return f"⚠️ Impossible de vérifier l'envoi: {str(e)}"

    def test_smtp_connection(self) -> str:
        """Teste la connexion SMTP pour diagnostiquer les problèmes d'envoi."""
        try:
            smtp_host = MAIL_SETTINGS["smtp_host"]
            smtp_port = MAIL_SETTINGS["smtp_port"]
            
            print(f"🔍 Test de connexion SMTP...")
            print(f"📡 Serveur: {smtp_host}:{smtp_port}")
            print(f"👤 Utilisateur: {self.user}")
            
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.set_debuglevel(1)  # Mode debug activé
                server.starttls()
                server.login(self.user, self.password)
                return "✅ Connexion SMTP fonctionnelle - Prêt à envoyer des emails"
                
        except smtplib.SMTPAuthenticationError as e:
            return f"❌ Erreur d'authentification: {str(e)}\n💡 Solution: Utilisez un mot de passe d'application Gmail"
        except smtplib.SMTPConnectError as e:
            return f"❌ Impossible de se connecter au serveur: {str(e)}\n💡 Vérifiez l'adresse du serveur SMTP"
        except Exception as e:
            return f"❌ Erreur de connexion: {str(e)}\n💡 Type: {type(e).__name__}"

    def _convert_to_html(self, text_body: str) -> str:
        """Convertit un email texte en HTML bien structuré et joli."""
        # Échapper les caractères HTML
        import html
        escaped_body = html.escape(text_body)
        
        # Remplacer les sauts de ligne par des paragraphes HTML
        paragraphs = escaped_body.split('\n\n')
        html_paragraphs = [f'<p style="margin: 10px 0; line-height: 1.6;">{p.replace(chr(10), "<br>")}</p>' for p in paragraphs if p.strip()]
        
        html_template = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Email</title>
</head>
<body style="margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f4f4;">
    <div style="max-width: 600px; margin: 20px auto; background-color: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); overflow: hidden;">
        <!-- Header -->
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; text-align: center;">
            <h1 style="color: white; margin: 0; font-size: 24px; font-weight: 300;">📧</h1>
        </div>
        
        <!-- Content -->
        <div style="padding: 30px;">
            {''.join(html_paragraphs)}
        </div>
        
        <!-- Footer -->
        <div style="background-color: #f8f9fa; padding: 20px; text-align: center; border-top: 1px solid #e9ecef;">
            <p style="margin: 0; color: #6c757d; font-size: 12px;">
                Envoyé avec ❤️ par AI Email Agent de @kaiiine
            </p>
        </div>
    </div>
</body>
</html>
        """
        
        return html_template.strip()
