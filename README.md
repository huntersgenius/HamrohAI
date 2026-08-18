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

## Litsenziya

Proprietary — Hamroh.
