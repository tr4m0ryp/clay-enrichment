import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from src.utils import log_error


def send_email(sender, recipient, subject, body, smtp_config):
    """
    Sends an email via SMTP. Constructs a plain-text email with the given
    sender, recipient, subject, and body, then delivers it through the
    configured SMTP server.

    Parameters:
        sender: The sender email address.
        recipient: The recipient email address.
        subject: The email subject line.
        body: The email body text (plain text).
        smtp_config: A dict with SMTP connection settings:
            - "host": SMTP server hostname
            - "port": SMTP server port (typically 587 for TLS)
            - "password": SMTP authentication password

    Returns:
        True if the email was sent successfully, False otherwise.
    """
    try:
        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        host = smtp_config.get("host", "")
        port = int(smtp_config.get("port", 587))
        password = smtp_config.get("password", "")

        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)

        return True
    except smtplib.SMTPAuthenticationError as e:
        log_error(f"SMTP authentication failed for {sender}: {e}")
        return False
    except smtplib.SMTPRecipientsRefused as e:
        log_error(f"Recipient refused ({recipient}): {e}")
        return False
    except smtplib.SMTPException as e:
        log_error(f"SMTP error sending to {recipient}: {e}")
        return False
    except Exception as e:
        log_error(f"Unexpected error sending email to {recipient}: {e}")
        return False
