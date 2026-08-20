"""Test fixtures.

Tests run against a real PostgreSQL database rather than SQLite: the schema
relies on partial unique indexes and JSONB, and the isolation guarantees this
suite exists to prove are only meaningful on the engine that ships.

Set ``TEST_DATABASE_URL`` to point at a scratch database; it is created and
dropped around the session.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-123456")
os.environ.setdefault("ENV", "local")
os.environ.setdefault("SMS_PROVIDER", "console")
os.environ.setdefault("PUSH_PROVIDER", "console")
os.environ.setdefault("IVR_PROVIDER", "console")
os.environ.setdefault("AI_PROVIDER", "console")
os.environ.setdefault("OTP_DEBUG_RETURN_CODE", "true")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:test-bot-token")

TEST_DB_URL = os.environ.setdefault(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://hamroh:hamroh@127.0.0.1:55432/hamroh_test",
)
os.environ["DATABASE_URL"] = TEST_DB_URL

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import db as db_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.care import CareThread  # noqa: E402
from app.models.enums import (  # noqa: E402
    CareThreadKind,
    DoctorVerificationStatus,
    UserRole,
)
from app.models.profile import DoctorProfile, PatientProfile  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import issue_tokens  # noqa: E402
from app.services.care import allocate_connect_code  # noqa: E402

ADMIN_URL = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
TEST_DB_NAME = TEST_DB_URL.rsplit("/", 1)[1]


@pytest.fixture(scope="session", autouse=True)
async def _create_database() -> AsyncIterator[None]:
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        await conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    await admin.dispose()

    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield

    await db_module.dispose_engine()
    admin = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
    await admin.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    """Truncate everything between tests so each starts from a known state."""
    yield
    engine = db_module.get_engine()
    tables = ", ".join(f'"{name}"' for name in Base.metadata.tables)
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    maker: async_sessionmaker[AsyncSession] = db_module.get_sessionmaker()
    async with maker() as session:
        yield session


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


# ----------------------------------------------------------------- factories
async def make_user(
    db: AsyncSession,
    phone: str,
    *,
    role: UserRole | None = None,
    full_name: str = "Test User",
    locale: str = "uz",
    verified: bool = True,
) -> User:
    user = User(
        phone=phone,
        phone_verified_at=datetime.now(UTC) if verified else None,
        role=role,
        full_name=full_name,
        locale=locale,
    )
    db.add(user)
    await db.flush()
    return user


async def make_doctor(
    db: AsyncSession,
    phone: str = "+998901000001",
    *,
    specialty: str = "endocrinologist",
    approved: bool = True,
    consultation_open: bool = True,
    price: int | None = 50_000,
    full_name: str = "Dr Test",
) -> tuple[User, DoctorProfile]:
    user = await make_user(db, phone, role=UserRole.DOCTOR, full_name=full_name)
    profile = DoctorProfile(
        user_id=user.id,
        full_name=full_name,
        specialty=specialty,
        experience_years=10,
        verification_status=(
            DoctorVerificationStatus.APPROVED if approved else DoctorVerificationStatus.PENDING
        ),
        verified_at=datetime.now(UTC) if approved else None,
        connect_code=await allocate_connect_code(db),
        consultation_open=consultation_open,
        consultation_price_uzs=price,
    )
    db.add(profile)
    await db.flush()

    from app.services.billing import start_trial

    await start_trial(db, profile)
    return user, profile


async def make_patient(
    db: AsyncSession, phone: str = "+998901000002", *, full_name: str = "Test Patient"
) -> User:
    user = await make_user(db, phone, role=UserRole.PATIENT, full_name=full_name)
    db.add(PatientProfile(user_id=user.id, full_name=full_name))
    await db.flush()
    return user


async def make_thread(db: AsyncSession, patient: User, doctor: User) -> CareThread:
    thread = CareThread(
        patient_user_id=patient.id,
        doctor_user_id=doctor.id,
        kind=CareThreadKind.DOCTOR,
        connected_at=datetime.now(UTC),
        last_activity_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def auth_headers(db: AsyncSession, user: User) -> dict[str, str]:
    tokens = await issue_tokens(db, user)
    await db.commit()
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def seed_catalog(db: AsyncSession) -> None:
    from app.cli import seed_protocols, seed_templates

    await seed_templates(db)
    await seed_protocols(db)
    await db.commit()
