import requests
import os
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")

FROM_EMAIL = "WhatNext <hello@send.whatnexttv.org>"

print("FROM EMAIL:", FROM_EMAIL)

def send_email(to_email: str, subject: str, html: str):
    try:
        if not RESEND_API_KEY:
            print("❌ RESEND_API_KEY missing")
            return

        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
            timeout=20,
        )

        print("📨 Resend response:", response.status_code, response.text)

        if response.status_code not in (200, 201, 202):
            print("❌ Email failed")
        else:
            print("✅ Email sent successfully")

    except Exception as e:
        print("❌ Email error:", repr(e))

def welcome_email_html(first_name: str = "there"):
    name = first_name if first_name and first_name != "None" else "there"

    return f"""
    <div style="font-family: Arial, sans-serif; background:#f8fafc; padding:30px;">
      <div style="max-width:600px; margin:0 auto; background:#ffffff; border-radius:12px; padding:30px;">

        <h2 style="margin-bottom:10px;">Welcome to WhatNext 🎬</h2>

        <p style="font-size:16px;">Hi {name},</p>

        <p style="font-size:16px;">
          Ever spend 20 minutes scrolling and still not pick anything to watch?
        </p>

        <p style="font-size:16px;">
          <strong>That’s exactly why we built WhatNext.</strong>
        </p>

        <p style="font-size:16px;">
          Instead of endless browsing, WhatNext helps you:
        </p>

        <ul style="font-size:15px; line-height:1.6;">
          <li>🎯 Find shows you’ll actually enjoy</li>
          <li>⭐ Track what you’ve watched</li>
          <li>🚀 Get smarter recommendations over time</li>
        </ul>

        <div style="text-align:center; margin:30px 0;">
          <a href="https://whatnexttv.org"
             style="background:#6366f1;color:#fff;padding:14px 22px;
                    text-decoration:none;border-radius:8px;
                    font-weight:bold; display:inline-block;">
            Get your recommendations
          </a>
        </div>

        <div style="background:#f1f5f9; padding:15px; border-radius:8px;">
          <p style="margin:0; font-size:14px;">
            💡 <strong>Quick tip:</strong> Add just 3 shows you like to unlock your first recommendations.
          </p>
        </div>

        <p style="margin-top:25px; font-size:14px; color:#475569;">
          This is still early, so things will improve quickly.  
          If something feels off — just reply to this email.
        </p>

        <p style="margin-top:20px;">
          Leon<br/>
          <span style="color:#64748b;">Founder, WhatNext</span>
        </p>

      </div>
    </div>
    """