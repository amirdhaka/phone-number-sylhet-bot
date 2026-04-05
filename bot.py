import asyncio
import requests
import time
import csv
import os
from bs4 import BeautifulSoup
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ================= KEEP ALIVE =================
app_web = Flask('')
@app_web.route('/')
def home(): return "Bot is running!"

def run(): app_web.run(host='0.0.0.0', port=10000)
def keep_alive(): Thread(target=run).start()

# ================= CONFIGURATION =================
TOKEN = "8720872771:AAF1BSkDHA2KE_clSS8pqb9a0BzTsaPZHmg" 
FILE_NAME = "data.csv"

# ইউজার অনুযায়ী সার্চ স্টেট রাখার জন্য
user_tasks = {} # {user_id: bool_is_running}
last_range = {}

def init_file():
    if not os.path.exists(FILE_NAME):
        with open(FILE_NAME, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Name","Roll","Board","Mobile","Date","TranID"])

def save_data(name, roll, board, mobile, date, tran_id):
    with open(FILE_NAME, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, roll, board, mobile, date, tran_id])

# ----------------- ডাটা ফেচিং ফাংশন -----------------
def get_tran_ids(roll):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Search?searchStr={roll}"
    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        ids = [r.find_all("td")[1].text.strip() for r in soup.find("table").find_all("tr")[1:]]
        return ids
    except: return []

def get_full_data(tran_id):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Voucher/{tran_id}"
    try:
        res = requests.get(url, timeout=5)
        soup = BeautifulSoup(res.text, "html.parser")
        lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
        def find(label):
            for i in range(len(lines)):
                if label in lines[i]: return lines[i+1]
            return "N/A"
        name, roll, board, mobile, date = find("Name"), find("Roll"), find("Board"), find("Mobile"), find("Date")
        save_data(name, roll, board, mobile, date, tran_id)
        text = f"<pre>\nName   : {name}\nRoll   : {roll}\nBoard  : {board}\nMobile : {mobile}\nDate   : {date}\nID     : {tran_id}\n</pre>"
        return text, mobile
    except: return None, None

# ----------------- বাটন এবং কীবোর্ড -----------------
def stop_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Search", callback_data="stop_search")]])

def next_button(num):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"➡️ Next {num}", callback_data="next_range")]])

def get_contact_buttons(mobile):
    n = mobile.replace("+","").replace(" ","")
    if n.startswith("01"): n = "880"+n[1:]
    return InlineKeyboardMarkup([[InlineKeyboardButton("📱 WhatsApp", url=f"https://wa.me/{n}"), InlineKeyboardButton("✈️ Telegram", url=f"https://t.me/+{n}")]])

# ----------------- মূল সার্চ লজিক -----------------
async def run_search(message, context, start, end):
    user_id = message.chat_id
    user_tasks[user_id] = True # সার্চ শুরু
    
    status_msg = await message.reply_text("⏳ প্রসেসিং শুরু হচ্ছে...", reply_markup=stop_button())
    count = 0
    total = end - start + 1

    for i, roll in enumerate(range(start, end+1), 1):
        # প্রতিবার চেক করবে ইউজার স্টপ করেছে কি না
        if not user_tasks.get(user_id, False):
            await message.reply_text(f"🛑 Search Stopped!\n📊 Found so far: {count}")
            return

        found_in_this_roll = False
        tids = get_tran_ids(roll)
        for tid in tids:
            # মাঝপথে স্টপ করলে ট্রানজাকশন চেক থামাবে
            if not user_tasks.get(user_id, False): break
            
            data, mobile = get_full_data(tid)
            if data:
                count += 1
                found_in_this_roll = True
                await message.reply_text(f"📄 Result {count}:\n{data}", parse_mode="HTML", reply_markup=get_contact_buttons(mobile))

        # স্ট্যাটাস আপডেট
        if i % 2 == 0 or i == total or found_in_this_roll:
            try:
                await status_msg.edit_text(f"⏳ Processing...\n🔢 Roll: {roll}\n📊 Found: {count}\n✅ Progress: {i}/{total}", reply_markup=stop_button())
            except: pass

        # ২ সেকেন্ড গ্যাপ - এটি এখন বাটনকে ব্লক করবে না
        for _ in range(20): # ২ সেকেন্ডকে ছোট ছোট ভাগে ভাগ করা হয়েছে যাতে দ্রুত রেসপন্স করে
            if not user_tasks.get(user_id, False): return
            await asyncio.sleep(0.1)

    user_tasks[user_id] = False
    await status_msg.edit_text(f"✅ Done!\n📊 Total: {count}")
    await message.reply_text(f"👉 Next {total}?", reply_markup=next_button(total))

# ----------------- হ্যান্ডলারস -----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    if text == "🚀 Start":
        await update.message.reply_text("✅ Ready!", reply_markup=ReplyKeyboardMarkup([["🚀 Start"],["📂 Search Database"],["📥 Download Data"]], resize_keyboard=True))
    elif text == "📂 Search Database":
        await update.message.reply_text("👉 Roll (e.g. 123) or Range (e.g. 100-500)")
    elif text == "📥 Download Data":
        if os.path.exists(FILE_NAME): await update.message.reply_document(open(FILE_NAME,"rb"))
        else: await update.message.reply_text("❌ No data")
    elif text.isdigit():
        roll = int(text)
        last_range[user_id] = (roll, roll)
        await run_search(update.message, context, roll, roll)
    elif "-" in text:
        try:
            s, e = map(int, text.split("-"))
            if (e-s+1) > 500: await update.message.reply_text("❌ Max 500 limit")
            else:
                last_range[user_id] = (s, e)
                await run_search(update.message, context, s, e)
        except: await update.message.reply_text("❌ Format: 100-200")

async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "stop_search":
        user_tasks[user_id] = False # সিগন্যাল বন্ধ করে দেওয়া হলো
        await query.answer("🛑 Stopping Search...")
    elif query.data == "next_range":
        await query.answer()
        s, e = last_range.get(user_id, (0,0))
        diff = e - s + 1
        new_s, new_e = e + 1, e + diff
        last_range[user_id] = (new_s, new_e)
        await query.message.reply_text(f"🔄 Auto Search: {new_s}-{new_e}")
        await run_search(query.message, context, new_s, new_e)

# ================= RUN =================
if __name__ == '__main__':
    init_file()
    keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("👋 Hi!")))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_query))
    print("🤖 Bot is Online...")
    app.run_polling()
