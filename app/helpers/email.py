import os
import resend
from app.core.config import settings

resend.api_key = settings.RESEND_API_KEY


async def send_email(
    to: str,
    subject: str,
    html: str,
):
    params: resend.Emails.SendParams = {
        # "from": "onboarding@resend.dev", # for testing
        "from":"growth@contentlynxe.com",
        "to": [to],
        "subject": subject,
        "html": html,
    }

    email = await resend.Emails.send_async(params)

    return email
