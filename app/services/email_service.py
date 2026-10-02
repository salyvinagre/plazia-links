from html import escape

from app.core.email import get_email_backend
from app.core.logging import get_logger
from app.schemas.internal import EmailSendResult

logger = get_logger(__name__)

_INVITE_EMAIL_HTML = (
    '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n<body '
    'style="font-family: Arial, sans-serif; max-width: 600px; margin: '
    '0 auto; padding: 20px;">\n  <h2 style="color: #333;">You\'ve been '
    "invited to {workspace_name}</h2>\n  <p>{invited_by_name} has "
    "invited you to join <strong>{workspace_name}</strong> on "
    "Zly.</p>\n  <p>Click the button below to accept your "
    'invitation:</p>\n  <div style="text-align: center; margin: 30px '
    '0;">\n    <a href="{invite_url}" style="background-color: '
    "#007bff; color: white; padding: 12px 24px; text-decoration: "
    'none; border-radius: 5px; display: inline-block;">Accept '
    'Invitation</a>\n  </div>\n  <p style="color: #666; font-size: '
    '14px;">This invitation expires in 7 days ({expires_at}).</p>\n  '
    '<hr style="border: none; border-top: 1px solid #eee; margin: '
    '20px 0;">\n  <p style="color: #999; font-size: 12px;">If you '
    "didn't expect this email, you can safely ignore "
    "it.</p>\n</body>\n</html>"
)

_PASSWORD_RESET_EMAIL_HTML = (
    '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n<body '
    'style="font-family: Arial, sans-serif; max-width: 600px; margin: '
    '0 auto; padding: 20px;">\n  <h2 style="color: #333;">Reset your '
    "password</h2>\n  <p>We received a request to reset your password "
    "for your Zly account.</p>\n  <p>Click the button below to set a "
    'new password:</p>\n  <div style="text-align: center; margin: 30px '
    '0;">\n    <a href="{reset_url}" style="background-color: #dc3545; '
    "color: white; padding: 12px 24px; text-decoration: none; "
    'border-radius: 5px; display: inline-block;">Reset Password</a>\n  '
    '</div>\n  <p style="color: #666; font-size: 14px;">This link '
    'expires in 1 hour ({expires_at}).</p>\n  <hr style="border: none; '
    'border-top: 1px solid #eee; margin: 20px 0;">\n  <p style="color: '
    "#999; font-size: 12px;\">If you didn't request a password reset, "
    "you can safely ignore this email. Your password won't change "
    "until you create a new one.</p>\n</body>\n</html>"
)

_EXPIRY_ALERT_EMAIL_HTML = (
    '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"></head>\n<body '
    'style="font-family: Arial, sans-serif; max-width: 600px; margin: '
    '0 auto; padding: 20px;">\n  <h2 style="color: #333;">Link '
    "expiring soon: {link_title}</h2>\n  <p>Your short link "
    "<strong>{short_code}</strong> is set to expire in "
    "<strong>{hours_remaining} hours</strong>.</p>\n  <table "
    'style="border-collapse: collapse; width: 100%; margin: 20px '
    '0;">\n    <tr><td style="padding: 8px; border: 1px solid '
    '#eee;"><strong>Short URL</strong></td><td style="padding: 8px; '
    'border: 1px solid #eee;"><a '
    'href="{short_url}">{short_url}</a></td></tr>\n    <tr><td '
    'style="padding: 8px; border: 1px solid '
    '#eee;"><strong>Destination</strong></td><td style="padding: 8px; '
    'border: 1px solid #eee;"><a '
    'href="{destination_url}">{destination_url}</a></td></tr>\n    '
    '<tr><td style="padding: 8px; border: 1px solid '
    '#eee;"><strong>Expires at</strong></td><td style="padding: 8px; '
    'border: 1px solid #eee;">{expires_at}</td></tr>\n    <tr><td '
    'style="padding: 8px; border: 1px solid #eee;"><strong>Total '
    'clicks</strong></td><td style="padding: 8px; border: 1px solid '
    '#eee;">{total_clicks}</td></tr>\n  </table>\n  <p>If you want to '
    "keep this link active, please update or remove the expiration "
    'date in your Zly dashboard.</p>\n  <hr style="border: none; '
    'border-top: 1px solid #eee; margin: 20px 0;">\n  <p style="color: '
    '#999; font-size: 12px;">This is an automated alert from '
    "Zly.</p>\n</body>\n</html>"
)


async def send_invite_email(
    invite_id: str,
    to_email: str,
    workspace_name: str,
    invited_by_name: str,
    invite_url: str,
    expires_at: str,
) -> EmailSendResult:
    backend = get_email_backend()
    html = _INVITE_EMAIL_HTML.format(
        workspace_name=escape(workspace_name),
        invited_by_name=escape(invited_by_name),
        invite_url=escape(invite_url, quote=True),
        expires_at=escape(expires_at),
    )
    logger.info("Sending invite email", extra={"invite_id": invite_id, "to": to_email})
    return await backend.send_email(
        to=to_email,
        subject=f"You've been invited to {workspace_name}",
        html_body=html,
    )


async def send_password_reset_email(
    user_id: str,
    to_email: str,
    reset_url: str,
    expires_at: str,
) -> EmailSendResult:
    backend = get_email_backend()
    html = _PASSWORD_RESET_EMAIL_HTML.format(
        reset_url=escape(reset_url, quote=True),
        expires_at=escape(expires_at),
    )
    logger.info("Sending password reset email", extra={"user_id": user_id, "to": to_email})
    return await backend.send_email(
        to=to_email,
        subject="Reset your Zly password",
        html_body=html,
    )


async def send_expiry_alert_email(
    link_id: str,
    to_email: str,
    link_title: str,
    short_code: str,
    short_url: str,
    destination_url: str,
    expires_at: str,
    hours_remaining: int,
    total_clicks: int,
) -> EmailSendResult:
    backend = get_email_backend()
    html = _EXPIRY_ALERT_EMAIL_HTML.format(
        link_title=escape(link_title),
        short_code=escape(short_code),
        short_url=escape(short_url, quote=True),
        destination_url=escape(destination_url, quote=True),
        expires_at=escape(expires_at),
        hours_remaining=hours_remaining,
        total_clicks=total_clicks,
    )
    logger.info("Sending expiry alert email", extra={"link_id": link_id, "to": to_email})
    return await backend.send_email(
        to=to_email,
        subject=f"Link expiring soon: {link_title}",
        html_body=html,
    )
