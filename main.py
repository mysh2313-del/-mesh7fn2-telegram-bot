import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ["BOT_TOKEN"]
TZ = ZoneInfo("Asia/Riyadh")
logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "تم ربطك ببوت متابعة الأوبشن التجريبي.\n"
        f"معرّف المحادثة: {chat_id}\n\n"
        "الأوامر:\n"
        "/status — حالة البوت\n"
        "/help — المساعدة\n\n"
        "تنبيه: لم يتم ربط مصدر أسعار الخيارات بعد؛ لذلك لن أصدر توصيات دخول أو أسعارًا غير موثوقة."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_text(
        f"البوت يعمل. توقيت الرياض: {now}\n"
        "المتابعة المطلوبة: TSLA وNVDA\n"
        "الميزانية المحددة: 100 ريال\n"
        "حالة بيانات الخيارات: غير مربوطة حتى الآن."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "هذا البوت مخصص لتنبيهات تعليمية عن CALL وPUT على TSLA وNVDA.\n"
        "لن يرسل إشارة إلا بعد ربط مصدر موثوق وحديث لسلسلة الخيارات. "
        "لا يرسل أوامر إلى دراية ولا ينفذ صفقات."
    )

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()
