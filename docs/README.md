# Hamroh — texnik hujjat

Bu hujjat tizim arxitekturasi, asosiy qarorlar va ishga tushirish tartibini
tavsiflaydi. Mahsulot talablari asosiy topshiriq hujjatida.

---

## 1. Nima qurilgan

| Qism | Texnologiya | Joylashuv |
|---|---|---|
| Mobil ilova | Flutter (iOS + Android, bitta kod bazasi) | `mobile/` |
| Backend API | FastAPI + SQLAlchemy 2 (async) | `backend/app/` |
| Ma'lumotlar bazasi | PostgreSQL 16 | `deploy/docker-compose.yml` |
| Fayl saqlash | S3-mos (MinIO) | `deploy/docker-compose.yml` |
| Fon ishlari | Bitta asyncio scheduler jarayoni | `backend/app/jobs/` |

**Ma'lumotlar joylashuvi.** Barcha servislar O'zbekiston hududidagi
infratuzilmada ishlashi **shart**. Bu ishlash tezligi uchun emas — tibbiy
ma'lumotlarning mahalliy saqlanishi qonuniy talabi. `/health` javobida
`data_residency_region` maydoni shu sababli chiqariladi: deploymentni audit
qilish mumkin bo'lsin.

---

## 2. Uchta asosiy tuzilma qarori

### 2.1. Telefon raqami — yagona shaxs kaliti

`users.phone` — noyob (unique). Google va Telegram *o'zi* shaxsni tasdiqlamaydi:
ular faqat "bu odam o'sha tashqi akkauntni boshqaradi" degan faktni isbotlaydi.

Shu sababli provayder orqali kirish **sessiya bermaydi**. U qisqa muddatli
*onboarding token* qaytaradi va bu token faqat bitta amalga ruxsat beradi —
telefonni tasdiqlash. Tasdiqlangandan keyingina:

```
telefon → mavjud akkaunt topilsa      → provayder o'sha akkauntga biriktiriladi
        → topilmasa                   → yangi akkaunt yaratiladi
```

Dublikat akkaunt yaratish imkoniyati kod darajasida yo'q.

Amalga oshirilishi: `backend/app/services/auth.py`,
testlar: `backend/tests/test_identity.py`.

### 2.2. Care-thread — izolyatsiya chegarasi

Har bir bemor–shifokor bog'lanishi alohida `care_threads` yozuvi. **Barcha**
klinik jadvallar (`diagnoses`, `medications`, `metric_series`,
`metric_readings`, `checkin_submissions`, `documents`, `ai_messages`)
`care_thread_id` ustuniga ega.

Izolyatsiya faqat bitta joyda hal qilingani uchun haqiqiy:
`backend/app/services/access.py`. Klinik ma'lumotga tegadigan **har bir**
endpoint shu modul orqali o'tadi.

```python
access = await resolve_thread(db, thread_id, user)   # kim ekanini hal qiladi
access.require_doctor()                               # roldan kelib chiqqan gate
```

Ikkita muhim tafsilot:

- Ishtirokchi bo'lmagan foydalanuvchiga `403` emas, **`404`** qaytariladi —
  begona odam qaysi `thread_id` mavjudligini bilib olmasligi kerak.
- Bola-yozuv (masalan `diagnosis_id`) har doim `care_thread_id` bo'yicha qayta
  tekshiriladi: boshqa ipdagi id bilan o'z ipingiz orqali murojaat qilish
  ishlamaydi.

"Shaxsiy" konteyner — `doctor_user_id IS NULL` bo'lgan qator. Uning yagonaligi
qisman unikal indeks bilan bazada kafolatlangan:

```sql
CREATE UNIQUE INDEX uq_care_thread_personal
  ON care_threads (patient_user_id) WHERE doctor_user_id IS NULL;
```

Testlar: `backend/tests/test_isolation.py` (16 ta test).

### 2.3. AI — javob berish huquqini retrieval hal qiladi

Model **manba emas**. Ketma-ketlik qat'iy va kodda majburlangan
(`backend/app/services/ai/assistant.py`):

