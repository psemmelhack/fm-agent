"""
tools/email.py
Send emails via Resend from morris@familymatter.co
"""

import os
import resend
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY")
FROM_ADDRESS = "Morris <morris@familymatter.co>"


def send_email(to: str, subject: str, html: str) -> str:
    """
    Send an email via Resend.
    
    Args:
        to:      recipient email address
        subject: email subject line
        html:    HTML email body
    """
    try:
        response = resend.Emails.send({
            "from": FROM_ADDRESS,
            "to": to,
            "subject": subject,
            "html": html
        })
        print(f"Email sent to {to}: {response['id']}")
        return f"Email sent successfully to {to}."
    except Exception as e:
        print(f"Email error: {e}")
        return f"Failed to send email to {to}: {str(e)}"


def send_invitation_email(
    to: str,
    family_member_name: str,
    deceased_name: str,
    executor_name: str,
    join_code: str
) -> str:
    """
    Send a Family Matter invitation email to a family member.
    """
    subject = f"You've been invited to join the {deceased_name} Family Matter"

    html = f"""
    <div style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto; 
                color: #2c2c2c; padding: 40px 20px;">
        
        <p style="font-size: 18px; color: #555; margin-bottom: 30px;">
            Dear {family_member_name},
        </p>

        <p style="font-size: 16px; line-height: 1.7;">
            My name is Morris. {executor_name} has asked me to help coordinate 
            the distribution of {deceased_name}'s belongings, and they've invited 
            you to be part of this process.
        </p>

        <p style="font-size: 16px; line-height: 1.7;">
            Family Matter is a calm, organized way to handle something that can 
            feel overwhelming. I'll guide everyone through it — what needs to happen, 
            when, and how to make sure things are handled fairly and with care.
        </p>

<p style="font-size: 16px; line-height: 1.7;">
    There's no rush right now. When you're ready, visit 
    <a href="https://app.familymatter.co" 
       style="color: #8b7355; text-decoration: none; border-bottom: 1px solid #C4A882;">
        app.familymatter.co
    </a> 
    and enter your personal join code below to get started. 
    It will take just a few minutes.
</p>    

        <div style="background: #f5f5f0; border-left: 3px solid #8b7355; 
                    padding: 20px 25px; margin: 30px 0; border-radius: 4px;">
            <p style="margin: 0; font-size: 14px; color: #888; 
                       text-transform: uppercase; letter-spacing: 1px;">
                Your join code
            </p>
            <p style="margin: 8px 0 0; font-size: 28px; font-weight: bold; 
                       letter-spacing: 4px; color: #2c2c2c;">
                {join_code}
            </p>
        </div>

        <p style="font-size: 16px; line-height: 1.7;">
            If you have any questions before joining, simply reply to this email. 
            I'm here.
        </p>

        <p style="font-size: 16px; margin-top: 40px; color: #555;">
            With care,<br>
            <strong>Morris</strong><br>
            <span style="font-size: 14px; color: #888;">
                Family Matter &mdash; familymatter.co
            </span>
        </p>

    </div>
    """

    return send_email(to, subject, html)


def send_reminder_email(
    to: str,
    family_member_name: str,
    deceased_name: str,
    join_code: str,
    days_since_invite: int
) -> str:
    """Send a gentle nudge to someone who hasn't joined yet."""
    subject = f"A gentle reminder — {deceased_name} Family Matter"

    html = f"""
    <div style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto;
                color: #2c2c2c; padding: 40px 20px;">

        <p style="font-size: 18px; color: #555; margin-bottom: 30px;">
            Dear {family_member_name},
        </p>

        <p style="font-size: 16px; line-height: 1.7;">
            Just a quiet note to let you know the invitation to join the 
            {deceased_name} Family Matter is still open. There's no pressure — 
            these things move at their own pace.
        </p>

        <p style="font-size: 16px; line-height: 1.7;">
            Your join code, in case you need it:
        </p>

        <div style="background: #f5f5f0; border-left: 3px solid #8b7355;
                    padding: 20px 25px; margin: 30px 0; border-radius: 4px;">
            <p style="margin: 0; font-size: 28px; font-weight: bold;
                       letter-spacing: 4px; color: #2c2c2c;">
                {join_code}
            </p>
        </div>

        <p style="font-size: 16px; line-height: 1.7;">
            Reply to this email anytime if you have questions or need anything.
        </p>

        <p style="font-size: 16px; margin-top: 40px; color: #555;">
            Morris<br>
            <span style="font-size: 14px; color: #888;">Family Matter</span>
        </p>

    </div>
    """

    return send_email(to, subject, html)


def send_group_announcement(
    recipients: list,
    subject: str,
    message: str,
    deceased_name: str
) -> str:
    """
    Send a group announcement to all family members.
    recipients: list of email addresses
    """
    html = f"""
    <div style="font-family: Georgia, serif; max-width: 600px; margin: 0 auto;
                color: #2c2c2c; padding: 40px 20px;">

        <p style="font-size: 14px; color: #888; text-transform: uppercase;
                   letter-spacing: 1px; margin-bottom: 20px;">
            {deceased_name} Family Matter — Update
        </p>

        <div style="font-size: 16px; line-height: 1.8;">
            {message}
        </div>

        <p style="font-size: 16px; margin-top: 40px; color: #555;">
            Morris<br>
            <span style="font-size: 14px; color: #888;">Family Matter</span>
        </p>

    </div>
    """

    results = []
    for email in recipients:
        result = send_email(email, subject, html)
        results.append(result)

    return f"Announcement sent to {len(recipients)} family members."
