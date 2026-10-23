"""Mijozga boradigan tayyor xabarlar — 3 tilda: o'zbek lotin, o'zbek kirill, rus.
Til har xabarda mijoz yozgan matndan aniqlanadi (detect_lang)."""
import re

LANGS = ("uz_latn", "uz_cyrl", "ru")
LANG_NAMES = {"uz_latn": "o'zbek tili, LOTIN yozuvi", "uz_cyrl": "o'zbek tili, KIRILL yozuvi (ўзбекча кирилл)",
              "ru": "rus tili"}

_UZ_CYRL_LETTERS = set("ўқғҳЎҚҒҲ")
_RU_ONLY_LETTERS = set("ыщЫЩ")
_UZ_CYRL_WORDS = {"ассалому", "алайкум", "алейкум", "салом", "рахмат", "раҳмат", "сотаман", "сотилади", "сотмоқчи",
                  "нархи", "керак", "бор", "йук", "йўқ", "ха", "ҳа", "яхши", "эълон", "элон", "уй", "мен", "сиз",
                  "қанча", "канча", "булади", "бўлади", "болди", "бўлди", "тўладим", "туладим", "ака", "опа", "майли"}
_RU_WORDS = {"здравствуйте", "привет", "добрый", "день", "спасибо", "продаю", "продам", "цена", "это", "есть",
             "да", "нет", "хочу", "объявление", "сколько", "как", "что", "можно", "оплатил", "оплатила",
             "пожалуйста", "я", "не", "и", "в", "на", "состояние", "район", "хорошо", "понял", "поняла",
             "понятно", "ладно", "давай", "давайте", "сейчас", "отправил", "отправила", "всё", "все", "где", "когда",
             "почему", "но", "у", "меня", "вас", "вы", "мы", "мне", "ещё", "еще", "уже", "тоже", "очень", "только",
             "здрасте", "салам", "добрый", "вечер", "утро", "ок", "окей", "продаётся", "продается", "срочно"}


def detect_lang(text: str, prev: str | None = None) -> str:
    """Matndan til/yozuvni aniqlaydi. Aniq bo'lmasa (raqam, emoji, 1-2 harf) — oldingisini qoldiradi."""
    prev = prev if prev in LANGS else "uz_latn"
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 2:
        return prev
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in letters if c.isascii())
    if lat >= cyr:
        return "uz_latn"
    if any(c in _UZ_CYRL_LETTERS for c in text):
        return "uz_cyrl"
    words = set(re.findall(r"[а-яёўқғҳ]+", text.lower()))
    uz, ru = len(words & _UZ_CYRL_WORDS), len(words & _RU_WORDS)
    if any(c in _RU_ONLY_LETTERS for c in text):
        ru += 2
    if "ь" in text.lower():  # o'zbek kirillida juda kam uchraydi
        ru += 1
    if uz > ru:
        return "uz_cyrl"
    if ru > uz:
        return "ru"
    return prev if prev in ("uz_cyrl", "ru") else "uz_cyrl"


