import base64
import resend

from app.core.config import settings

resend.api_key = settings.RESEND_API_KEY


async def send_email(
    to: str,
    subject: str,
    html: str,
    pdf_bytes: bytes | None = None,
):
    params: resend.Emails.SendParams = {
        "from": "growth@contentlynxe.com",
        "to": [to],
        "subject": subject,
        "html": html,
    }

    if pdf_bytes:
        params["attachments"] = [
            {
                "filename": "ai-visibility-report.pdf",
                "content": base64.b64encode(pdf_bytes).decode("utf-8"),
            }
        ]

    email = await resend.Emails.send_async(params)

    return email

