"""Approved protocol corpus for the AI companion (spec 8).

The assistant may only answer from this curated content. Every chunk is written
as *self-care guidance already agreed with a treating doctor* — never a
diagnosis, never a prescription, never a dose change. Anything a patient asks
that is not covered here is escalated to their doctor instead of answered.

In production this corpus is maintained through the (future) admin panel and the
``protocols import`` CLI command; the entries below are the launch baseline.
"""

from __future__ import annotations

from typing import Any, Final

PROTOCOLS: Final[list[dict[str, Any]]] = [
    {
        "slug": "general_safety",
        "title": {
            "uz": "Umumiy xavfsizlik qoidalari",
            "ru": "Общие правила безопасности",
            "en": "General safety rules",
        },
        "specialty": None,
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "role",
                "tags": ["ai", "rol", "роль", "role", "tashxis", "диагноз", "diagnosis"],
                "uz": (
                    "Men Hamroh yordamchisiman. Men tashxis qo'ymayman, dori tayinlamayman "
                    "va dozani o'zgartirmayman. Men faqat shifokoringiz tasdiqlagan protokol "
                    "doirasida kundalik kuzatuv, dori intizomi va ilovadan foydalanish "
                    "bo'yicha yordam beraman. Tashxis, davolash va doza bilan bog'liq har "
                    "qanday qaror faqat shifokoringizga tegishli."
                ),
                "ru": (
                    "Я — помощник Hamroh. Я не ставлю диагнозы, не назначаю лекарства и не "
                    "меняю дозировки. Я помогаю только в рамках протокола, утверждённого "
                    "вашим врачом: ежедневное наблюдение, приём препаратов и работа с "
                    "приложением. Любые решения о диагнозе, лечении и дозах принимает "
                    "только ваш врач."
                ),
                "en": (
                    "I am the Hamroh assistant. I do not diagnose, prescribe, or change "
                    "doses. I help only within the protocol approved by your doctor: daily "
                    "monitoring, medication routine, and using the app. Every decision about "
                    "diagnosis, treatment, and dosing belongs to your doctor alone."
                ),
            },
            {
                "key": "emergency",
                "tags": [
                    "shoshilinch",
                    "tez yordam",
                    "неотложная",
                    "скорая",
                    "emergency",
                    "103",
                ],
                "uz": (
                    "Quyidagi holatlarda darhol 103 raqamiga qo'ng'iroq qiling yoki eng "
                    "yaqin shifoxonaga boring: ko'krak qafasida kuchli og'riq, nafas olishning "
                    "og'irlashuvi, hushdan ketish, nutqning buzilishi, yuz yoki qo'l-oyoqning "
                    "bir tomonlama falajlanishi, to'xtamaydigan qon ketish, kuchli qorin "
                    "og'rig'i, tutqanoq. Bunday holatda ilovadan javob kutib turmang."
                ),
                "ru": (
                    "В следующих случаях немедленно звоните 103 или обратитесь в ближайшую "
                    "больницу: сильная боль в груди, затруднённое дыхание, потеря сознания, "
                    "нарушение речи, односторонняя слабость лица или конечностей, "
                    "непрекращающееся кровотечение, сильная боль в животе, судороги. "
                    "Не ждите ответа в приложении."
                ),
                "en": (
                    "Call 103 or go to the nearest hospital immediately if you have: severe "
                    "chest pain, difficulty breathing, loss of consciousness, slurred speech, "
                    "one-sided weakness of the face or limbs, bleeding that will not stop, "
                    "severe abdominal pain, or seizures. Do not wait for a reply in the app."
                ),
            },
            {
                "key": "medication_adherence",
                "tags": [
                    "dori",
                    "eslatma",
                    "unutdim",
                    "лекарство",
                    "напоминание",
                    "забыл",
                    "medication",
                    "missed dose",
                ],
                "uz": (
                    "Dorini o'z vaqtida qabul qilish davolashning asosidir. Agar dorini "
                    "ichishni unutgan bo'lsangiz, o'z boshingiz bilan ikki dozani birdan "
                    "qabul qilmang. Eslatmani ilovada 'Ichdim' tugmasi bilan belgilang. "
                    "Unutilgan doza haqida shifokoringizga xabar bering — keyingi qadamni "
                    "u aytadi."
                ),
                "ru": (
                    "Своевременный приём препаратов — основа лечения. Если вы пропустили "
                    "приём, не принимайте двойную дозу самостоятельно. Отмечайте приём "
                    "кнопкой «Принял» в приложении. Сообщите врачу о пропущенной дозе — "
                    "дальнейшие действия определит он."
                ),
                "en": (
                    "Taking medication on time is the foundation of treatment. If you miss a "
                    "dose, do not take a double dose on your own. Mark each intake with the "
                    "“Taken” button in the app. Tell your doctor about the missed dose — they "
                    "decide the next step."
                ),
            },
            {
                "key": "app_usage",
                "tags": [
                    "ilova",
                    "qanday",
                    "grafik",
                    "приложение",
                    "как",
                    "график",
                    "app",
                    "chart",
                ],
                "uz": (
                    "Kundalik ko'rsatkichlarni 'Bugun' bo'limidan kiriting. Kiritilgan har "
                    "bir qiymat avtomatik ravishda tendensiya grafigiga tushadi va "
                    "shifokoringiz uni ko'radi. 'Doktorlarim' bo'limida har bir shifokor "
                    "alohida varaqda — bir shifokorning ma'lumoti boshqasiga ko'rinmaydi."
                ),
                "ru": (
                    "Вводите ежедневные показатели в разделе «Сегодня». Каждое значение "
                    "автоматически попадает на график динамики, и ваш врач его видит. "
                    "В разделе «Мои врачи» каждый врач — на отдельной карточке: данные "
                    "одного врача не видны другому."
                ),
                "en": (
                    "Enter daily readings in the “Today” tab. Every value automatically joins "
                    "the trend chart your doctor sees. In “My doctors” each doctor has a "
                    "separate card — one doctor's data is never visible to another."
                ),
            },
        ],
    },
    {
        "slug": "diabetes_self_care",
        "title": {
            "uz": "Qandli diabet: kundalik o'z-o'zini kuzatish",
            "ru": "Сахарный диабет: ежедневный самоконтроль",
            "en": "Diabetes: daily self-monitoring",
        },
        "specialty": "endocrinologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "measurement",
                "tags": [
                    "qand",
                    "o'lchash",
                    "glyukometr",
                    "глюкоза",
                    "измерение",
                    "глюкометр",
                    "glucose",
                    "measure",
                ],
                "uz": (
                    "Qon shakarini shifokoringiz belgilagan tartibda o'lchang — odatda "
                    "ertalab nahorda va kechqurun. O'lchashdan oldin qo'lni sovun bilan yuvib "
                    "quriting; spirtdan keyin barmoq to'liq qurishi kerak. Natijani darhol "
                    "ilovaga kiriting, shunda grafik va shifokoringizning ko'rinishi yangilanadi."
                ),
                "ru": (
                    "Измеряйте глюкозу в порядке, назначенном врачом — обычно утром натощак "
                    "и вечером. Перед измерением вымойте руки с мылом и высушите; после "
                    "спирта палец должен полностью высохнуть. Сразу вносите результат в "
                    "приложение — график и данные для врача обновятся."
                ),
                "en": (
                    "Measure your blood glucose on the schedule your doctor set — usually "
                    "fasting in the morning and in the evening. Wash and dry your hands "
                    "first; if you use alcohol, let the finger dry completely. Enter the "
                    "result in the app right away so the chart and your doctor's view update."
                ),
            },
            {
                "key": "targets",
                "tags": ["norma", "maqsad", "норма", "цель", "target", "range"],
                "uz": (
                    "Ko'pchilik kattalar uchun odatiy maqsadli oraliq: nahorda 4.4–7.2 "
                    "mmol/L. Sizning shaxsiy maqsadli oralig'ingizni faqat shifokoringiz "
                    "belgilaydi va u ilovadagi grafikda ko'rsatiladi. Agar ko'rsatkich bir "
                    "necha kun ketma-ket oraliqdan chiqsa, shifokoringizga xabar bering."
                ),
                "ru": (
                    "Для большинства взрослых обычный целевой диапазон натощак — 4.4–7.2 "
                    "ммоль/л. Ваш индивидуальный целевой диапазон определяет только врач, и "
                    "он отображается на графике в приложении. Если показатели выходят за "
                    "пределы несколько дней подряд, сообщите врачу."
                ),
                "en": (
                    "For most adults the usual fasting target range is 4.4–7.2 mmol/L. Only "
                    "your doctor sets your personal target range, and it is shown on the "
                    "chart in the app. If readings stay outside the range for several days "
                    "in a row, tell your doctor."
                ),
            },
            {
                "key": "hypo_signs",
                "tags": [
                    "past qand",
                    "gipoglikemiya",
                    "titroq",
                    "низкий сахар",
                    "гипогликемия",
                    "hypoglycemia",
                    "low sugar",
                ],
                "uz": (
                    "Qand darajasi pasayganda: titroq, sovuq ter, ochlik, yurak tez urishi, "
                    "boshning aylanishi bo'lishi mumkin. Bunday holatda 15 gramm tez "
                    "hazm bo'ladigan uglevod qabul qiling (masalan bir stakan sharbat yoki "
                    "3-4 dona qand), 15 daqiqadan keyin qayta o'lchang. Hushdan ketish, "
                    "tutqanoq yoki yutolmaslik holatida — darhol 103."
                ),
                "ru": (
                    "При снижении сахара возможны: дрожь, холодный пот, чувство голода, "
                    "учащённое сердцебиение, головокружение. Примите 15 граммов быстрых "
                    "углеводов (стакан сока или 3–4 кусочка сахара) и через 15 минут "
                    "измерьте повторно. При потере сознания, судорогах или невозможности "
                    "глотать — немедленно 103."
                ),
                "en": (
                    "Low blood sugar can cause trembling, cold sweat, hunger, a fast "
                    "heartbeat, or dizziness. Take 15 grams of fast carbohydrate (a glass of "
                    "juice or 3–4 sugar cubes) and re-measure after 15 minutes. If there is "
                    "loss of consciousness, seizures, or inability to swallow — call 103 "
                    "immediately."
                ),
            },
            {
                "key": "lifestyle",
                "tags": [
                    "ovqat",
                    "parhez",
                    "sport",
                    "питание",
                    "диета",
                    "спорт",
                    "diet",
                    "exercise",
                ],
                "uz": (
                    "Umumiy tavsiyalar: ovqatni kuniga bir xil vaqtlarda qabul qiling, "
                    "shirin ichimliklardan voz keching, tarkibida tola ko'p bo'lgan "
                    "mahsulotlarni tanlang, imkon qadar kuniga 30 daqiqa piyoda yuring. "
                    "Shaxsiy parhez rejasi — shifokoringiz vazifasi; men ovqatlanish rejasini "
                    "o'zgartira olmayman."
                ),
                "ru": (
                    "Общие рекомендации: питайтесь в одно и то же время, откажитесь от "
                    "сладких напитков, выбирайте продукты с высоким содержанием клетчатки, "
                    "по возможности ходите пешком 30 минут в день. Индивидуальный план "
                    "питания составляет врач; я не могу его изменять."
                ),
                "en": (
                    "General advice: eat at consistent times, avoid sugary drinks, choose "
                    "high-fibre foods, and walk about 30 minutes a day when you can. Your "
                    "personal meal plan is your doctor's decision; I cannot change it."
                ),
            },
        ],
    },
    {
        "slug": "hypoglycemia_red_flags",
        "title": {
            "uz": "Diabet: xavfli belgilar",
            "ru": "Диабет: тревожные признаки",
            "en": "Diabetes: red flags",
        },
        "specialty": "endocrinologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "red_flags",
                "tags": [
                    "xavfli",
                    "asetom",
                    "hushdan",
                    "опасные",
                    "ацетон",
                    "рвота",
                    "red flag",
                    "ketone",
                ],
                "uz": (
                    "Shoshilinch tibbiy yordam kerak bo'lgan belgilar: qand darajasi 13.9 "
                    "mmol/L dan yuqori va tushmayapti, og'izdan aseton hidi, to'xtovsiz "
                    "qusish, chuqur va tez nafas olish, kuchli chanqoq bilan birga hushning "
                    "xiralashuvi. Darhol 103 ga qo'ng'iroq qiling."
                ),
                "ru": (
                    "Признаки, требующие неотложной помощи: уровень глюкозы выше 13.9 "
                    "ммоль/л и не снижается, запах ацетона изо рта, непрекращающаяся рвота, "
                    "глубокое частое дыхание, сильная жажда со спутанностью сознания. "
                    "Немедленно звоните 103."
                ),
                "en": (
                    "Signs that need emergency care: glucose above 13.9 mmol/L that will not "
                    "come down, a fruity/acetone smell on the breath, persistent vomiting, "
                    "deep rapid breathing, or intense thirst with confusion. Call 103 "
                    "immediately."
                ),
            }
        ],
    },
    {
        "slug": "hypertension_self_care",
        "title": {
            "uz": "Gipertoniya: kundalik kuzatuv",
            "ru": "Гипертония: ежедневное наблюдение",
            "en": "Hypertension: daily monitoring",
        },
        "specialty": "cardiologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "measurement",
                "tags": [
                    "bosim",
                    "o'lchash",
                    "tonometr",
                    "давление",
                    "измерение",
                    "тонометр",
                    "blood pressure",
                    "measure",
                ],
                "uz": (
                    "Qon bosimini o'lchashdan 30 daqiqa oldin qahva, choy va chekishdan "
                    "saqlaning. 5 daqiqa tinch o'tiring, orqangizni suyang, oyoqlarni "
                    "chalishtirmang, manjetni yurak sathida yelkaga taqing. Ikki marta "
                    "o'lchab, o'rtacha qiymatni ilovaga kiriting."
                ),
                "ru": (
                    "За 30 минут до измерения давления не пейте кофе и чай, не курите. "
                    "Посидите спокойно 5 минут, обопритесь на спинку, не скрещивайте ноги, "
                    "манжету наденьте на плечо на уровне сердца. Измерьте дважды и внесите "
                    "среднее значение в приложение."
                ),
                "en": (
                    "Avoid coffee, tea, and smoking for 30 minutes before measuring. Sit "
                    "quietly for 5 minutes with your back supported and legs uncrossed, and "
                    "place the cuff on your upper arm at heart level. Measure twice and enter "
                    "the average in the app."
                ),
            },
            {
                "key": "targets",
                "tags": ["norma", "maqsad", "норма", "цель", "target"],
                "uz": (
                    "Ko'pchilik kattalar uchun uy sharoitidagi odatiy maqsad — 135/85 mmHg "
                    "dan past. Sizning maqsadli qiymatingizni shifokoringiz belgilaydi. "
                    "Bosim bir necha kun ketma-ket maqsaddan yuqori bo'lsa, shifokoringizga "
                    "xabar bering — dozani o'zingiz o'zgartirmang."
                ),
                "ru": (
                    "Для большинства взрослых обычная домашняя цель — ниже 135/85 мм рт. ст. "
                    "Ваш целевой уровень определяет врач. Если давление несколько дней "
                    "подряд выше цели, сообщите врачу — не меняйте дозу самостоятельно."
                ),
                "en": (
                    "For most adults the usual home target is below 135/85 mmHg. Your own "
                    "target is set by your doctor. If your pressure stays above target for "
                    "several days, tell your doctor — never change your dose yourself."
                ),
            },
            {
                "key": "lifestyle",
                "tags": ["tuz", "sport", "соль", "спорт", "salt", "exercise"],
                "uz": (
                    "Kunlik tuz miqdorini kamaytiring (taxminan choy qoshig'ining yarmi), "
                    "tayyor va konservalangan mahsulotlarni cheklang, muntazam piyoda yuring, "
                    "chekishni tashlang va alkogoldan voz keching. Uyqu 7-8 soat bo'lsin."
                ),
                "ru": (
                    "Уменьшите потребление соли (примерно половина чайной ложки в день), "
                    "ограничьте готовые и консервированные продукты, регулярно ходите "
                    "пешком, откажитесь от курения и алкоголя. Сон — 7–8 часов."
                ),
                "en": (
                    "Cut down on salt (about half a teaspoon a day), limit processed and "
                    "canned food, walk regularly, and stop smoking and alcohol. Aim for 7–8 "
                    "hours of sleep."
                ),
            },
        ],
    },
    {
        "slug": "cardiac_red_flags",
        "title": {
            "uz": "Yurak: xavfli belgilar",
            "ru": "Сердце: тревожные признаки",
            "en": "Cardiac red flags",
        },
        "specialty": "cardiologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "red_flags",
                "tags": [
                    "ko'krak og'rig'i",
                    "insult",
                    "боль в груди",
                    "инсульт",
                    "chest pain",
                    "stroke",
                ],
                "uz": (
                    "Darhol 103: ko'krak qafasidagi bosuvchi og'riq (ayniqsa qo'l, jag' yoki "
                    "kuraklarga tarqalsa), sovuq ter bilan birga nafas qisishi, hushdan "
                    "ketish, nutqning buzilishi yoki tananing bir tomoni holsizlanishi, "
                    "yuqori bosim (180/120 dan yuqori) bilan birga bosh og'rig'i va ko'rish "
                    "buzilishi."
                ),
                "ru": (
                    "Немедленно 103: давящая боль в груди (особенно с отдачей в руку, "
                    "челюсть или между лопаток), одышка с холодным потом, потеря сознания, "
                    "нарушение речи или слабость одной стороны тела, очень высокое давление "
                    "(выше 180/120) с головной болью и нарушением зрения."
                ),
                "en": (
                    "Call 103 immediately for: pressing chest pain (especially spreading to "
                    "the arm, jaw, or between the shoulder blades), breathlessness with cold "
                    "sweat, fainting, slurred speech or one-sided weakness, or very high "
                    "pressure (above 180/120) with headache and vision changes."
                ),
            }
        ],
    },
    {
        "slug": "asthma_self_care",
        "title": {
            "uz": "Astma: kundalik nazorat",
            "ru": "Астма: ежедневный контроль",
            "en": "Asthma: daily control",
        },
        "specialty": "pulmonologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "peak_flow",
                "tags": ["pef", "cho'qqi oqim", "пикфлоу", "peak flow"],
                "uz": (
                    "Cho'qqi oqimni (PEF) har kuni bir xil vaqtda, dori qabul qilishdan "
                    "oldin o'lchang. Tik turing, chuqur nafas oling va imkon qadar kuchli "
                    "puflang; uch marta takrorlab, eng yaxshi natijani ilovaga kiriting."
                ),
                "ru": (
                    "Измеряйте пиковую скорость выдоха (PEF) каждый день в одно и то же "
                    "время, до приёма препаратов. Встаньте прямо, глубоко вдохните и выдохните "
                    "как можно сильнее; повторите три раза и внесите лучший результат."
                ),
                "en": (
                    "Measure peak flow (PEF) at the same time each day, before taking your "
                    "medication. Stand up straight, breathe in deeply, and blow out as hard "
                    "as you can; repeat three times and enter the best result."
                ),
            },
            {
                "key": "triggers",
                "tags": ["trigger", "chang", "allergiya", "пыль", "аллергия", "dust"],
                "uz": (
                    "Keng tarqalgan qo'zg'atuvchilar: uy changi, tamaki tutuni, sovuq havo, "
                    "kuchli hid, gullar changi, mushuk-it juni, o'tkir jismoniy yuklama. "
                    "Ularni imkon qadar cheklang va qaysi holatda xuruj boshlanganini "
                    "ilovada qayd eting."
                ),
                "ru": (
                    "Частые триггеры: домашняя пыль, табачный дым, холодный воздух, резкие "
                    "запахи, пыльца, шерсть животных, резкая физическая нагрузка. По "
                    "возможности избегайте их и отмечайте в приложении, после чего начался "
                    "приступ."
                ),
                "en": (
                    "Common triggers: house dust, tobacco smoke, cold air, strong smells, "
                    "pollen, pet dander, and sudden exertion. Avoid them where you can, and "
                    "record in the app what preceded an attack."
                ),
            },
        ],
    },
    {
        "slug": "respiratory_red_flags",
        "title": {
            "uz": "Nafas olish: xavfli belgilar",
            "ru": "Дыхание: тревожные признаки",
            "en": "Respiratory red flags",
        },
        "specialty": "pulmonologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "red_flags",
                "tags": ["nafas", "ko'karish", "одышка", "синеет", "breathless"],
                "uz": (
                    "Darhol 103: gapirishga qiynaladigan darajada nafas qisishi, lab yoki "
                    "barmoqlarning ko'karishi, ingalyator yordam bermayotgani, SpO₂ 92% dan "
                    "past, hushning xiralashuvi."
                ),
                "ru": (
                    "Немедленно 103: одышка, при которой трудно говорить, посинение губ или "
                    "пальцев, ингалятор не помогает, SpO₂ ниже 92%, спутанность сознания."
                ),
                "en": (
                    "Call 103 immediately: breathlessness that makes speaking difficult, blue "
                    "lips or fingers, an inhaler that is not helping, SpO₂ below 92%, or "
                    "confusion."
                ),
            }
        ],
    },
    {
        "slug": "ckd_self_care",
        "title": {
            "uz": "Buyrak kasalligi: kundalik kuzatuv",
            "ru": "Болезнь почек: ежедневное наблюдение",
            "en": "Kidney disease: daily monitoring",
        },
        "specialty": "nephrologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "fluid_salt",
                "tags": ["suyuqlik", "shish", "tuz", "жидкость", "отёки", "соль", "swelling"],
                "uz": (
                    "Har kuni ertalab hojatxonadan keyin, nonushtadan oldin bir xil kiyimda "
                    "tarozida o'lchaning — kunlik vazn o'zgarishi suyuqlik to'planishini "
                    "ko'rsatadi. Tuzni cheklang. Uch kun ichida 2 kg dan ortiq vazn "
                    "qo'shilishi yoki oyoq/ yuz shishishi kuchayishi — shifokoringizga xabar "
                    "berish sababi."
                ),
                "ru": (
                    "Взвешивайтесь каждое утро после туалета, до завтрака, в одинаковой "
                    "одежде — суточные изменения веса отражают задержку жидкости. "
                    "Ограничьте соль. Прибавка более 2 кг за три дня или усиление отёков "
                    "ног и лица — повод сообщить врачу."
                ),
                "en": (
                    "Weigh yourself each morning after the toilet, before breakfast, in "
                    "similar clothing — daily weight change reflects fluid retention. Limit "
                    "salt. Gaining more than 2 kg in three days, or worsening swelling of "
                    "the legs or face, is a reason to tell your doctor."
                ),
            }
        ],
    },
    {
        "slug": "thyroid_self_care",
        "title": {
            "uz": "Qalqonsimon bez: dori tartibi",
            "ru": "Щитовидная железа: приём препаратов",
            "en": "Thyroid: medication routine",
        },
        "specialty": "endocrinologist",
        "source": "Hamroh clinical board",
        "chunks": [
            {
                "key": "routine",
                "tags": ["levotiroksin", "ertalab", "левотироксин", "утром", "levothyroxine"],
                "uz": (
                    "Qalqonsimon bez dorilari odatda ertalab nahorda, kamida 30 daqiqa "
                    "ovqatdan oldin, bir stakan suv bilan qabul qilinadi. Temir, kalsiy va "
                    "antatsidlar bilan birga ichmang — kamida 4 soat oraliq bo'lsin. "
                    "Doza va qabul vaqtini faqat shifokoringiz o'zgartiradi."
                ),
                "ru": (
                    "Препараты щитовидной железы обычно принимают утром натощак, не менее "
                    "чем за 30 минут до еды, запивая водой. Не принимайте одновременно с "
                    "железом, кальцием и антацидами — интервал не менее 4 часов. Дозу и "
                    "время приёма меняет только врач."
                ),
                "en": (
                    "Thyroid medication is usually taken in the morning on an empty stomach, "
                    "at least 30 minutes before food, with water. Do not take it together "
                    "with iron, calcium, or antacids — leave at least 4 hours between them. "
                    "Only your doctor changes the dose or timing."
                ),
            }
        ],
    },
]
