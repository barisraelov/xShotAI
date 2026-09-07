"""
/contact endpoint — support / feedback form.

  POST /contact -> 200 MessageResult

Open to guests and signed-in users alike. There is no transactional-mail
infrastructure wired up right now, so the message is validated and logged;
the response is the same either way so the client can show a confirmation.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import get_current_user_optional
from models import User
from schemas import ContactMessage, MessageResult

logger = logging.getLogger(__name__)

router = APIRouter(tags=["contact"])

MESSAGE_MIN_LEN = 10


@router.post("/contact", response_model=MessageResult)
def submit_contact(
    payload: ContactMessage,
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> MessageResult:
    name = payload.name.strip()
    email = payload.email.strip()
    message = payload.message.strip()

    if not name or not email or not payload.subject.strip() or not message:
        raise HTTPException(status_code=400, detail="All fields are required.")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")
    if len(message) < MESSAGE_MIN_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Your message should be at least {MESSAGE_MIN_LEN} characters.",
        )

    who = current_user.username if current_user is not None else "guest"
    logger.info(
        "Contact form (%s) — %s <%s> | %s | %s",
        who, name, email, payload.subject.strip(), message[:1000],
    )

    return MessageResult(
        detail="Thanks! Your message has been received — we'll get back to you shortly."
    )
