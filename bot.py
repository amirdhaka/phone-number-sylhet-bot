import requests
import time
import csv
import os
import asyncio
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ================= KEEP ALIVE =================
app_web = Flask('')
@app_web.route('/')
def home(): return "Bot is running!"

def run(): app_web.run(host='0.0.0.0', port=10000)
def keep_alive(): Thread(target=run).start()

# ================= CONFIG =================
TOKEN = "8720872771:AAF1BSkDHA2KE_clSS8pqb9a0BzTsaPZHmg"
FILE_NAME = "data.csv"

search_context = {}
last_range = {}

# ================= FILE =================
def init_file():
    if not os.path.exists(FILE_NAME):
        with open(FILE_NAME, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Name","Roll","Board","Mobile","Date","TranID"])

def save_data(name, roll, board, mobile, date, tran_id):
    with open(FILE_NAME, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, roll, board, mobile, date, tran_id])

# ================= SCRAPER =================
def get_tran_ids(roll):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Search?searchStr={roll}"
    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.find("table")
        if not table: return []
        return [r.find_all("td")[1].text.strip() for r in table.find_all("tr")[1:]]
    except:
        return []

def get_full_data(tran_id):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Voucher/{tran_id}"
    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]

        def find(label):
            for i in range(len(lines)):
                if label in lines[i]:
                    return lines[i+1]
            return "N/A"

        name, roll, board, mobile, date = find("Name"), find("Roll"), find("Board"), find("Mobile"), find("Date")
        save_data(name, roll, board, mobile, date, tran_id)

        return f"<pre>\nName   : {name}\nRoll   : {roll}\nBoard  : {board}\nMobile : {mobile}\nDate   : {date}\nID     : {tran_id}\n</pre>", mobile
    except:
        return None, None

# ================= BUTTON =================
def stop_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Search", callback_data="stop_search")]])

def next_button(num):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"➡️ Next {num}", callback_data="next_range")]])

def get_contact_buttons(mobile):
    n = mobile.replace("+","").replace(" ","")
    if n.startswith("01"):
        n = "880"+n[1:]
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 WhatsApp", url=f"https://wa.me/{n}"),
            InlineKeyboardButton("✈️ Telegram", url=f"https://t.me/+{n}")
        ]
    ])

# ================= MAIN ENGINE =================
async def run_search_logic(message, context, start, end, run_id):
    user_id = message.chat_id

    status_msg = await message.reply_text("⏳ Starting...", reply_markup=stop_button())

    count = 0
    total = end - start + 1

    for i, roll in enumerate(range(start, end+1), 1):

        # 🔴 STOP CHECK
        if search_context.get(user_id, {}).get('run_id') != run_id:
            await message.reply_text("🛑 Stopped!")
            return

        tids = get_tran_ids(roll)

        for tid in tids:

            if search_context.get(user_id, {}).get('run_id') != run_id:
                await message.reply_text("🛑 Stopped!")
                return

            data, mobile = get_full_data(tid)

            if data:
                count += 1

                try:
                    await status_msg.delete()
                except:
                    pass

                await message.reply_text(
                    f"📄 Result {count}:\n{data}",
                    parse_mode="HTML",
                    reply_markup=get_contact_buttons(mobile)
                )

                status_msg = await message.reply_text(
                    f"📊 Progress: {i}/{total} (Roll: {roll})",
                    reply_markup=stop_button()
                )

        # 🔄 LIVE UPDATE (every roll)
        try:
            await status_msg.edit_text(
                f"⏳ Processing Roll: {roll}\n"
                f"✅ Progress: {i}/{total}\n"
                f"📊 Found: {count}",
                reply_markup=stop_button()
            )
        except:
            pass

        # ⏱️ DELAY (IMPORTANT)
        await asyncio.sleep(2)

    # ✅ FINISH
    if search_context.get(user_id, {}).get('run_id') == run_id:
        try:
            await status_msg.delete()
        except:
            pass

        await message.reply_text(f"✅ Done!\n📊 Total Found: {count}")
        await message.reply_text(f"👉 Next {total}?", reply_markup=next_button(total))

        search_context[user_id] = {'status': 'idle'}

# ================= HANDLERS =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    if text == "🚀 Start":
        await update.message.reply_text(
            "✅ Ready!",
            reply_markup=ReplyKeyboardMarkup(
                [["🚀 Start"],["📂 Search Database"],["📥 Download Data"]],
                resize_keyboard=True
            )
        )
        return

    run_id = time.time()
    search_context[user_id] = {'run_id': run_id, 'status': 'running'}

    if text.isdigit():
        last_range[user_id] = (int(text), int(text))
        await run_search_logic(update.message, context, int(text), int(text), run_id)

    elif "-" in text:
        try:
            s, e = map(int, text.split("-"))
            last_range[user_id] = (s, e)
            await run_search_logic(update.message, context, s, e, run_id)
        except:
            pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if query.data == "stop_search":
        search_context[user_id] = {'run_id': None, 'status': 'idle'}
        await query.answer("🛑 Stopped!")
        await query.message.reply_text("🛑 Search stopped.")

    elif query.data == "next_range":
        await query.answer()

        s, e = last_range.get(user_id, (0,0))
        diff = e - s + 1

        run_id = time.time()
        search_context[user_id] = {'run_id': run_id, 'status': 'running'}

        await run_search_logic(query.message, context, e+1, e+diff, run_id)

# ================= RUN =================
if __name__ == "__main__":
    init_file()
    keep_alive()

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("🤖 Bot Running Final Version...")
    app.run_polling()
