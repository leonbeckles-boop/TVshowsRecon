import os
import requests
from dotenv import load_dotenv

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
FROM_EMAIL = "WhatNext <hello@send.whatnexttv.org>"


def send_email(to_email: str, subject: str, html: str) -> dict:
    try:
        if not RESEND_API_KEY:
            return {
                "ok": False,
                "status_code": None,
                "message_id": None,
                "response_text": "RESEND_API_KEY missing",
            }

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

        message_id = None
        try:
            payload = response.json()
            message_id = payload.get("id")
        except Exception:
            payload = None

        ok = response.status_code in (200, 201, 202)

        return {
            "ok": ok,
            "status_code": response.status_code,
            "message_id": message_id,
            "response_text": response.text,
        }

    except Exception as e:
        return {
            "ok": False,
            "status_code": None,
            "message_id": None,
            "response_text": repr(e),
        }


def _safe_name(first_name: str | None) -> str:
    if not first_name or str(first_name).strip().lower() == "none":
        return "there"
    return str(first_name).strip()


def _email_shell(title: str, preheader: str, body_html: str) -> str:
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{title}</title>
      </head>
      <body style="margin:0; padding:0; background:#f3f6fb; font-family:Arial, Helvetica, sans-serif; color:#0f172a;">
        <div style="display:none; max-height:0; overflow:hidden; opacity:0; mso-hide:all;">
          {preheader}
        </div>

        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3f6fb; margin:0; padding:24px 0;">
          <tr>
            <td align="center">
              <table role="presentation" width="640" cellspacing="0" cellpadding="0" border="0" style="width:640px; max-width:640px; background:#ffffff; border-radius:18px; overflow:hidden; box-shadow:0 8px 30px rgba(15,23,42,0.08);">
                <tr>
                    <td style="background:linear-gradient(135deg, #020617 0%, #0f172a 55%, #1d4ed8 100%); padding:24px 28px;">
                        
                        <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                        <tr>
                            
                            <!-- LOGO -->
                            <td style="vertical-align:middle; width:60px;">
                            <img 
                                src="https://whatnexttv.org/logo1.png" 
                                alt="WhatNext"
                                style="height:44px; display:block;"
                            />
                            </td>

                            <!-- TEXT -->
                            <td style="vertical-align:middle; padding-left:12px;">
                            <div style="font-size:22px; font-weight:700; color:#ffffff; line-height:1.2;">
                                WhatNext
                            </div>
                            <div style="font-size:13px; color:#cbd5e1; margin-top:2px;">
                                Personalised TV recommendations
                            </div>
                            </td>

                        </tr>
                        </table>

                    </td>
                    </tr>

                <tr>
                  <td style="padding:36px 32px 14px 32px;">
                    {body_html}
                  </td>
                </tr>

                <tr>
                  <td style="padding:8px 32px 32px 32px;">
                    <div style="margin-top:18px; padding-top:18px; border-top:1px solid #e2e8f0; font-size:13px; color:#64748b; line-height:1.6;">
                      You’re receiving this because you signed up for WhatNext.<br/>
                      <a href="https://whatnexttv.org" style="color:#4f46e5; text-decoration:none;">whatnexttv.org</a>
                    </div>
                  </td>
                </tr>

              </table>
            </td>
          </tr>
        </table>
      </body>
    </html>
    """


def welcome_email_html(first_name: str | None = None) -> str:
    name = _safe_name(first_name)

    body = f"""
      <h1 style="margin:0 0 14px 0; font-size:30px; line-height:1.2; color:#0f172a;">
        Welcome to WhatNext
      </h1>

      <p style="margin:0 0 18px 0; font-size:17px; line-height:1.7; color:#334155;">
        Hi {name},
      </p>

      <p style="margin:0 0 16px 0; font-size:17px; line-height:1.7; color:#334155;">
        Ever spend 20 minutes scrolling and still not pick anything?
      </p>

      <p style="margin:0 0 18px 0; font-size:17px; line-height:1.7; color:#0f172a; font-weight:700;">
        That’s exactly why I built WhatNext.
      </p>

      <p style="margin:0 0 16px 0; font-size:16px; line-height:1.7; color:#334155;">
        WhatNext helps you:
      </p>

      <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:0 0 24px 0;">
        <tr>
          <td style="padding:0 0 10px 0; font-size:16px; color:#0f172a;">🎯 Find shows you’ll actually enjoy</td>
        </tr>
        <tr>
          <td style="padding:0 0 10px 0; font-size:16px; color:#0f172a;">⭐ Track what you’ve watched</td>
        </tr>
        <tr>
          <td style="padding:0 0 10px 0; font-size:16px; color:#0f172a;">🚀 Get better recommendations over time</td>
        </tr>
      </table>

      <div style="text-align:center; margin:28px 0;">
        <a href="https://whatnexttv.org"
           style="display:inline-block; background:linear-gradient(135deg, #2563eb 0%, #6366f1 100%); color:#ffffff; text-decoration:none; padding:15px 24px; border-radius:12px; font-size:16px; font-weight:700;">
          Get your recommendations
        </a>
      </div>

      <div style="margin:0 0 22px 0; background:#eef2ff; border:1px solid #c7d2fe; border-radius:12px; padding:16px;">
        <div style="font-size:15px; line-height:1.7; color:#312e81;">
          <strong>Quick tip:</strong> Add 3 shows you like to unlock your first recommendations.
        </div>
      </div>

      <p style="margin:0 0 18px 0; font-size:15px; line-height:1.7; color:#475569;">
        This is still early, so things will improve quickly. If something feels off, just reply to this email.
      </p>

      <p style="margin:0; font-size:15px; line-height:1.7; color:#0f172a;">
        Leon<br/>
        <span style="color:#64748b;">Founder, WhatNext</span>
      </p>
    """

    return _email_shell(
        "Welcome to WhatNext",
        "Welcome to WhatNext — get personalised TV recommendations faster.",
        body,
    )


def day2_email_html(first_name: str | None = None) -> str:
    name = _safe_name(first_name)

    body = f"""
      <h1 style="margin:0 0 14px 0; font-size:28px; line-height:1.2; color:#0f172a;">
        Your recommendations are waiting 👀
      </h1>

      <p style="margin:0 0 18px 0; font-size:17px; line-height:1.7; color:#334155;">
        Hi {name},
      </p>

      <p style="margin:0 0 16px 0; font-size:16px; line-height:1.7; color:#334155;">
        WhatNext works best once you add a few shows you already like.
      </p>

      <p style="margin:0 0 20px 0; font-size:16px; line-height:1.7; color:#334155;">
        Add just <strong>3 favourites</strong> and the app starts shaping recommendations around your taste.
      </p>

      <div style="margin:0 0 22px 0; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:16px;">
        <div style="font-size:15px; line-height:1.7; color:#334155;">
          Try adding shows like:
          <strong>Breaking Bad</strong>, <strong>Dark</strong>, <strong>The Bear</strong>, <strong>Silo</strong>
        </div>
      </div>

      <div style="text-align:center; margin:28px 0;">
        <a href="https://whatnexttv.org"
           style="display:inline-block; background:linear-gradient(135deg, #2563eb 0%, #6366f1 100%); color:#ffffff; text-decoration:none; padding:15px 24px; border-radius:12px; font-size:16px; font-weight:700;">
          Add your favourites
        </a>
      </div>

      <p style="margin:0; font-size:15px; line-height:1.7; color:#0f172a;">
        Leon<br/>
        <span style="color:#64748b;">Founder, WhatNext</span>
      </p>
    """

    return _email_shell(
        "Your recommendations are waiting",
        "Add a few favourites and let WhatNext start learning your taste.",
        body,
    )


def day5_email_html(first_name: str | None = None) -> str:
    name = _safe_name(first_name)

    body = f"""
      <h1 style="margin:0 0 14px 0; font-size:28px; line-height:1.2; color:#0f172a;">
        Stop scrolling. Start watching better shows 🎯
      </h1>

      <p style="margin:0 0 18px 0; font-size:17px; line-height:1.7; color:#334155;">
        Hi {name},
      </p>

      <p style="margin:0 0 16px 0; font-size:16px; line-height:1.7; color:#334155;">
        Instead of endless browsing, WhatNext is built to help you find your next show faster.
      </p>

      <p style="margin:0 0 16px 0; font-size:16px; line-height:1.7; color:#334155;">
        The more you favourite, rate, and hide shows, the smarter your recommendations get.
      </p>

      <div style="margin:0 0 22px 0; background:#eff6ff; border:1px solid #bfdbfe; border-radius:12px; padding:16px;">
        <div style="font-size:15px; line-height:1.7; color:#1e3a8a;">
          <strong>Best result:</strong> add a few favourites, rate what you’ve seen, and mark anything you’re not interested in.
        </div>
      </div>

      <div style="text-align:center; margin:28px 0;">
        <a href="https://whatnexttv.org"
           style="display:inline-block; background:linear-gradient(135deg, #2563eb 0%, #6366f1 100%); color:#ffffff; text-decoration:none; padding:15px 24px; border-radius:12px; font-size:16px; font-weight:700;">
          Jump back in
        </a>
      </div>

      <p style="margin:0; font-size:15px; line-height:1.7; color:#0f172a;">
        Leon<br/>
        <span style="color:#64748b;">Founder, WhatNext</span>
      </p>
    """

    return _email_shell(
        "Stop scrolling. Start watching better shows",
        "WhatNext helps you find better TV recommendations faster.",
        body,
    )


def day7_feedback_email_html(first_name: str | None = None) -> str:
    name = _safe_name(first_name)

    body = f"""
      <h1 style="margin:0 0 14px 0; font-size:28px; line-height:1.2; color:#0f172a;">
        Quick favour? 🙏
      </h1>

      <p style="margin:0 0 18px 0; font-size:17px; line-height:1.7; color:#334155;">
        Hi {name},
      </p>

      <p style="margin:0 0 16px 0; font-size:16px; line-height:1.7; color:#334155;">
        You’re one of the early WhatNext users, so your feedback genuinely helps shape what gets built next.
      </p>

      <div style="margin:0 0 20px 0; background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:16px;">
        <div style="font-size:15px; line-height:1.8; color:#334155;">
          Just reply and tell me:
          <br/>1. Have you found a show through the app yet?
          <br/>2. What feels missing or not quite right?
        </div>
      </div>

      <p style="margin:0 0 22px 0; font-size:16px; line-height:1.7; color:#334155;">
        Even one line helps.
      </p>

      <div style="text-align:center; margin:28px 0;">
        <a href="mailto:hello@whatnexttv.org"
           style="display:inline-block; background:linear-gradient(135deg, #2563eb 0%, #6366f1 100%); color:#ffffff; text-decoration:none; padding:15px 24px; border-radius:12px; font-size:16px; font-weight:700;">
          Reply with feedback
        </a>
      </div>

      <p style="margin:0; font-size:15px; line-height:1.7; color:#0f172a;">
        Leon<br/>
        <span style="color:#64748b;">Founder, WhatNext</span>
      </p>
    """

    return _email_shell(
        "Quick favour?",
        "Your feedback will help shape WhatNext.",
        body,
    )