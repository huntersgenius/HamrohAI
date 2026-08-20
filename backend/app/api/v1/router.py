"""v1 API router aggregate."""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    billing,
    consultations,
    doctors,
    mock,
    patients,
    threads,
    webhooks,
)
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(doctors.router)
api_router.include_router(patients.router)
api_router.include_router(patients.documents_router)
api_router.include_router(threads.router)
api_router.include_router(consultations.router)
api_router.include_router(ai.router)
api_router.include_router(ai.notifications_router)
api_router.include_router(billing.router)
api_router.include_router(billing.subscription_router)
api_router.include_router(webhooks.router)

# The mock surface never exists in production: the routes are not registered at
# all, so there is nothing to authenticate, rate-limit or accidentally leave on.
if not settings.is_production:
    api_router.include_router(mock.router)
