"""Regression tests for API-shape bugs found by end-to-end testing.

Each of these passed unit testing but broke against a live server, so they are
pinned here rather than left to the smoke script.
"""

from __future__ import annotations

import sqlalchemy as sa

from app.models.enums import OtpPurpose
from app.models.profile import DoctorProfile
from app.models.template import DiagnosisTemplate
from app.schemas.doctor import DoctorProfileResponse
from app.services.otp import start_challenge
from app.services.templates import checkin_questions_for
from tests.conftest import auth_headers, make_doctor, seed_catalog


class TestPhoneVerifyBodyShape:
    async def test_accepts_a_flat_body(self, client, db) -> None:
        """The verify payload must be flat.

        Declaring `onboarding_token` as an embedded Body parameter made FastAPI
        nest *every* field under a wrapper key, which the mobile client does not
        send. The contract is one flat object.
        """
        challenge, code = await start_challenge(db, "+998905550001", OtpPurpose.LOGIN)
        await db.commit()

        response = await client.post(
            "/api/v1/auth/phone/verify",
            json={"challenge_id": str(challenge.id), "code": code},
        )
        assert response.status_code == 200, response.text
        assert response.json()["tokens"]["access_token"]

    async def test_accepts_an_optional_onboarding_token(self, client, db) -> None:
        from app.models.enums import AuthProvider
        from app.services.auth import issue_onboarding_token
        from app.services.oauth import OAuthProfile

        token = issue_onboarding_token(
            OAuthProfile(subject="tg-777", full_name="Test"),
            AuthProvider.TELEGRAM,
            "uz",
        )
        challenge, code = await start_challenge(db, "+998905550002", OtpPurpose.LOGIN)
        await db.commit()

        response = await client.post(
            "/api/v1/auth/phone/verify",
            json={
                "challenge_id": str(challenge.id),
                "code": code,
                "onboarding_token": token,
            },
        )
        assert response.status_code == 200, response.text

        # The provider is attached to the account that owns this phone number.
        from app.models.user import AuthIdentity, User

        user = await db.scalar(sa.select(User).where(User.phone == "+998905550002"))
        identity = await db.scalar(
            sa.select(AuthIdentity).where(
                AuthIdentity.user_id == user.id,
                AuthIdentity.provider == AuthProvider.TELEGRAM,
            )
        )
        assert identity is not None and identity.subject == "tg-777"

    async def test_rejects_a_missing_code(self, client, db) -> None:
        challenge, _ = await start_challenge(db, "+998905550003", OtpPurpose.LOGIN)
        await db.commit()

        response = await client.post(
            "/api/v1/auth/phone/verify", json={"challenge_id": str(challenge.id)}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"


class TestDoctorProfileSerialization:
    async def test_profile_serialises_with_its_subscription(self, db) -> None:
        """Serialising the profile must not trigger a lazy load.

        Pydantic reads every matching attribute, so a lazily-loaded relationship
        raises MissingGreenlet under async SQLAlchemy at response time.
        """
        doctor, _ = await make_doctor(db, "+998905550010")
        await db.commit()

        # A fresh session, as a real request would have.
        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor.id)
        )
        db.expunge_all()
        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor.id)
        )

        response = DoctorProfileResponse.model_validate(profile)
        assert response.full_name == "Dr Test"
        assert response.subscription is not None
        assert response.subscription.plan == "monthly"

    async def test_register_endpoint_returns_201(self, client, db) -> None:
        from app.models.care import Document
        from app.models.enums import DocumentPurpose, UserRole
        from tests.conftest import make_user

        user = await make_user(db, "+998905550011", role=UserRole.DOCTOR)
        document = Document(
            owner_user_id=user.id,
            purpose=DocumentPurpose.DOCTOR_LICENSE.value,
            storage_key="doctor_license/test/x.pdf",
            filename="licence.pdf",
            content_type="application/pdf",
            size_bytes=1024,
        )
        db.add(document)
        await db.flush()
        headers = await auth_headers(db, user)

        response = await client.post(
            "/api/v1/doctors/register",
            json={
                "full_name": "Aziza Karimova",
                "specialty": "endocrinologist",
                "experience_years": 14,
                "license_document_id": str(document.id),
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["verification_status"] == "pending"
        assert body["connect_code"]


class TestCheckinSlots:
    async def test_default_slot_returns_every_question_for_today(self, db) -> None:
        """The "Bugun" tab is one card, so the default slot means the whole day.

        Filtering it to a single slot hid the template's main indicator (morning
        glucose) and left the patient no way to record it.
        """
        await seed_catalog(db)
        template = await db.scalar(
            sa.select(DiagnosisTemplate).where(DiagnosisTemplate.code == "diabetes_t2")
        )

        keys = [q["key"] for q in checkin_questions_for(template)]
        assert "glucose_morning" in keys
        assert "glucose_evening" in keys
        assert "wellbeing" in keys

    async def test_a_specific_slot_still_narrows(self, db) -> None:
        await seed_catalog(db)
        template = await db.scalar(
            sa.select(DiagnosisTemplate).where(DiagnosisTemplate.code == "diabetes_t2")
        )

        keys = [q["key"] for q in checkin_questions_for(template, slot="morning")]
        assert "glucose_morning" in keys
        assert "glucose_evening" not in keys

    async def test_no_template_means_no_questions(self, db) -> None:
        assert checkin_questions_for(None) == []
