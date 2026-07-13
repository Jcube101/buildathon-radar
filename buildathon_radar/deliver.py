import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown
from dotenv import load_dotenv

load_dotenv()

ARCHIVE_DIR = "archive"
ACCENT_COLOR = "#1a56db"


def get_date_range():
    """Date-range subtitle spanning the last 6 days."""
    end = datetime.now()
    start = end - timedelta(days=6)
    if start.strftime("%b %Y") == end.strftime("%b %Y"):
        return f"{start.strftime('%b %d')} - {end.strftime('%d, %Y')}"
    elif start.year == end.year:
        return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
    return f"{start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}"


def markdown_to_html(text, date_range=None):
    html_body = markdown.markdown(text, extensions=["extra", "nl2br"])
    subtitle = (
        f'<p style="color:#666;font-size:14px;margin-top:-6px;">{date_range}</p>'
        if date_range
        else ""
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 24px; color: #1a1a1a; line-height: 1.6;">
  <h1 style="color: {ACCENT_COLOR}; border-bottom: 3px solid {ACCENT_COLOR}; padding-bottom: 8px;">Buildathon Radar</h1>
  {subtitle}
  <div>{html_body}</div>
  <hr style="margin-top: 32px; border: none; border-top: 1px solid #ddd;">
  <p style="color: #999; font-size: 12px;">Buildathon Radar scans Devpost and Devfolio weekly and emails you every Sunday.</p>
</body>
</html>"""


def save_to_archive(digest_text):
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    week_label = datetime.now().strftime("%Y-%m-%d")
    filename = f"{ARCHIVE_DIR}/radar_{week_label}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# Buildathon Radar - Week of {week_label}\n\n")
        f.write(digest_text)
    return filename


def _count_picks(digest_text):
    return digest_text.count("\n### [")


def send_digest(digest_text):
    try:
        save_to_archive(digest_text)
    except Exception as e:
        print(f"  WARNING: Could not save to archive: {e}")

    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_ADDRESS")

    if not sender or not password:
        print(
            "  ERROR: EMAIL_ADDRESS or EMAIL_PASSWORD not set in .env, skipping email send."
        )
        return

    try:
        date_range = get_date_range()
        pick_count = _count_picks(digest_text)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = (
            f"🛰️ Buildathon Radar | {datetime.now().strftime('%b %d, %Y')} | "
            f"{pick_count} events"
        )
        msg["From"] = f"Buildathon Radar <{sender}>"
        msg["To"] = recipient

        text_part = MIMEText(digest_text, "plain")
        html_part = MIMEText(markdown_to_html(digest_text, date_range), "html")

        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print("Digest sent to your inbox.")
    except smtplib.SMTPAuthenticationError:
        print(
            "  ERROR: Gmail authentication failed. Check EMAIL_ADDRESS and EMAIL_PASSWORD in .env."
        )
    except smtplib.SMTPException as e:
        print(f"  ERROR: SMTP error, {e}")
    except Exception as e:
        print(f"  ERROR: Failed to send email, {e}")


def send_failure_email(error_text):
    """Sent by main.py's fatal handler on a non-dry crashing run, so silence
    always means the pipeline is broken, never masked by a swallowed error."""
    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_ADDRESS")

    if not sender or not password:
        print(
            "  ERROR: EMAIL_ADDRESS or EMAIL_PASSWORD not set in .env, cannot send failure email."
        )
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🛰️ Buildathon Radar | run failed"
        msg["From"] = f"Buildathon Radar <{sender}>"
        msg["To"] = recipient

        body = (
            "The weekly Buildathon Radar run failed with an error:\n\n"
            f"{error_text}\n\n"
            "Check journalctl --user -u buildathon-radar.service for details."
        )
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print("Failure notice sent to your inbox.")
    except Exception as e:
        print(f"  ERROR: Failed to send failure email, {e}")
