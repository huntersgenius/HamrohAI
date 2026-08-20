# Hamroh

Surunkali kasallik bemorlarini uyda kuzatish va onlayn shifokor konsultatsiyasi platformasi
(O'zbekiston). — *Chronic illness home-monitoring and online doctor consultation platform.*

Hamroh ikkita teng maqsadga xizmat qiladi:

1. **Uyda kuzatuv** — bemor o'z shifokori bilan doimiy bog'liqlikda: dori nazorati,
   ko'rsatkich kuzatuvi, tendensiya tahlili, AI hamrohligi.
2. **Hududiy tenglik** — shifokorga jismoniy kirish cheklangan hududlar uchun bir martalik
   onlayn konsultatsiya.

## Repozitoriya tuzilishi

```
backend/     FastAPI + PostgreSQL + S3 (MinIO) — REST API, AI, to'lovlar, ish oqimlari
mobile/      Flutter ilova (iOS + Android, bitta kod bazasi)
docs/        Arxitektura, ma'lumotlar modeli, ishga tushirish qo'llanmasi
deploy/      Docker Compose, muhit namunalari
```

## Tez ishga tushirish

```bash
cp deploy/.env.example deploy/.env    # sozlamalarni to'ldiring
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml exec api alembic upgrade head
docker compose -f deploy/docker-compose.yml exec api python -m app.cli seed
```

API hujjatlari: <http://localhost:8000/docs>

Batafsil: [`docs/README.md`](docs/README.md).

## Asosiy tamoyillar

- **Telefon raqami — yagona shaxs identifikatori.** Google/Telegram/telefon — qaysi usul
  bo'lmasin, SMS tasdiqlash majburiy; bir xil raqam har doim bitta akkaunt.
- **Care-thread izolyatsiyasi.** Har bir bemor–shifokor bog'lanishi mutlaqo ajratilgan
  ma'lumotlar konteyneri. Bir shifokor boshqasining ipini hech qachon ko'rmaydi.
- **AI hech qachon tashxis qo'ymaydi.** Faqat tasdiqlangan protokollar (RAG), protokoldan
  tashqari savol — biriktirilgan shifokorga eskalatsiya.
- **Ma'lumotlar O'zbekiston hududida saqlanadi** — qonuniy talab (performance emas).

---

# MOCK REJIM — haqiqiy kalitlarsiz to'liq sinash

Click/Payme merchant, Eskiz/Play Mobile va Twilio arizalari hali berilmagan, ya'ni
**haqiqiy API kalitlari hozircha yo'q**. Shu sababli har bir tashqi servisning
mock rejimi bor: mock **hech qanday so'rov yubormaydi**, provayderning
muvaffaqiyatli javobini shu jarayonning o'zida simulyatsiya qiladi.

Rejim bitta o'zgaruvchi bilan boshqariladi (`deploy/.env`):

| O'zgaruvchi | `mock` (hozirgi holat) | `real` |
|---|---|---|
| `SMS_MODE` | SMS yuborilmaydi, kod outbox'ga yoziladi | `SMS_PROVIDER` (eskiz/playmobile) chaqiriladi |
| `IVR_MODE` | qo'ng'iroq qilinmaydi, chaqiruv yoziladi | Twilio Voice API chaqiriladi |
| `PUSH_MODE` | push yuborilmaydi, "yetkazildi" deb qaytadi | FCM HTTP v1 chaqiriladi |
| `PAYMENT_MODE` | ichki simulyator sahifasi | my.click.uz / checkout.paycom.uz |
| `AI_MODE` | model chaqirilmaydi, protokol matni qaytariladi | Anthropic API chaqiriladi |

**Almashtirish tartibi:** kalitlar kelib tushgan sari bittalab o'zgartiriladi —
masalan SMS shartnomasi imzolangach `SMS_MODE=real` + `SMS_PROVIDER=eskiz` +
`ESKIZ_EMAIL/ESKIZ_PASSWORD`. Kodda hech narsa o'zgartirilmaydi.

**Xavfsizlik qulfi.** `ENV=production` bo'lganda mock rejim bilan ilova umuman
ishga tushmaydi — konfiguratsiya import paytida xato beradi
(`app/core/config.py`, `_no_mocks_in_production`). Mock rejimdagi to'lov "to'landi"
deb belgilaydi, lekin pul harakati bo'lmaydi; buni tasodifan production'ga
chiqarish — bu konfiguratsiya qila oladigan eng qimmat xato.

### To'lovni mock rejimda qanday sinash mumkin

Mock rejimda `POST /api/v1/consultations` qaytaradigan `checkout_url` haqiqiy
shlyuz o'rniga ichki simulyator sahifasiga ishora qiladi:

```
http://localhost:8000/api/v1/mock/checkout/<payment_id>
```

Sahifadagi "To'lovni tasdiqlash" tugmasi — yoki to'g'ridan-to'g'ri
`POST /api/v1/mock/payments/<payment_id>/confirm` — **haqiqiy** Click
`Prepare→Complete` yoki Payme `CreateTransaction→PerformTransaction`
ketma-ketligini ishga tushiradi: haqiqiy MD5 imzo, haqiqiy JSON-RPC, haqiqiy
handler. Faqat tarmoq bosqichi olib tashlangan. Shu sababli mock rejimda
sinalgan kod — production'da ishlaydigan kodning aynan o'zi.

Simulyatsiya qilingan barcha xabarlarni (SMS kodi, IVR qo'ng'irog'i, push)
o'qish:

```bash
curl localhost:8000/api/v1/mock/outbox            # hammasi
curl "localhost:8000/api/v1/mock/outbox?kind=sms" # faqat SMS — OTP kodi shu yerda
curl localhost:8000/api/v1/mock/status            # qaysi servis mock rejimda
```

`/mock/*` yo'llari `ENV=production` bo'lganda **umuman ro'yxatdan o'tmaydi**
(`app/api/v1/router.py`), qo'shimcha ravishda har bir handler ham tekshiradi.

Joriy holatni `/health` ham ko'rsatadi: `mocked_integrations` maydoni.

Testlar: `backend/tests/test_mock_mode.py` (19 ta test) — jumladan mock rejimda
`httpx.AsyncClient` ochilsa test darhol yiqiladi, ya'ni "hech narsa yuborilmaydi"
degani tekshirilgan fakt.

---

# PRODUCTION'GA CHIQISHDAN OLDIN ALMASHTIRILISHI KERAK BO'LGAN FAYLLAR VA KALITLAR

Quyidagilarning hammasi hozirda **placeholder / ishlab chiqish qiymatlari**.
Ro'yxat to'liq: bu bo'limdagi hamma narsa almashtirilmaguncha ilova
production'ga chiqmaydi.

## 1. Fayllar

| Fayl | Hozirgi holati | Haqiqiy qiymat qayerdan olinadi |
|---|---|---|
| `mobile/android/app/google-services.json` | **PLACEHOLDER** (`project_id: hamroh-placeholder-replace-me`) | Firebase Console → loyiha → *Project settings* → *Your apps* → Android ilova (`uz.hamroh.hamroh`) → `google-services.json` yuklab olish |
| `mobile/ios/Runner/GoogleService-Info.plist` | **PLACEHOLDER** (XML izohida ogohlantirish bor) | Firebase Console → *Your apps* → iOS ilova (bundle id `uz.hamroh.hamroh`) → `GoogleService-Info.plist`; Xcode'da `Runner` target'iga qo'shiladi |
| `deploy/.env` | mavjud emas — `deploy/.env.example` dan nusxa olinadi | pastdagi 2-jadval |
| `mobile/android/key.properties` + release keystore | **mavjud emas** — release APK hozir *debug* kalit bilan imzolanadi (`android/app/build.gradle.kts`, `signingConfig = signingConfigs.getByName("debug")`) | `keytool -genkey -v -keystore hamroh-release.jks -keyalg RSA -keysize 2048 -validity 10000 -alias hamroh` — Play Store debug kalit bilan imzolangan APK'ni qabul qilmaydi |

> `google-services.json` ichida JSON izoh qo'llab-quvvatlanmagani uchun
> ogohlantirish `_HAMROH_OGOHLANTIRISH` kaliti sifatida yozilgan; Gradle plagini
> notanish kalitlarni e'tiborsiz qoldiradi.

## 2. `deploy/.env` kalitlari

| Kalit | Qayerdan | Almashtirilmasa nima bo'ladi |
|---|---|---|
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` | barcha sessiya tokenlari qalbakilashtiriladi |
| `POSTGRES_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | o'z infratuzilmangiz | baza va fayllar ochiq qoladi |
| `CLICK_MERCHANT_ID`, `CLICK_SERVICE_ID`, `CLICK_MERCHANT_USER_ID`, `CLICK_SECRET_KEY` | Click merchant kabinet (`merchant.click.uz`) — ariza tasdiqlangandan keyin | `PAYMENT_MODE=real` da imzo tekshiruvi hech qachon o'tmaydi |
| `PAYME_MERCHANT_ID`, `PAYME_KEY` | Payme merchant kabinet (`business.payme.uz`) | webhook `Basic Paycom:<key>` autentifikatsiyasi rad etiladi |
| `PAYME_TEST_KEY` | Payme sandbox | faqat `ENV != production` da ishlaydi (kod darajasida) |
| `ESKIZ_EMAIL`, `ESKIZ_PASSWORD` *yoki* `PLAYMOBILE_LOGIN`, `PLAYMOBILE_PASSWORD` | Eskiz (`notify.eskiz.uz`) yoki Play Mobile shartnomasi | OTP SMS yuborilmaydi — hech kim ro'yxatdan o'ta olmaydi |
| `SMS_SENDER` | provayder tasdiqlagan alfa-nom / qisqa raqam | SMS rad etiladi |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | `twilio.com/console` | ovozli dori eslatmasi qo'ng'irog'i ishlamaydi |
| `FCM_PROJECT_ID`, `FCM_CREDENTIALS_JSON` | Firebase Console → *Service accounts* → *Generate new private key* (bir qatorli JSON) | push bildirishnomalar yetkazilmaydi |
| `GOOGLE_CLIENT_IDS` | Google Cloud Console → *Credentials* → OAuth client ID (android, ios, web — vergul bilan) | "Google bilan kirish" ishlamaydi |
| `TELEGRAM_BOT_TOKEN` | Telegram `@BotFather` | "Telegram bilan kirish" ishlamaydi |
| `ANTHROPIC_API_KEY` | `console.anthropic.com` | AI javoblari faqat protokol matni bo'ladi |
| `IVR_WEBHOOK_BASE_URL` | ilovaning haqiqiy public domeni (masalan `https://api.hamroh.uz`) | Click/Payme/Twilio callback'lari kelmaydi |
| `CORS_ORIGINS`, `TRUSTED_HOSTS` | `*` o'rniga aniq domenlar | har qanday sayt API'ga murojaat qila oladi |
| `OTP_DEBUG_RETURN_CODE` | **`false`** bo'lishi shart | OTP kodi API javobida qaytadi — akkauntni istalgan odam egallaydi |
| `SMS_MODE`, `IVR_MODE`, `PUSH_MODE`, `PAYMENT_MODE`, `AI_MODE` | hammasi **`real`** | `ENV=production` da ilova ishga tushmaydi (ataylab) |

## 3. Provayder kabinetida ro'yxatdan o'tkaziladigan manzillar

Kalitlar bilan bir vaqtda provayderga quyidagi URL'lar berilishi kerak:

```
Click  Prepare   POST  https://<domen>/api/v1/webhooks/click/prepare
Click  Complete  POST  https://<domen>/api/v1/webhooks/click/complete
Payme  Endpoint  POST  https://<domen>/api/v1/webhooks/payme
Twilio Voice     POST  https://<domen>/api/v1/webhooks/ivr/{call_id}/voice
```

## 4. Mobil ilova

```bash
flutter build apk --release --dart-define=API_BASE_URL=https://<domen>/api/v1
```

`API_BASE_URL` berilmasa ilova ishlab chiqish manzilini ishlatadi. Release
imzolash yuqoridagi 1-jadvalning oxirgi qatorida.

## 5. Infratuzilma

Serverlar **O'zbekiston hududida** joylashishi shart — bu tibbiy ma'lumotlarning
mahalliy saqlanishi bo'yicha qonuniy talab, ishlash tezligi masalasi emas.
`/health` javobidagi `data_residency_region` shuning uchun chiqariladi.

---

## CI

| Workflow | Nima qiladi |
|---|---|
| `.github/workflows/backend-ci.yml` | har push va PR'da: `ruff` + butun pytest to'plami **haqiqiy PostgreSQL 16 service container**ga qarshi, so'ng bo'sh bazaga `alembic upgrade head` |
| `.github/workflows/frontend-ci.yml` | `flutter analyze`, `flutter test`, `flutter build apk --release` (Ubuntu) va `flutter build ios --no-codesign` (macOS runner) |

Backend testlari SQLite bilan almashtirilmaydi: `tests/test_isolation.py`
`SELECT version()` natijasini va `pg_indexes` dagi qisman unikal indeksni
tekshiradi — SQLite'da bu kafolatlar mavjud emas.

Flutter SDK `subosito/flutter-action@v2` orqali **cache**'lanadi (versiya
`3.29.3` ga qadab qo'yilgan), Gradle keshi ham saqlanadi.

## Litsenziya

Proprietary — Hamroh.
