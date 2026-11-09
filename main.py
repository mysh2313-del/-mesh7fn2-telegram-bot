import os
import re
import asyncio
import requests
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
BOT_TOKEN = os.environ["BOT_TOKEN"]
API_KEY = os.environ["ALPACA_API_KEY"]
SECRET_KEY = os.environ["ALPACA_SECRET_KEY"]
BASE_URL = "https://data.alpaca.markets/v1beta1/options/snapshots"
BUDGET_USD = 26.67
USD_SAR = 3.75
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
    for _ in range(20):
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
            match = re.fullmatch(
                r"[A-Z0-9]+(\d{6})([CP])(\d{8})",
                contract
            )
            if not match:
                continue
            expiry = datetime.strptime(
                match.group(1), "%y%m%d"
            ).date()
            option_type = match.group(2)
            strike = int(match.group(3)) / 1000
            quote = snapshot.get("latestQuote") or {}
            bid = float(quote.get("bp") or 0)
            ask = float(quote.get("ap") or 0)
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            midpoint = (bid + ask) / 2
            spread = (
                (ask - bid) / midpoint * 100
                if midpoint else 999
            )
            cost = ask * 100
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
                "age": age
            })
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return results
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك في بوت متابعة الخيارات.\n\n"
        "الأسهم: TSLA وNVDA\n"
        "الميزانية: 100 ريال تقريباً\n\n"
        "الأوامر:\n"
        "/scan - فحص العقود\n"
        "/status - حالة البوت"
    )
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "البوت متصل.\n"
        "مصدر البيانات: Alpaca Indicative\n"
        "الأسهم: TSLA وNVDA\n"
        "الميزانية: 100 ريال"
    )
async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await update.message.reply_text(
        "جارٍ فحص بيانات الخيارات..."
    )
    try:
        all_results = []
        for symbol in ["TSLA", "NVDA"]:
            results = await asyncio.to_thread(
                get_options, symbol
            )
            all_results.extend(results)
        all_results.sort(
            key=lambda x: (x["spread"], x["age"])
        )
        if not all_results:
            await message.edit_text(
                "لا توجد عقود مناسبة حالياً ضمن الميزانية."
            )
            return
        lines = [
            "نتائج فحص عقود الخيارات",
            "الأسعار إرشادية وليست تنفيذية",
            "الميزانية: 100 ريال تقريباً",
            ""
        ]
        for item in all_results[:5]:
            entry = item["ask"]
            tp1 = entry * 1.20
            tp2 = entry * 1.40
            stop = entry * 0.80
            cost_sar = item["cost"] * USD_SAR
            lines.append(
                f"السهم: {item['symbol']}\n"
                f"الاتجاه: {item['type']}\n"
                f"العقد: {item['contract']}\n"
                f"سعر التنفيذ: ${item['strike']:.2f}\n"
                f"الانتهاء: {item['expiry']}\n"
                f"سعر الدخول الافتراضي: ${entry:.3f}\n"
                f"الهدف الأول: ${tp1:.3f}\n"
                f"الهدف الثاني: ${tp2:.3f}\n"
                f"وقف الخسارة: ${stop:.3f}\n"
                f"التكلفة: {cost_sar:.2f} ريال\n"
                f"Bid: ${item['bid']:.3f}\n"
                f"Ask: ${item['ask']:.3f}\n"
                f"Spread: {item['spread']:.1f}%\n"
                f"عمر السعر: {item['age']:.1f} دقيقة\n"
                "--------------------"
            )
        lines.append(
            "\nالأهداف حسابية افتراضية وليست توصيات أو توقعات."
        )
        await message.edit_text(
            "\n".join(lines)
        )
    except Exception as error:
        print("SCAN ERROR:", repr(error))
        await message.edit_text(
            "حدث خطأ أثناء الفحص. "
            "راجع سجلات Railway."
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