```
shoshilinch belgi?      → 103 skripti, model chaqirilmaydi
tashxis/doza so'rovi?   → shifokorga eskalatsiya
retrieval bo'sh?        → shifokorga eskalatsiya
retrieval topdi         → model faqat topilgan matnni qayta yozadi
```

Ya'ni "javob bormi yo'qmi" degan qarorni **retrieval bali** hal qiladi, model
emas. Model javobi yana bir bor tekshiriladi (`check_output`): agar u
protokoldan chiqib tashxis yoki doza haqida gapirsa — javob tashlab yuboriladi
va eskalatsiya qilinadi.

Eskalatsiya **o'sha ipning** shifokoriga boradi. Tasodifiy shifokorga emas,
pullik konsultatsiya ham ochilmaydi. Shifokor umuman bo'lmasa — shundagina
"Maslahat olish" bo'limi taklif qilinadi.

Testlar: `backend/tests/test_ai_safety.py` (32 ta test).

---

## 3. Ishga tushirish

```bash
cp deploy/.env.example deploy/.env
# SECRET_KEY ni to'ldiring:
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml exec api alembic upgrade head
docker compose -f deploy/docker-compose.yml exec api python -m app.cli seed
docker compose -f deploy/docker-compose.yml exec api python -m app.cli demo
```

API hujjatlari: <http://localhost:8000/docs> (production'da o'chiriladi).

### Mobil ilova

```bash
cd mobile
flutter pub get
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1
```

`10.0.2.2` — Android emulyatoridan host mashinaga murojaat manzili.

---

## 4. Operatsion buyruqlar

MVP'da admin panel yo'q (talab 1). Quyidagi amallar CLI orqali bajariladi:

```bash
# Shifokor hujjatlarini tasdiqlash
python -m app.cli approve-doctor +998901234567

# Kutilayotgan pul yechish so'rovlari
python -m app.cli payouts

# Qo'lda o'tkazilgan to'lovni belgilash
python -m app.cli complete-payout <payout-id> --note "karta orqali"

# Fon ishini qo'lda ishga tushirish
python -m app.cli run-job weekly_reports

# Provayderga qaytarilishi kerak bo'lgan to'lovlar
python -m app.cli refunds
```

Arxitektura kelajakdagi admin panelga tayyor: `UserRole.ADMIN` mavjud,
`audit_logs` jadvali yozib boradi, tasdiqlash mantiqi servis qatlamida.

---

## 5. Fon ishlari

`backend/app/jobs/scheduler.py` — bitta asyncio jarayon. Celery emas: ish yuki
bir nechta qisqa SQL sweep, va production'da bitta kam harakatlanuvchi qism
taqsimlangan rejalashtiruvchidan qimmatroq turadi.

| Ish | Davriylik | Vazifa |
|---|---|---|
| `medication_reminders` | 1 daq | Dori vaqti kelganda push |
| `reminder_calls` | 1 daq | ~18 daqiqa javobsizlikdan keyin IVR qo'ng'iroq |
| `missed_doses` | 15 daq | Tasdiqlanmagan dozalarni MISSED qilish |
| `dose_horizon` | 1 soat | Keyingi 7 kunlik dozalarni materializatsiya |
| `expire_consultations` | 10 daq | 24 soatlik SLA — avtomatik qaytarish |
| `expire_subscriptions` | kuniga | Muddati tugagan obunalar |
| `weekly_reports` | dushanba 08:00 | AI haftalik hisoboti |

Har bir ish **idempotent** — scheduler at-least-once, shuning uchun
to'g'rilik aniq vaqtga bog'liq emas.

---

## 6. To'lovlar

| | Click | Payme |
|---|---|---|
| Protokol | Prepare/Complete, form-encoded | JSON-RPC 2.0 |
| Autentifikatsiya | MD5 imzo (maydon tartibi qat'iy) | HTTP Basic `Paycom:<key>` |
| Valyuta birligi | so'm | tiyin (1 so'm = 100 tiyin) |
| Endpoint | `/webhooks/click/{prepare,complete}` | `/webhooks/payme` |

