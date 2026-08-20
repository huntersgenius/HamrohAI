"""Phone number as the single identity key (spec 2.1)."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
import sqlalchemy as sa

from app.core.config import settings
from app.core.phone import normalize_phone
from app.models.enums import AuthProvider
from app.models.user import AuthIdentity, User
from app.services import auth as auth_service
from app.services.oauth import OAuthProfile, verify_telegram_payload
from tests.conftest import make_user


class TestPhoneNormalization:
    @pytest.mark.parametrize(
        "raw",
        [
            "+998901234567",
            "998901234567",
            "90 123 45 67",
            "+998 90 123-45-67",
            "(90) 1234567",
        ],
    )
    def test_all_local_formats_collapse_to_one_identity(self, raw: str) -> None:
        # Every way a user might type their number must land on one key,
        # otherwise "one phone = one account" silently breaks.
        assert normalize_phone(raw) == "+998901234567"

    def test_rejects_invalid(self) -> None:
        from app.core.errors import ValidationError

        with pytest.raises(ValidationError):
            normalize_phone("123")


class TestAccountMerge:
    async def test_google_then_phone_is_one_account(self, db) -> None:
        """Signing in with Google, then with the same phone, must not fork."""
        phone = "+998901234567"
        user, created = await auth_service.get_or_create_user_by_phone(db, phone)
        assert created is True

        # The same person now arrives through Google.
        profile = OAuthProfile(subject="google-sub-1", email="a@example.com", full_name="A")
        await auth_service.attach_identity(db, user, AuthProvider.GOOGLE, profile.subject, {})
        await db.commit()

        again, created_again = await auth_service.get_or_create_user_by_phone(db, phone)
        assert created_again is False
        assert again.id == user.id

        total = await db.scalar(sa.select(sa.func.count()).select_from(User))
        assert total == 1

        identities = await db.scalars(
            sa.select(AuthIdentity).where(AuthIdentity.user_id == user.id)
        )
        providers = {i.provider for i in identities}
        assert providers == {AuthProvider.PHONE, AuthProvider.GOOGLE}

    async def test_identity_cannot_be_stolen_by_another_account(self, db) -> None:
        from app.core.errors import ConflictError

        first = await make_user(db, "+998901111111")
        second = await make_user(db, "+998902222222")
        await auth_service.attach_identity(db, first, AuthProvider.GOOGLE, "shared-sub")
        await db.commit()

        with pytest.raises(ConflictError):
            await auth_service.attach_identity(db, second, AuthProvider.GOOGLE, "shared-sub")

    async def test_relinking_replaces_the_previous_subject(self, db) -> None:
        user = await make_user(db, "+998903333333")
        await auth_service.attach_identity(db, user, AuthProvider.GOOGLE, "old-sub")
        await auth_service.attach_identity(db, user, AuthProvider.GOOGLE, "new-sub")
        await db.commit()

        rows = list(
            (
                await db.scalars(
                    sa.select(AuthIdentity).where(
                        AuthIdentity.user_id == user.id,
                        AuthIdentity.provider == AuthProvider.GOOGLE,
                    )
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].subject == "new-sub"


class TestPhoneGate:
    async def test_no_session_without_a_verified_phone(self, db) -> None:
        from app.core.errors import AuthError

        user = await make_user(db, "+998904444444", verified=False)
        with pytest.raises(AuthError) as excinfo:
            await auth_service.issue_tokens(db, user)
        assert excinfo.value.code == "phone_verification_required"

    async def test_oauth_returns_onboarding_token_not_a_session(self, client, db) -> None:
        """Google sign-in for an unknown phone must not hand out API access."""
        payload = _telegram_payload(user_id=555)
        response = await client.post("/api/v1/auth/telegram", json=payload)
        assert response.status_code == 200

        body = response.json()
        assert body["tokens"] is None
        assert body["onboarding_token"]
        assert body["state"]["phone_verification_required"] is True

    async def test_onboarding_token_only_authorises_phone_verification(self, db) -> None:
        profile = OAuthProfile(subject="tg-1", full_name="T")
        token = auth_service.issue_onboarding_token(profile, AuthProvider.TELEGRAM, "uz")

        # It is not an access token, so it cannot authenticate ordinary requests.
        from app.core.errors import AuthError
        from app.core.security import decode_token

        with pytest.raises(AuthError):
            decode_token(token, expected_type="access")

        provider, parsed, locale = auth_service.read_onboarding_token(token)
        assert provider == AuthProvider.TELEGRAM
        assert parsed.subject == "tg-1"
        assert locale == "uz"


class TestTelegramSignature:
    def test_valid_signature_accepted(self) -> None:
        payload = _telegram_payload(user_id=777)
        profile = verify_telegram_payload(payload)
        assert profile.subject == "777"

    def test_tampered_payload_rejected(self) -> None:
        from app.core.errors import AuthError

        payload = _telegram_payload(user_id=777)
        payload["first_name"] = "Someone Else"
        with pytest.raises(AuthError):
            verify_telegram_payload(payload)

    def test_expired_login_rejected(self) -> None:
        from app.core.errors import AuthError

        payload = _telegram_payload(user_id=777, auth_date=int(time.time()) - 999_999)
        with pytest.raises(AuthError):
            verify_telegram_payload(payload)


class TestSessionRotation:
    async def test_refresh_rotates_and_old_token_dies(self, db) -> None:
        user = await make_user(db, "+998905555555")
        tokens = await auth_service.issue_tokens(db, user)
        await db.commit()

        rotated = await auth_service.rotate_refresh_token(db, tokens.refresh_token)
        await db.commit()
        assert rotated.refresh_token != tokens.refresh_token

    async def test_reusing_a_rotated_token_kills_every_session(self, db) -> None:
        from app.core.errors import AuthError
        from app.models.user import RefreshSession

        user = await make_user(db, "+998906666666")
        tokens = await auth_service.issue_tokens(db, user)
        await db.commit()
        await auth_service.rotate_refresh_token(db, tokens.refresh_token)
        await db.commit()

        # Replaying the old token looks like theft: everything is revoked.
        with pytest.raises(AuthError) as excinfo:
            await auth_service.rotate_refresh_token(db, tokens.refresh_token)
        assert excinfo.value.code == "refresh_token_reused"
        await db.commit()

        live = await db.scalar(
            sa.select(sa.func.count())
            .select_from(RefreshSession)
            .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        )
        assert live == 0


def _telegram_payload(*, user_id: int, auth_date: int | None = None) -> dict:
    data = {
        "id": user_id,
        "first_name": "Test",
        "username": "testuser",
        "auth_date": auth_date or int(time.time()),
    }
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data
