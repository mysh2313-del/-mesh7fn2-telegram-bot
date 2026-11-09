import os
import re
import uuid
import math
import asyncio
import requests

from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_KEY = os.environ["ALPACA_API_KEY"]
SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]

DATA_URL = "https://data.alpaca.markets/v1beta1/options/snapshots"
PAPER_URL = "https://paper-api.alpaca.markets/v2"

BUDGET_USD = 26.67
USD_SAR = 3.75
WATCHLIST = ["TSLA", "NVDA"]

HEADERS = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": SECRET_KEY
}

JSON_HEADERS = {
    **HEADERS,
    "Content-Type": "application/json"
}

SCAN_CACHE = {}
PENDING = {}


def paper_get(path, params=None):
    response = requests.get(
        PAPER_URL + path,
        headers=HEADERS,
        params=params,
        timeout=20
    )
    response.raise_for_status()
    return response.json()


def get_options(symbol):
    found = []

    today = datetime.now(timezone.utc).date()
    token = None

    for _ in range(10):

        params = {
            "feed": "indicative",
            "limit": 1000,
            "expiration_date_gte": str(today + timedelta(days=1)),
            "expiration_date_lte": str(today + timedelta(days=30))
        }

        if token:
            params["page_token"] = token

        response = requests.get(
            DATA_URL + "/" + symbol,
            headers=HEADERS,
            params=params,
            timeout=25
        )

        response.raise_for_status()
        data = response.json()

        for contract, snap in data.get("snapshots", {}).items():

            match = re.fullmatch(
                r"[A-Z0-9]+(\d{6})([CP])(\d{8})",
                contract
            )

            if not match:
                continue

            quote = snap.get("latestQuote") or {}

            try:
                bid = float(quote.get("bp") or 0)
                ask = float(quote.get("ap") or 0)

                stamp = datetime.fromisoformat(
                    quote["t"].replace("Z", "+00:00")
                )

            except (TypeError, ValueError, KeyError):
                continue

            if bid <= 0 or ask < bid or ask <= 0:
                continue

            age = (
                datetime.now(timezone.utc) - stamp
            ).total_seconds() / 60

            spread = (
                (ask - bid) / ((ask + bid) / 2)
            ) * 100

            if age < -1 or age > 5:
                continue

            if spread > 25 or ask * 100 > BUDGET_USD:
                continue

            found.append({
                "symbol": symbol,
                "contract": contract,
                "kind": "CALL" if match.group(2) == "C" else "PUT",
                "strike": int(match.group(3)) / 1000,
                "expiry": match.group(1),
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "age": age
            })

        token = data.get("next_page_token")

        if not token:
            break

    return found


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "بوت الخيارات التجريبي متصل.\n"
        "لا يستخدم أموالاً حقيقية.\n\n"

        "/status - حالة الحساب\n"
        "/scan - فحص الأسهم\n"
        "/buy CONTRACT - معاينة شراء\n"
        "/confirm - تأكيد الأمر التجريبي\n"
        "/cancel - إلغاء المعاينة\n"
        "/orders - آخر الأوامر\n"
        "/positions - المراكز المفتوحة"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        account = await asyncio.to_thread(
            paper_get,
            "/account"
        )

        await update.message.reply_text(
            "اتصال Paper Trading ناجح.\n"
            f"الحالة: {account.get('status')}\n"
            f"القوة الشرائية: ${float(account.get('buying_power', 0)):.2f}\n"
            "التنفيذ محصور بالحساب التجريبي."
        )

    except Exception as error:

        print("STATUS ERROR:", repr(error))

        await update.message.reply_text(
            "تعذر الاتصال بحساب Paper Trading."
        )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat = update.effective_chat.id

    message = await update.message.reply_text(
        "جارٍ فحص العقود..."
    )

    try:

        all_items = []

        for symbol in WATCHLIST:

            results = await asyncio.to_thread(
                get_options,
                symbol
            )

            all_items.extend(results)

        all_items.sort(
            key=lambda x: (x["spread"], x["age"])
        )

        SCAN_CACHE[chat] = {
            x["contract"]: x for x in all_items[:20]
        }

        if not all_items:

            await message.edit_text(
                "لا توجد عقود مناسبة حالياً ضمن الميزانية."
            )

            return

        lines = [
            "نتائج الفحص - أسعار إرشادية وليست تنفيذية.",
            ""
        ]

        for item in all_items[:5]:

            cost = item["ask"] * 100

            lines.append(
                f"{item['symbol']} {item['kind']}\n"
                f"العقد: {item['contract']}\n"
                f"Strike: {item['strike']:.2f}\n"
                f"Bid: ${item['bid']:.2f}\n"
                f"Ask: ${item['ask']:.2f}\n"
                f"التكلفة التقديرية: {cost * USD_SAR:.2f} ريال\n"
                f"Spread: {item['spread']:.1f}%\n"
                "----------------"
            )

        lines.append(
            "للمعاينة استخدم /buy متبوعاً برمز العقد."
        )

        await message.edit_text(
            "\n".join(lines)
        )

    except Exception as error:

        print("SCAN ERROR:", repr(error))

        await message.edit_text(
            "فشل الفحص. راجع Railway Logs."
        )


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat = update.effective_chat.id

    if not context.args:

        await update.message.reply_text(
            "اكتب /buy ثم رمز العقد من آخر فحص."
        )

        return

    symbol = context.args[0].upper()

    item = SCAN_CACHE.get(chat, {}).get(symbol)

    if not item:

        await update.message.reply_text(
            "العقد غير موجود في آخر فحص. نفّذ /scan أولاً."
        )

        return

    try:

        contract = await asyncio.to_thread(
            paper_get,
            "/options/contracts/" + symbol
        )

        if (
            contract.get("status") != "active"
            or not contract.get("tradable")
        ):

            await update.message.reply_text(
                "العقد غير نشط أو غير قابل للتداول."
            )

            return

        limit_price = math.ceil(
            item["ask"] * 100 - 1e-9
        ) / 100

        cost = limit_price * 100

        if cost > BUDGET_USD:

            await update.message.reply_text(
                "قيمة العقد تتجاوز سقف 100 ريال."
            )

            return

        account = await asyncio.to_thread(
            paper_get,
            "/account"
        )

        if (
            account.get("status") != "ACTIVE"
            or float(account.get("buying_power", 0)) < cost
        ):

            await update.message.reply_text(
                "الحساب غير نشط أو القوة الشرائية غير كافية."
            )

            return

        PENDING[chat] = {
            "symbol": symbol,
            "qty": "1",
            "side": "buy",
            "type": "limit",
            "time_in_force": "day",
            "limit_price": f"{limit_price:.2f}",
            "client_order_id": "tgpaper-" + uuid.uuid4().hex[:20]
        }

        await update.message.reply_text(
            "معاينة أمر تجريبي - لم يرسل بعد.\n\n"
            f"العقد: {symbol}\n"
            "شراء عقد واحد\n"
            f"سعر الحد: ${limit_price:.2f}\n"
            f"القيمة: {cost * USD_SAR:.2f} ريال\n\n"
            "أرسل /confirm للتأكيد التجريبي.\n"
            "أرسل /cancel للإلغاء."
        )

    except Exception as error:

        print("BUY ERROR:", repr(error))

        await update.message.reply_text(
            "تعذر التحقق من العقد أو الحساب."
        )


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat = update.effective_chat.id

    order = PENDING.get(chat)

    if not order:

        await update.message.reply_text(
            "لا توجد معاينة معلقة."
        )

        return

    try:

        account = await asyncio.to_thread(
            paper_get,
            "/account"
        )

        if account.get("status") != "ACTIVE":

            await update.message.reply_text(
                "حساب Paper Trading غير نشط."
            )

            return

        response = requests.post(
            PAPER_URL + "/orders",
            headers=JSON_HEADERS,
            json=order,
            timeout=25
        )

        if not response.ok:

            print(
                "ORDER ERROR:",
                response.status_code,
                response.text[:1000]
            )

            await update.message.reply_text(
                f"رفض Alpaca الأمر التجريبي: HTTP {response.status_code}"
            )

            return

        result = response.json()

        PENDING.pop(chat, None)

        await update.message.reply_text(
            "تم إرسال الأمر إلى Paper Trading فقط.\n\n"
            f"العقد: {result.get('symbol')}\n"
            f"الحالة: {result.get('status')}\n"
            f"الكمية: {result.get('qty')}\n"
            f"سعر الحد: ${result.get('limit_price')}\n"
            f"رقم الأمر: {result.get('id')}"
        )

    except Exception as error:

        print("CONFIRM ERROR:", repr(error))

        await update.message.reply_text(
            "تعذر تأكيد نتيجة الإرسال. افحص /orders قبل إعادة المحاولة."
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    PENDING.pop(
        update.effective_chat.id,
        None
    )

    await update.message.reply_text(
        "ألغيت المعاينة. لم يرسل أي أمر."
    )


async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        data = await asyncio.to_thread(
            paper_get,
            "/orders",
            {
                "status": "all",
                "limit": 10,
                "direction": "desc"
            }
        )

        if not data:

            await update.message.reply_text(
                "لا توجد أوامر تجريبية."
            )

            return

        lines = ["آخر الأوامر التجريبية:"]

        for order in data:

            lines.append(
                f"{order.get('symbol')} | {order.get('side')}\n"
                f"الحالة: {order.get('status')}\n"
                f"الكمية: {order.get('qty')}"
            )

        await update.message.reply_text(
            "\n\n".join(lines)
        )

    except Exception as error:

        print("ORDERS ERROR:", repr(error))

        await update.message.reply_text(
            "تعذر جلب الأوامر."
        )


async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):

    try:

        data = await asyncio.to_thread(
            paper_get,
            "/positions"
        )

        if not data:

            await update.message.reply_text(
                "لا توجد مراكز تجريبية مفتوحة."
            )

            return

        lines = ["المراكز التجريبية:"]

        for position in data[:15]:

            lines.append(
                f"{position.get('symbol')}\n"
                f"الكمية: {position.get('qty')}\n"
                f"متوسط الدخول: ${position.get('avg_entry_price')}\n"
                f"الربح/الخسارة: ${position.get('unrealized_pl')}"
            )

        await update.message.reply_text(
            "\n\n".join(lines)
        )

    except Exception as error:

        print("POSITIONS ERROR:", repr(error))

        await update.message.reply_text(
            "تعذر جلب المراكز."
        )


def main():

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("confirm", confirm))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("orders", orders))
    app.add_handler(CommandHandler("positions", positions))

    print("Paper-only bot started")

    app.run_polling()


if __name__ == "__main__":
    main()