Ikkalasi ham **hech qachon 500 qaytarmaydi**: xato provayderning o'z xato
kodiga aylantiriladi, aks holda gateway cheksiz qayta urinadi. Barcha
callback'lar `provider_transaction_id` bo'yicha idempotent.

Pul oqimi:

```
bemor to'laydi (100%)
   → javob berilsa:  80% shifokor hamyoniga, 20% platforma
   → 24 soat javobsiz: 100% avtomatik qaytariladi
```

Hamyon — ichki ledger. Har bir kredit `idempotency_key` bilan yoziladi, shuning
uchun qayta urinilgan webhook shifokorga ikki marta to'lay olmaydi.

**Qaytarish (refund) haqida muhim eslatma.** SLA ishi 24 soat ichida javob
kelmasa konsultatsiyani *va unga bog'liq `payments` yozuvini* darhol `refunded`
holatiga o'tkazadi — ledger va provayder hisoboti bir-biriga mos bo'lib qoladi.
Ammo provayder tomonidagi haqiqiy reversal MVP'da **qo'lda** bajariladi, xuddi
pul yechish kabi:

```bash
python -m app.cli refunds                  # kutilayotgan reversal'lar ro'yxati
python -m app.cli settle-refund <payment-id>   # o'tkazilgandan keyin belgilash
```

Testlar: `backend/tests/test_payments.py` (29 ta test).

---

## 7. Testlar

```bash
cd backend
python -m pytest -q          # 172 ta test
ruff check app tests
```

Testlar haqiqiy PostgreSQL'ga qarshi ishlaydi (SQLite emas): sxema qisman
unikal indeks va JSONB'ga tayanadi, va bu test to'plami isbotlamoqchi bo'lgan
izolyatsiya kafolatlari faqat production'da ishlaydigan dvigatelda ma'noga ega.

| Fayl | Nima tekshiriladi |
|---|---|
| `test_identity.py` | Telefon — yagona kalit, akkaunt birlashtirish, sessiya rotatsiyasi |
| `test_isolation.py` | Care-thread izolyatsiyasi, har tomondan hujum |
| `test_ai_safety.py` | Shoshilinch aniqlash, tashxis rad etish, eskalatsiya manzili |
| `test_consultations.py` | Eksklyuziv claim, 80/20, SLA qaytarish, snapshot muzlatilishi |
| `test_payments.py` | Click/Payme protokol muvofiqligi, idempotentlik |
| `test_care_flows.py` | Shablon moslashtirish, dori jadvali, IVR, Excel |

---

## 8. Xavfsizlik

- Parollar yo'q — kirish faqat SMS/OAuth orqali.
- OTP kodlari bazada **xeshlangan** holda (`hash_lookup`), urinishlar cheklangan,
  qayta yuborish kutish vaqti bilan, kunlik kvota bilan.
- Refresh token har ishlatilganda **aylantiriladi**; eski tokenni qayta
  ishlatish — o'g'irlik belgisi, foydalanuvchining barcha sessiyalari bekor
  qilinadi.
- Kartaning to'liq raqami hech qachon saqlanmaydi — faqat oxirgi 4 raqam.
- Loglar redaktsiyalanadi: tashxis, savol, javob, telefon, token — hech biri
  log sinkiga tushmaydi (`app/core/logging.py`).
- `audit_logs` — klinik ma'lumotga kirish va pul harakati uchun append-only iz.
- Fayllar hech qachon ochiq emas: yuklab olish faqat qisqa muddatli presigned
  URL orqali, va faqat API ruxsat bergan foydalanuvchiga.

---

## 9. Nima qilinmagan (ataylab)

- **Admin panel** — talab 1 bo'yicha MVP'dan tashqarida. Shifokor tasdiqlash va
  pul yechish CLI orqali.
- **Avtomatik ommaviy to'lov** — talab 7 bo'yicha keyingi bosqich.
- **Realtime chat** — AI va eskalatsiya javoblari push orqali yetkaziladi;
  WebSocket qatlami hozircha kerak emas.
