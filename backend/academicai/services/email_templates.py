"""The text of the transactional emails.

Content only. Nothing here decides whether or when to send - that is
email_service (the seam) and the callers. Keeping the wording in one module
means the verification email reads the same however it was triggered.

WHY BOTH TEXT AND HTML
----------------------
Every message is sent as both. The text part is not a fallback nobody reads: a
mail client that blocks remote content, a screen reader, a terminal client and
a spam filter all look at it, and a code the reader cannot reach is the same as
no code at all.

The HTML is deliberately plain - a table, system fonts, inline styles, no
images and no external CSS. Mail clients strip <style> blocks, and an image
that must load to show the code will not load for most people on first open.
"""

BRAND = "AcademicAI"


def verification_code_email(code, ttl_minutes):
    """The code a new account needs to verify its address.

    Returns (subject, text, html). The subject carries the code as well: some
    clients preview it, which saves opening the message at all.
    """
    subject = f"{code} is your {BRAND} verification code"

    text = f"""{BRAND}

Verify your email

Your verification code is:

    {code}

This code expires in {ttl_minutes} minutes.

If you did not create an {BRAND} account, you can ignore this email.
Do not share this code with anyone.
"""

    # Letter-spaced, large, and selectable as one run of text so it can be
    # copied in one gesture on a phone.
    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width" />
<title>Verify your email</title></head>
<body style="margin:0;padding:24px;background:#f1f3f2;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0"
         style="width:100%;max-width:520px;margin:0 auto;background:#ffffff;
                border:1px solid #d9dedc;border-radius:12px;">
    <tr><td style="padding:32px 32px 0 32px;">
      <p style="margin:0;font:600 18px -apple-system,BlinkMacSystemFont,'Segoe UI',
                Roboto,Helvetica,Arial,sans-serif;color:#0b5c4a;">{BRAND}</p>
    </td></tr>
    <tr><td style="padding:24px 32px 0 32px;">
      <h1 style="margin:0;font:600 24px -apple-system,BlinkMacSystemFont,'Segoe UI',
                 Roboto,Helvetica,Arial,sans-serif;color:#141a22;">Verify your email</h1>
      <p style="margin:12px 0 0 0;font:400 15px/1.6 -apple-system,BlinkMacSystemFont,
                'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#48555f;">
        Your verification code is:
      </p>
    </td></tr>
    <tr><td style="padding:20px 32px 0 32px;">
      <div style="background:#f1f6f4;border:1px solid #d9dedc;border-radius:10px;
                  padding:18px;text-align:center;font:600 32px/1.2 ui-monospace,
                  SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.22em;
                  color:#0b5c4a;">{code}</div>
    </td></tr>
    <tr><td style="padding:20px 32px 0 32px;">
      <p style="margin:0;font:400 14px/1.6 -apple-system,BlinkMacSystemFont,
                'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#48555f;">
        This code expires in {ttl_minutes} minutes.
      </p>
    </td></tr>
    <tr><td style="padding:24px 32px 32px 32px;">
      <hr style="border:none;border-top:1px solid #e6eae8;margin:0 0 16px 0;" />
      <p style="margin:0;font:400 13px/1.6 -apple-system,BlinkMacSystemFont,
                'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#6b7780;">
        If you did not create an {BRAND} account, you can ignore this email.
        Do not share this code with anyone.
      </p>
    </td></tr>
  </table>
</body>
</html>"""

    return subject, text, html
