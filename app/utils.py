
from flask import request

from app.extensions import db
from app.models import LoginHistory


def record_login_attempt(
    username,
    status,
    customer_id=None
):
    """
    Record a successful or failed login attempt.
    """

    forwarded_ip = request.headers.get(
        "X-Forwarded-For"
    )

    # Only trust forwarded IP headers when set by
    # a proxy that you control.
    ip_address = (
        forwarded_ip.split(",")[0].strip()
        if forwarded_ip
        else request.remote_addr
    )

    user_agent = request.headers.get(
        "User-Agent",
        "Unknown"
    )

    history = LoginHistory(
        customer_id=customer_id,
        username_attempted=username[:50],
        ip_address=ip_address,
        device_info=user_agent[:1000],
        login_status=status,
    )

    db.session.add(history)
    db.session.commit()
