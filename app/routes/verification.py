import logging
from datetime import datetime, timezone
from functools import wraps
from uuid import UUID

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import select

from app.extensions import db
from app.models import AppUser, CustomerDetails, IdentityVerification
from app.services import (
    is_access_blocked,
    VERIFICATION_PENDING,
    VERIFICATION_REJECTED,
    VERIFICATION_VERIFIED,
    is_admin,
    is_verification_officer,
    notify,
    write_audit,
)

verification = Blueprint("verification", __name__, url_prefix="/verification")
logger = logging.getLogger(__name__)


def officer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("customer_id")
        if not user_id:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        try:
            user = db.session.get(AppUser, UUID(str(user_id)))
        except (ValueError, TypeError, AttributeError):
            user = None
        if is_access_blocked(user):
            session.clear()
            flash("Your account is unavailable. Please log in again.", "error")
            return redirect(url_for("auth.login"))
        # Verification officers and administrators may review requests.
        if not (is_verification_officer(user) or is_admin(user)):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@verification.route("/")
@officer_required
def dashboard():
    show = request.args.get("show", "pending")
    query = IdentityVerification.query
    if show == "reviewed":
        query = query.filter(
            IdentityVerification.verification_status != VERIFICATION_PENDING
        ).order_by(IdentityVerification.reviewed_at.desc())
    else:
        show = "pending"
        query = query.filter_by(
            verification_status=VERIFICATION_PENDING
        ).order_by(IdentityVerification.submitted_at.asc())

    items = query.limit(250).all()
    user_ids = {i.customer_id for i in items} | {
        i.reviewed_by for i in items if i.reviewed_by
    }
    users = AppUser.query.filter(AppUser.user_id.in_(user_ids)).all() if user_ids else []
    details = (
        CustomerDetails.query.filter(CustomerDetails.customer_id.in_(user_ids)).all()
        if user_ids else []
    )
    pending_count = IdentityVerification.query.filter_by(
        verification_status=VERIFICATION_PENDING
    ).count()

    viewer = db.session.get(AppUser, UUID(str(session.get("customer_id"))))
    return render_template(
        "verification.html",
        viewer_is_admin=is_admin(viewer),
        show=show,
        items=items,
        pending_count=pending_count,
        users_by_id={str(u.user_id): u for u in users},
        details_by_id={str(d.customer_id): d for d in details},
    )


@verification.route("/<int:verification_id>/review", methods=["POST"])
@officer_required
def review(verification_id):
    decision = (request.form.get("decision") or "").strip().lower()
    remarks = (request.form.get("remarks") or "").strip()[:1000]

    if decision not in {"approve", "reject"}:
        flash("Choose approve or reject.", "error")
        return redirect(url_for("verification.dashboard"))
    if decision == "reject" and not remarks:
        flash("Enter a reason when rejecting a request.", "error")
        return redirect(url_for("verification.dashboard"))

    record = db.session.execute(
        select(IdentityVerification)
        .where(IdentityVerification.verification_id == verification_id)
        .with_for_update()
    ).scalar_one_or_none()

    if record is None:
        flash("Verification request was not found.", "error")
        return redirect(url_for("verification.dashboard"))
    if record.verification_status != VERIFICATION_PENDING:
        db.session.rollback()
        flash("This request has already been reviewed.", "error")
        return redirect(url_for("verification.dashboard"))

    officer_id = UUID(str(session.get("customer_id")))
    if record.customer_id == officer_id:
        db.session.rollback()
        abort(403)

    record.verification_status = (
        VERIFICATION_VERIFIED if decision == "approve" else VERIFICATION_REJECTED
    )
    record.review_remarks = remarks or None
    record.reviewed_by = officer_id
    record.reviewed_at = datetime.now(timezone.utc)

    if decision == "approve":
        notify(
            record.customer_id, "Identity verified",
            "Your identity has been verified. You can now request a bank "
            "account from the My Account page.",
        )
    else:
        notify(
            record.customer_id, "Verification declined",
            f"Your verification request was declined. Reason: {remarks} "
            "You may update your information and submit a new request.",
        )

    write_audit(
        f"verification_{record.verification_status}",
        "identity_verification", record.verification_id,
        f"Identity verification {record.verification_status}.",
        subject_id=record.customer_id,
    )

    try:
        db.session.commit()
        flash(f"Request {record.verification_status}.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Could not save the review.")
        flash("Could not save the review. Please try again.", "error")
    return redirect(url_for("verification.dashboard"))
