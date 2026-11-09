import os
import re
import requests
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]
API_KEY = os.environ["ALPACA_API_KEY"]
SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]

BASE_URL = "https://data.alpaca.markets/v1beta1/options/snapshots"
BUDGET_USD = 26.67
HEADERS = {
    "APCA-API-KEY-ID": API_KEY,
    "APCA-API-SECRET-KEY": SECRET_KEY
}


def get_options(symbol):
    results = []
    today = datetime.now(timezone.utc).date()

    params = {
        "feed": "indicative",
        "limit": 1000,
        "expiration_date_gte": str(today + timedelta(days=1)),
        "expiration_date_lte": str(today + timedelta(days=30))
    }

    page_token = None

    for _ in range(5):
        if page_token:
            params["page_token"] = page_token

        response = requests.get(
            f"{BASE_URL}/{symbol}",
            headers=HEADERS,
            params=params,
            timeout=25
        )
        response.raise_for_status()
        data = response.json()

        for contract, snapshot in data.get("snapshots", {}).items():
            match = re.match(
                r"^[A-Z]+(\d{6})([CP])(\d{8})$",
                contract
            )
            if not match:
                continue

            expiry = datetime.strptime(
                match.group(1), "%y%m%d"
            ).date()

            option_type = match.group(2)
            strike = int(match.group(3)) / 1000

            quote = snapshot.get("latestQuote", {})
            bid = quote.get("bp", 0)
            ask = quote.get("ap", 0)

            if not bid or not ask or bid <= 0 or ask <= 0:
                continue

            if ask < bid:
                continue

            cost = ask * 100
            spread = (ask - bid) / ask * 100

            if cost > BUDGET_USD or spread > 25:
                continue

            quote_time = quote.get("t")
            if not quote_time:
                continue

            timestamp = datetime.fromisoformat(
                quote_time.replace("Z", "+00:00")
            )

            age = (
                datetime.now(timezone.utc) - timestamp
            ).total_seconds() / 60

            if age > 15 or age < -1:
                continue

            trade = snapshot.get("latestTrade", {})

            results.append({
                "symbol": symbol,
                "contract": contract,
                "type": "CALL" if option_type == "C" else "PUT",
                "strike": strike,
                "expiry": expiry,
                "bid": bid,
                "ask": ask,
                "cost": cost,
                "spread": spread,
                "age": age,
                "volume": trade.get("s", "غير متوفر")
            })

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return results


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلًا بك في بوت متابعة الخيارات.\n\n"
        "الأسهم: TSLA وNVDA\n"
        "الميزانية: 100 ريال تقريبًا\n\n"
        "استخدم /scan لفحص العقود المتاحة."
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "حالة البوت: يعمل\n"
        "مصدر البيانات: Alpaca Indicative\n"
        "الميزانية: 100 ريال\n"
        "الأسهم: TSLA وNVDA"
    )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.message.reply_text(
        "جارٍ فحص بيانات الخيارات..."
    )

    try:
        all_results = []

        for symbol in ["TSLA", "NVDA"]:
            all_results.extend(get_options(symbol))

        all_results.sort(key=lambda x: x["spread"])

        if not all_results:
            await message.edit_text(
                "لا توجد عقود مناسبة ضمن الميزانية حاليًا، "
                "أو لم تتوفر بيانات حديثة وموثوقة."
            )
            return

        lines = [
            "نتائج فحص عقود الخيارات",
            "مصدر الأسعار: Indicative (إرشادية)",
            "الميزانية: 100 ريال تقريبًا",
            ""
        ]

        for item in all_results[:8]:
    entry = item["ask"]
    tp1 = entry * 1.20
    tp2 = entry * 1.40
    stop = entry * 0.80

    cost_sar = entry * 100 * 3.75
    profit1 = (tp1 - entry) * 100 * 3.75
    profit2 = (tp2 - entry) * 100 * 3.75
    loss = (entry - stop) * 100 * 3.75

    lines.append(
        f"السهم: {item['symbol']}\n"
        f"الاتجاه: {item['type']}\n"
        f"العقد: {item['contract']}\n"
        f"سعر التنفيذ: ${item['strike']:.2f}\n"
        f"الانتهاء: {item['expiry']}\n"
        f"الدخول: ${entry:.3f}\n"
        f"الهدف الأول: ${tp1:.3f}\n"
        f"الهدف الثاني: ${tp2:.3f}\n"
        f"وقف الخسارة: ${stop:.3f}\n"
        f"تكلفة العقد: {cost_sar:.2f} ريال\n"
        f"ربح الهدف الأول: {profit1:.2f} ريال\n"
        f"ربح الهدف الثاني: {profit2:.2f} ريال\n"
        f"الخسارة عند الوقف: {loss:.2f} ريال\n"
        f"Bid: ${item['bid']:.3f}\n"
        f"Ask: ${item['ask']:.3f}\n"
        f"فارق السعر: {item['spread']:.1f}%\n"
        "--------------------"
    )

        lines.append(
            "\nهذه قائمة فحص وليست توصية شراء أو بيع. "
            "الأسعار إرشادية وليست أسعار تنفيذ مؤكدة."
        )

        text = "\n".join(lines)

        await message.edit_text(text[:4000])

    except Exception as error:
        print("SCAN ERROR:", str(error))
        await message.edit_text(
            "تعذر جلب البيانات حاليًا. "
            "تحقق من صلاحية مفاتيح Alpaca والاشتراك."
        )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("scan", scan))

    print("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
