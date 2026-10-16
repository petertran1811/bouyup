"""Give a demo seller (default lan@buoyup.vn) a clean slate so the onboarding flow starts over.

Her earlier applications and loans move to an archive account (<name>-archive@…, cannot log
in). Nothing is deleted: chain entries, events and bank records keep pointing at the same
application ids, so the ledger still verifies and officers still see the old cases. Open demo
loans are closed as archived so they never count as bad debt for the auto-approval switch.
Only runs in dev/demo/test and only for sellers that have a demo dossier (profiles/*.json).

    .venv/bin/python scripts/reset_demo_seller.py [email]
"""
from __future__ import annotations

import os
import secrets
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # DATABASE_URL and .env are relative to the backend folder

from sqlalchemy import select, update  # noqa: E402

from app.platform import events
from app.data_sources import profiles  # noqa: E402
from app.platform.security import hash_password, new_user_id  # noqa: E402
from app.platform.tables import BuApplication, BuLoan, BuUser  # noqa: E402
from app.platform.config import settings  # noqa: E402
from app.platform.db.session import session_scope  # noqa: E402
from app.platform.db.tables import utcnow  # noqa: E402


def reset(email: str) -> int:
    if settings.app_env not in ("dev", "demo", "test"):
        raise SystemExit(f"Chỉ chạy ở môi trường demo (APP_ENV hiện là {settings.app_env}).")
    if profiles.hint_for_email(email) is None:
        raise SystemExit(f"{email} không phải tài khoản mẫu có hồ sơ dựng sẵn.")
    with session_scope() as session:
        user = session.scalar(select(BuUser).where(BuUser.email == email))
        if user is None or user.role != "seller":
            raise SystemExit(f"Không có người bán {email}. Chạy ./run.sh một lần để tạo tài khoản mẫu.")
        local, domain = email.split("@", 1)
        archive_email = f"{local}-archive@{domain}"
        archive = session.scalar(select(BuUser).where(BuUser.email == archive_email))
        if archive is None:
            archive = BuUser(id=new_user_id(), email=archive_email,
                             password_hash=hash_password(secrets.token_urlsafe(24)),
                             display_name=f"{user.display_name} (lưu trữ)", role="seller", active=False)
            session.add(archive)
            session.flush()
        moved = session.execute(update(BuApplication).where(BuApplication.seller_user_id == user.id)
                                .values(seller_user_id=archive.id)).rowcount
        for loan in session.scalars(select(BuLoan).where(BuLoan.seller_user_id == user.id)):
            loan.seller_user_id = archive.id
            if loan.status != "closed":
                loan.doc = {**(loan.doc or {}), "archived_demo": {"at": utcnow().isoformat(), "status": loan.status,
                                                                   "outstanding": loan.outstanding}}
                loan.status = "closed"
                events.log(session, loan.application_id, "system", "demo_archived",
                           "Khoản vay mẫu được đóng khi làm lại hồ sơ demo", {"loan_id": loan.id})
        return moved


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "lan@buoyup.vn"
    n = reset(target)
    print(f"{target}: chuyển {n} hồ sơ cũ sang tài khoản lưu trữ. Đăng nhập lại để bắt đầu từ đầu.")