T = {
    "preview_ask": {
        "uz_latn": "Kanalda shunaqa chiqadi. Hammasi to'g'rimi? To'g'ri bo'lsa «ha» deb yozing, to'g'irlash kerak bo'lsa ayting\n\nE'lon narxi {price} so'm",
        "uz_cyrl": "Каналда шунақа чиқади. Ҳаммаси тўғрими? Тўғри бўлса «ҳа» деб ёзинг, тўғирлаш керак бўлса айтинг\n\nЭълон нархи {price} сўм",
        "ru": "Вот так объявление будет выглядеть в канале. Всё верно? Если да — напишите «да», если нужно что-то исправить — скажите\n\nСтоимость объявления {price} сум",
    },
    "pay_amount": {
        "uz_latn": "Unda to'lovni qilib qo'ying: {amount} so'm.",
        "uz_cyrl": "Унда тўловни қилиб қўйинг: {amount} сўм.",
        "ru": "Тогда оплатите, пожалуйста: {amount} сум.",
    },
    "pay_exact": {
        "uz_latn": " Aynan shu summani tashlang, so'migacha, shunda to'lovingiz avtomatik taniladi.",
        "uz_cyrl": " Айнан шу суммани ташланг, сўмигача, шунда тўловингиз автоматик танилади.",
        "ru": " Переведите именно эту сумму, до сума — так оплата определится автоматически.",
    },
    "pay_link": {
        "uz_latn": "Payme orqali: {link}\n\nAgar silka ochilmasa, Payme ilovasiga kirib qidiruvga «{payme}» deb yozing, o'sha yerdan to'lasangiz ham bo'ladi",
        "uz_cyrl": "Payme орқали: {link}\n\nАгар силка очилмаса, Payme иловасига кириб қидирувга «{payme}» деб ёзинг, ўша ердан тўласангиз ҳам бўлади",
        "ru": "Через Payme: {link}\n\nЕсли ссылка не открывается, зайдите в приложение Payme и введите в поиске «{payme}» — можно оплатить оттуда",
    },
    "pay_nolink": {
        "uz_latn": "Payme ilovasiga kirib qidiruvga «{payme}» deb yozing va o'sha yerdan to'lang",
        "uz_cyrl": "Payme иловасига кириб қидирувга «{payme}» деб ёзинг ва ўша ердан тўланг",
        "ru": "Зайдите в приложение Payme, введите в поиске «{payme}» и оплатите оттуда",
    },
    "pay_click": {
        "uz_latn": "Click'dan ham bo'ladi: Click ilovasida «{click}» deb qidiring, shu summani tashlang. Faqat Click'dan to'lasangiz, chekining skrinshotini albatta shu yerga yuboring, cheksiz tasdiqlay olmayman",
        "uz_cyrl": "Click'дан ҳам бўлади: Click иловасида «{click}» деб қидиринг, шу суммани ташланг. Фақат Click'дан тўласангиз, чекининг скриншотини албатта шу ерга юборинг, чексиз тасдиқлай олмайман",
        "ru": "Можно и через Click: в приложении Click найдите «{click}» и переведите эту сумму. Только если платите через Click, обязательно пришлите сюда скриншот чека — без чека подтвердить не смогу",
    },
    "pay_click_auto": {
        "uz_latn": "Click'dan ham bo'ladi: Click ilovasida «{click}» deb qidiring va aynan shu summani tashlang",
        "uz_cyrl": "Click'дан ҳам бўлади: Click иловасида «{click}» деб қидиринг ва айнан шу суммани ташланг",
        "ru": "Можно и через Click: в приложении Click найдите «{click}» и переведите именно эту сумму",
    },
    "pay_click_link": {
        "uz_latn": "Click orqali: {link}\n\nAgar silka ochilmasa, Click ilovasida «{click}» deb qidiring va aynan shu summani tashlang",
        "uz_cyrl": "Click орқали: {link}\n\nАгар силка очилмаса, Click иловасида «{click}» деб қидиринг ва айнан шу суммани ташланг",
        "ru": "Через Click: {link}\n\nЕсли ссылка не открывается, найдите в приложении Click «{click}» и переведите именно эту сумму",
    },
    "pay_click_link_receipt": {
        "uz_latn": "Click orqali: {link}\n\nAgar silka ochilmasa, Click ilovasida «{click}» deb qidiring. Click'dan to'lasangiz, chekining skrinshotini albatta shu yerga yuboring, cheksiz tasdiqlay olmayman",
        "uz_cyrl": "Click орқали: {link}\n\nАгар силка очилмаса, Click иловасида «{click}» деб қидиринг. Click'дан тўласангиз, чекининг скриншотини албатта шу ерга юборинг, чексиз тасдиқлай олмайман",
        "ru": "Через Click: {link}\n\nЕсли ссылка не открывается, найдите в приложении Click «{click}». Если платите через Click, обязательно пришлите сюда скриншот чека — без чека подтвердить не смогу",
    },
    "btn_click": {"uz_latn": "🔵 Click orqali to'lash", "uz_cyrl": "🔵 Click орқали тўлаш", "ru": "🔵 Оплатить через Click"},
    # --- Bitta qisqa to'lov xabari ---
    "pay_head": {
        "uz_latn": "To'lov: {amount} so'm — aynan shu summani to'lang",
        "uz_cyrl": "Тўлов: {amount} сўм — айнан шу суммани тўланг",
        "ru": "Оплата: {amount} сум — переведите именно эту сумму",
    },
    "pay_search": {
        "uz_latn": "Silka ochilmasa, ilovada qidiring: {names}",
        "uz_cyrl": "Силка очилмаса, иловада қидиринг: {names}",
        "ru": "Если ссылка не открывается, найдите в приложении: {names}",
    },
    "pay_foot": {
        "uz_latn": "To'lov tushishi bilan e'loningiz kanalga chiqadi.",
        "uz_cyrl": "Тўлов тушиши билан эълонингиз каналга чиқади.",
        "ru": "Как только оплата поступит, объявление выйдет в канале.",
    },
    "pay_foot_click_receipt": {
        "uz_latn": "To'lov tushishi bilan e'loningiz kanalga chiqadi. Click'dan to'lasangiz, chek skrinshotini shu yerga tashlang.",
        "uz_cyrl": "Тўлов тушиши билан эълонингиз каналга чиқади. Click'дан тўласангиз, чек скриншотини шу ерга ташланг.",
        "ru": "Как только оплата поступит, объявление выйдет. Если платите через Click, пришлите сюда скриншот чека.",
    },
    "pay_after": {
        "uz_latn": "To'lov tushishi bilan e'loningizni kanalga chiqarib yuboraman. Agar 10 daqiqada chiqmasa, to'lov chekining skrinshotini shu yerga tashlab qo'ying",
        "uz_cyrl": "Тўлов тушиши билан эълонингизни каналга чиқариб юбораман. Агар 10 дақиқада чиқмаса, тўлов чекининг скриншотини шу ерга ташлаб қўйинг",
        "ru": "Как только оплата поступит, сразу опубликую объявление в канале. Если через 10 минут не появится — пришлите сюда скриншот чека",
    },
    "btn_pay": {"uz_latn": "💳 Payme orqali to'lash", "uz_cyrl": "💳 Payme орқали тўлаш", "ru": "💳 Оплатить через Payme"},
    "btn_cancel": {"uz_latn": "❌ E'lonni bekor qilish", "uz_cyrl": "❌ Эълонни бекор қилиш", "ru": "❌ Отменить объявление"},
    "receipt_got": {
        "uz_latn": "Chekni oldim, tekshirib e'loningizni chiqarib yuboraman 👍",
        "uz_cyrl": "Чекни олдим, текшириб эълонингизни чиқариб юбораман 👍",
        "ru": "Чек получил, проверю и опубликую объявление 👍",
    },
    "receipt_bad": {
        "uz_latn": "Bu rasm to'lov chekiga o'xshamadi. To'lov qilgan bo'lsangiz, Payme yoki Click'dagi chekning skrinshotini tashlang",
        "uz_cyrl": "Бу расм тўлов чекига ўхшамади. Тўлов қилган бўлсангиз, Payme ёки Click'даги чекнинг скриншотини ташланг",
        "ru": "Это не похоже на чек об оплате. Если вы оплатили, пришлите скриншот чека из Payme или Click",
    },
    "paid": {
        "uz_latn": "To'lov tushdi, rahmat! Hozir kanalga chiqaraman",
        "uz_cyrl": "Тўлов тушди, раҳмат! Ҳозир каналга чиқараман",
        "ru": "Оплата поступила, спасибо! Сейчас опубликую",
    },
    "published": {
        "uz_latn": "Tayyor, e'loningiz kanalda 👇\n{link}\n\nXaridor tez chiqsin! 🙂\n\nE'lon kanalda saqlanib qoladi. Sotsangiz yoki sotuvni to'xtatsangiz, shu yerga yozing — «sotildi» deb belgilab, raqamingizni olib tashlaymiz",
        "uz_cyrl": "Тайёр, эълонингиз каналда 👇\n{link}\n\nХаридор тез чиқсин! 🙂\n\nЭълон каналда сақланиб қолади. Сотсангиз ёки сотувни тўхтатсангиз, шу ерга ёзинг — «сотилди» деб белгилаб, рақамингизни олиб ташлаймиз",
        "ru": "Готово, ваше объявление в канале 👇\n{link}\n\nУдачной продажи! 🙂\n\nОбъявление остаётся в канале. Если продадите или передумаете — напишите сюда, отметим «продано» и уберём ваш номер",
    },
    "published_service": {
        "uz_latn": "Tayyor, e'loningiz kanalda 👇\n{link}\n\nMijozlaringiz ko'p bo'lsin! 🙂\n\nE'lon kanalda saqlanib qoladi. Xizmatni to'xtatsangiz, shu yerga yozing — «to'xtatildi» deb belgilab, raqamingizni olib tashlaymiz",
        "uz_cyrl": "Тайёр, эълонингиз каналда 👇\n{link}\n\nМижозларингиз кўп бўлсин! 🙂\n\nЭълон каналда сақланиб қолади. Хизматни тўхтатсангиз, шу ерга ёзинг — «тўхтатилди» деб белгилаб, рақамингизни олиб ташлаймиз",
        "ru": "Готово, ваше объявление в канале 👇\n{link}\n\nПобольше вам клиентов! 🙂\n\nОбъявление остаётся в канале. Если прекратите оказывать услугу — напишите сюда, отметим «остановлено» и уберём ваш номер",
    },
    "campaign_started": {
        "uz_latn": "Tarifingiz: {days} kun. E'loningiz har kuni 1 marta, har xil vaqtda chiqib turadi. Kun ora o'zim yozaman — rasm yoki videoni yangilab turamiz",
        "uz_cyrl": "Тарифингиз: {days} кун. Эълонингиз ҳар куни 1 марта, ҳар хил вақтда чиқиб туради. Кун ора ўзим ёзаман — расм ёки видеони янгилаб турамиз",
        "ru": "Ваш тариф: {days} дн. Объявление будет выходить раз в день в разное время. Через день я напишу — будем обновлять фото или видео",
    },
    "campaign_posted": {
        "uz_latn": "Bugungi reklamangiz chiqdi ({n}/{days}-kun) 👇\n{link}",
        "uz_cyrl": "Бугунги рекламангиз чиқди ({n}/{days}-кун) 👇\n{link}",
        "ru": "Сегодняшняя публикация вышла ({n}/{days}) 👇\n{link}",
    },
    "campaign_refresh": {
        "uz_latn": "Assalomu alaykum! Ertangi reklamani yangilaymizmi? Yangi rasm yoki video tashlang — shu bilan chiqaramiz. Tashlamasangiz, oldingisi bilan chiqaveradi",
        "uz_cyrl": "Ассалому алайкум! Эртанги рекламани янгилаймизми? Янги расм ёки видео ташланг — шу билан чиқарамиз. Ташламасангиз, олдингиси билан чиқаверади",
        "ru": "Здравствуйте! Обновим завтрашнюю публикацию? Пришлите новое фото или видео — выйдет с ним. Если не пришлёте, выйдет прежний вариант",
    },
    "campaign_done": {
        "uz_latn": "{days} kunlik tarifingiz tugadi — e'loningiz {days} kun davomida chiqdi. Davom ettiramizmi? Yozing 🙂",
        "uz_cyrl": "{days} кунлик тарифингиз тугади — эълонингиз {days} кун давомида чиқди. Давом эттирамизми? Ёзинг 🙂",
        "ru": "Ваш тариф на {days} дн. завершён — объявление выходило {days} дн. Продлим? Напишите 🙂",
    },
    "published_link": {
        "uz_latn": "E'loningizning aniq silkasi 👇\n{link}",
        "uz_cyrl": "Эълонингизнинг аниқ силкаси 👇\n{link}",
        "ru": "Точная ссылка на ваше объявление 👇\n{link}",
    },
    "publish_delay": {
        "uz_latn": "To'lov tushdi, lekin kanalga chiqarishda biroz kechikish bo'ldi. Tez orada chiqarib qo'yaman 🙏",
        "uz_cyrl": "Тўлов тушди, лекин каналга чиқаришда бироз кечикиш бўлди. Тез орада чиқариб қўяман 🙏",
        "ru": "Оплата поступила, но с публикацией небольшая задержка. Скоро опубликую 🙏",
    },
    "paid_wait": {
        "uz_latn": "To'lovingiz tushgan, e'lon chiqyapti 🙏",
        "uz_cyrl": "Тўловингиз тушган, эълон чиқяпти 🙏",
        "ru": "Оплата получена, объявление публикуется 🙏",
    },
    "expired": {
        "uz_latn": "#{id} e'lon uchun to'lov muddati tugadi ({amount} so'm). Agar to'lagan bo'lsangiz, chekini shu yerga tashlang. Yangi e'lon uchun yana yozing",
        "uz_cyrl": "#{id} эълон учун тўлов муддати тугади ({amount} сўм). Агар тўлаган бўлсангиз, чекини шу ерга ташланг. Янги эълон учун яна ёзинг",
        "ru": "Срок оплаты объявления #{id} истёк ({amount} сум). Если вы оплатили — пришлите сюда чек. Для нового объявления просто напишите",
    },
    "rejected": {
        "uz_latn": "Chekingizni tasdiqlay olmadik: {amount} so'm to'lov topilmadi. Summani tekshirib ko'ring yoki adminga yozing",
        "uz_cyrl": "Чекингизни тасдиқлай олмадик: {amount} сўм тўлов топилмади. Суммани текшириб кўринг ёки админга ёзинг",
        "ru": "Не удалось подтвердить чек: оплата {amount} сум не найдена. Проверьте сумму или напишите администратору",
    },
    "too_many_photos": {
        "uz_latn": "Ko'pi bilan {n} ta rasm yoki video bo'ladi",
        "uz_cyrl": "Кўпи билан {n} та расм ёки видео бўлади",
        "ru": "Можно максимум {n} фото или видео",
    },
    "other_media": {
        "uz_latn": "Ma'lumotni matn bilan yozing, rasm va videolarni esa fayl emas, oddiy rasm/video qilib tashlang 📸",
        "uz_cyrl": "Маълумотни матн билан ёзинг, расм ва видеоларни эса файл эмас, оддий расм/видео қилиб ташланг 📸",
        "ru": "Пишите информацию текстом, а фото и видео отправляйте не файлом, а обычным фото/видео 📸",
    },
    "ack": {
        "uz_latn": "Xo'p, tushundim 👍",
        "uz_cyrl": "Хўп, тушундим 👍",
        "ru": "Хорошо, понял 👍",
    },
    "tech_error": {
        "uz_latn": "Kechirasiz, hozir biroz uzilish bo'ldi. Bir daqiqadan keyin qayta yozing 🙏",
        "uz_cyrl": "Кечирасиз, ҳозир бироз узилиш бўлди. Бир дақиқадан кейин қайта ёзинг 🙏",
        "ru": "Извините, небольшой сбой. Напишите, пожалуйста, через минуту 🙏",
    },
}


def t(key: str, lang: str | None, **kw) -> str:
    variants = T[key]
    text = variants.get(lang or "uz_latn") or variants["uz_latn"]
    return text.format(**kw) if kw else text
