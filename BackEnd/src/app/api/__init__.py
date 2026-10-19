"""Aggregates every /v4 sub-router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import admin
from app.api import applications
from app.api import auth
from app.api import banks
from app.api import chain_api
from app.api import complaints
from app.api import demo
from app.api import face
from app.api import identity_docs
from app.api import legal_api
from app.api import loans
from app.api import me_notices
from app.api import my_bank
from app.api import officer
from app.api import payouts
from app.api import postaudit
from app.api import public
from app.api import seller_reports
from app.api import shops
from app.api import webank

router = APIRouter(prefix="/v4")
for _module in (auth, face, public, shops, applications, identity_docs, officer, complaints, loans, my_bank, me_notices, seller_reports, postaudit, banks, chain_api, payouts, admin, legal_api, webank, demo):
    router.include_router(_module.router)
