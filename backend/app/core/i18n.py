"""Server-side translations for push notifications, IVR scripts and API errors.

The mobile app localizes its own UI; the server still needs translations because
push notifications and voice calls are rendered outside the app. Locale is taken
from the recipient's ``users.locale`` column, never from the request.
"""

from __future__ import annotations

from typing import Final, Literal

Locale = Literal["uz", "ru", "en"]
SUPPORTED_LOCALES: Final[tuple[Locale, ...]] = ("uz", "ru", "en")
FALLBACK_LOCALE: Final[Locale] = "uz"

MESSAGES: Final[dict[str, dict[str, str]]] = {
    # ------------------------------------------------------------ push: doctor
    "push.patient_added.title": {
        "uz": "Yangi bemor",
        "ru": "Новый пациент",
        "en": "New patient",
    },
    "push.patient_added.body": {
        "uz": "{patient_name} sizning bemoringiz sifatida ulandi.",
        "ru": "{patient_name} присоединился(-ась) как ваш пациент.",
        "en": "{patient_name} joined as your patient.",
    },
    "push.consultation_new.title": {
        "uz": "Yangi konsultatsiya so'rovi",
        "ru": "Новый запрос на консультацию",
        "en": "New consultation request",
    },
    "push.consultation_new.body": {
        "uz": "{specialty} bo'yicha yangi so'rov — {price}",
        "ru": "Новый запрос по специальности «{specialty}» — {price}",
        "en": "New request in {specialty} — {price}",
    },
    "push.ai_escalation.title": {
        "uz": "Bemordan savol",
        "ru": "Вопрос от пациента",
        "en": "Question from a patient",
    },
    "push.ai_escalation.body": {
        "uz": "{patient_name} savoli AI protokolidan tashqarida — javobingiz kutilmoqda.",
        "ru": "Вопрос пациента {patient_name} вне протокола ИИ — требуется ваш ответ.",
        "en": "{patient_name}'s question falls outside the AI protocol — your reply is needed.",
    },
    "push.diagnosis_pending.title": {
        "uz": "Tashxis tasdiqlanishi kutilmoqda",
        "ru": "Диагноз ожидает подтверждения",
        "en": "Diagnosis awaiting confirmation",
    },
    "push.diagnosis_pending.body": {
        "uz": "{patient_name} tashxis yozuvini kiritdi — ko'rib chiqing.",
        "ru": "{patient_name} добавил(-а) запись о диагнозе — проверьте её.",
        "en": "{patient_name} submitted a diagnosis entry — please review it.",
    },
    "push.diagnosis_change_request.title": {
        "uz": "Tashxisni o'zgartirish taklifi",
        "ru": "Предложение изменить диагноз",
        "en": "Diagnosis change proposed",
    },
    "push.diagnosis_change_request.body": {
        "uz": "{patient_name} tasdiqlangan tashxisga o'zgartirish taklif qildi.",
        "ru": "{patient_name} предложил(-а) изменение подтверждённого диагноза.",
        "en": "{patient_name} proposed a change to a verified diagnosis.",
    },
    "push.wallet_updated.title": {
        "uz": "Hamyon yangilandi",
        "ru": "Кошелёк обновлён",
        "en": "Wallet updated",
    },
    "push.wallet_updated.body": {
        "uz": "Balansingizga {amount} qo'shildi. Joriy balans: {balance}",
        "ru": "На баланс зачислено {amount}. Текущий баланс: {balance}",
        "en": "{amount} was credited. Current balance: {balance}",
    },
    "push.weekly_report.title": {
        "uz": "Haftalik hisobot",
        "ru": "Еженедельный отчёт",
        "en": "Weekly report",
    },
    "push.weekly_report.body": {
        "uz": "{patient_name} bo'yicha haftalik hisobot tayyor.",
        "ru": "Еженедельный отчёт по пациенту {patient_name} готов.",
        "en": "The weekly report for {patient_name} is ready.",
    },
    # ----------------------------------------------------------- push: patient
    "push.consultation_answered.title": {
        "uz": "Javob keldi",
        "ru": "Получен ответ",
        "en": "You have a reply",
    },
    "push.consultation_answered.body": {
        "uz": "Shifokor {doctor_name} savolingizga javob berdi.",
        "ru": "Врач {doctor_name} ответил(-а) на ваш вопрос.",
        "en": "Dr. {doctor_name} answered your question.",
    },
    "push.consultation_refunded.title": {
        "uz": "Pul qaytarildi",
        "ru": "Средства возвращены",
        "en": "Payment refunded",
    },
    "push.consultation_refunded.body": {
        "uz": "Afsuski javob kelmadi. {amount} to'liq qaytarildi.",
        "ru": "К сожалению, ответа не поступило. {amount} возвращены полностью.",
        "en": "Unfortunately no reply arrived. {amount} has been fully refunded.",
    },
    "push.medication_due.title": {
        "uz": "Dori vaqti",
        "ru": "Время приёма лекарства",
        "en": "Medication time",
    },
    "push.medication_due.body": {
        "uz": "{medication} — {dose}. Ichganingizdan keyin belgilang.",
        "ru": "{medication} — {dose}. Отметьте после приёма.",
        "en": "{medication} — {dose}. Mark it once taken.",
    },
    "push.checkin_due.title": {
        "uz": "Bugungi kuzatuv",
        "ru": "Сегодняшний контроль",
        "en": "Today's check-in",
    },
    "push.checkin_due.body": {
        "uz": "Bugungi ko'rsatkichlaringizni kiriting.",
        "ru": "Внесите сегодняшние показатели.",
        "en": "Please record today's readings.",
    },
    "push.doctor_replied.title": {
        "uz": "Shifokoringizdan xabar",
        "ru": "Сообщение от вашего врача",
        "en": "Message from your doctor",
    },
    "push.doctor_replied.body": {
        "uz": "{doctor_name} savolingizga javob yozdi.",
        "ru": "{doctor_name} ответил(-а) на ваш вопрос.",
        "en": "{doctor_name} replied to your question.",
    },
    # ------------------------------------------------------------------- IVR
    "ivr.medication_reminder": {
        "uz": (
            "Assalomu alaykum. Bu Hamroh ilovasidan eslatma. "
            "{medication} dorisini qabul qilish vaqti keldi. "
            "Agar dorini ichgan bo'lsangiz, bir raqamini bosing."
        ),
        "ru": (
            "Здравствуйте. Это напоминание от приложения Hamroh. "
            "Пришло время принять лекарство {medication}. "
            "Если вы уже приняли лекарство, нажмите один."
        ),
        "en": (
            "Hello. This is a reminder from the Hamroh app. "
            "It is time to take {medication}. "
            "If you have already taken it, press one."
        ),
    },
    "ivr.confirmed": {
        "uz": "Rahmat, belgilandi. Sog' bo'ling.",
        "ru": "Спасибо, отмечено. Будьте здоровы.",
        "en": "Thank you, it has been recorded. Stay well.",
    },
    "ivr.not_confirmed": {
        "uz": "Rahmat. Ilovada belgilashni unutmang.",
        "ru": "Спасибо. Не забудьте отметить в приложении.",
        "en": "Thank you. Please remember to mark it in the app.",
    },
    # -------------------------------------------------------------------- SMS
    "sms.otp": {
        "uz": "Hamroh tasdiqlash kodi: {code}. Kodni hech kimga bermang.",
        "ru": "Код подтверждения Hamroh: {code}. Никому не сообщайте код.",
        "en": "Your Hamroh verification code: {code}. Do not share it with anyone.",
    },
    "sms.invite": {
        "uz": "Hamroh: shifokoringiz sizni taklif qildi. Kod: {code}. Ilova: {link}",
        "ru": "Hamroh: ваш врач пригласил вас. Код: {code}. Приложение: {link}",
        "en": "Hamroh: your doctor invited you. Code: {code}. App: {link}",
    },
    # --------------------------------------------------------------- AI text
    "ai.escalation_notice": {
        "uz": "Bu savolni {doctor_name}ga yetkazaman — u sizga javob beradi.",
        "ru": "Я передам этот вопрос врачу {doctor_name} — он(-а) вам ответит.",
        "en": "I will pass this question to {doctor_name}, who will reply to you.",
    },
    "ai.no_doctor_notice": {
        "uz": (
            "Sizda hali biriktirilgan shifokor yo'q. "
            "«Maslahat olish» bo'limidan foydalanib, shifokordan javob oling."
        ),
        "ru": (
            "У вас пока нет прикреплённого врача. "
            "Воспользуйтесь разделом «Получить консультацию», чтобы получить ответ врача."
        ),
        "en": (
            "You do not have an assigned doctor yet. "
            "Please use the “Get advice” section to reach a doctor."
        ),
    },
    "ai.safety_disclaimer": {
        "uz": (
            "Men tashxis qo'ymayman va dori tayinlamayman — "
            "faqat shifokoringiz tasdiqlagan protokol bo'yicha yordam beraman."
        ),
        "ru": (
            "Я не ставлю диагнозы и не назначаю лечение — "
            "я помогаю только в рамках протокола, утверждённого вашим врачом."
        ),
        "en": (
            "I do not diagnose or prescribe — "
            "I only help within the protocol approved by your doctor."
        ),
    },
    "ai.emergency": {
        "uz": (
            "Bu belgilar shoshilinch tibbiy yordam talab qilishi mumkin. "
            "Iltimos, darhol 103 raqamiga qo'ng'iroq qiling yoki eng yaqin "
            "shifoxonaga murojaat qiling."
        ),
        "ru": (
            "Эти признаки могут требовать неотложной помощи. "
            "Пожалуйста, немедленно позвоните 103 или обратитесь в ближайшую больницу."
        ),
        "en": (
            "These signs may require emergency care. "
            "Please call 103 immediately or go to the nearest hospital."
        ),
    },
}


def translate(key: str, locale: str | None = None, **params: object) -> str:
    """Look up ``key`` for ``locale`` and interpolate ``params``.

    Falls back to Uzbek, then to the key itself, so a missing translation degrades
    into something loggable rather than raising in a notification worker.
    """
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(normalize_locale(locale)) or entry.get(FALLBACK_LOCALE) or key
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError):
        return text


def normalize_locale(locale: str | None) -> Locale:
    if not locale:
        return FALLBACK_LOCALE
    short = locale.split("-")[0].split("_")[0].lower()
    if short in SUPPORTED_LOCALES:
        return short  # type: ignore[return-value]
    return FALLBACK_LOCALE


def format_money(amount_uzs: int, locale: str | None = None) -> str:
    """Uzbek sum uses a space as the thousands separator in all three locales."""
    formatted = f"{amount_uzs:,}".replace(",", " ")
    suffix = {"uz": "so'm", "ru": "сум", "en": "UZS"}[normalize_locale(locale)]
    return f"{formatted} {suffix}"
