from flask import Flask
from threading import Thread
import requests
import asyncio  # এটি স্টপ বাটন দ্রুত কাজ করার জন্য জরুরি
import time
import csv
import os
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ================= KEEP ALIVE =================
app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is running!"

def run():
    app_web.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# ================= FINAL UPDATED BOT CODE =================
TOKEN = "8720872771:AAF1BSkDHA2KE_clSS8pqb9a0BzTsaPZHmg" # আপনার বটের টোকেন এখানে দিন
FILE_NAME = "data.csv"

last_range = {}
stop_requests = {} 

def init_file():
    if not os.path.exists(FILE_NAME):
        with open(FILE_NAME, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Name","Roll","Board","Mobile","Date","TranID"])

def is_duplicate(tran_id):
    if not os.path.exists(FILE_NAME):
        return False
    with open(FILE_NAME, "r", encoding="utf-8") as f:
        return any(tran_id in row for row in f)

def save_data(name, roll, board, mobile, date, tran_id):
    if is_duplicate(tran_id):
        return
    with open(FILE_NAME, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, roll, board, mobile, date, tran_id])

def get_tran_ids(roll):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Search?searchStr={roll}"
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        ids = []
        rows = soup.find("table").find_all("tr")[1:]
        for r in rows:
            ids.append(r.find_all("td")[1].text.strip())
        return ids
    except:
        return []

def get_full_data(tran_id):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Voucher/{tran_id}"
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]

        def find(label):
            for i in range(len(lines)):
                if label in lines[i]:
                    return lines[i+1]
            return "Not found"

        name = find("Name")
        roll = find("Roll")
        board = find("Board")
        mobile = find("Mobile")
        date = find("Date")

        save_data(name, roll, board, mobile, date, tran_id)

        text = f"""<pre>
Name   : {name}
Roll   : {roll}
Board  : {board}
Mobile : {mobile}
Date   : {date}
ID     : {tran_id}
</pre>"""
        return text, mobile
    except:
        return None, None

def format_number_bd(mobile):
    n = mobile.replace("+","").replace(" ","")
    if n.startswith("01"):
        return "880"+n[1:]
    if n.startswith("880"):
        return n
    return None

def get_contact_buttons(mobile):
    n = format_number_bd(mobile)
    if not n: return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("📱 WhatsApp", url=f"https://wa.me/{n}"),
        InlineKeyboardButton("✈️ Telegram", url=f"https://t.me/+{n}")
    ]])

def stop_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Search", callback_data="stop_search")]])

def next_button(limit_text):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"➡️ Next {limit_text}", callback_data="next_range")]])

def get_keyboard():
    return ReplyKeyboardMarkup(
        [["🚀 Start"],["📂 Search Database"],["📥 Download Data"]],
        resize_keyboard=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome!", reply_markup=get_keyboard())

async def run_range(message, context, start, end):
    user_id = message.chat_id
    stop_requests[user_id] = False
    
    status = await message.reply_text("⏳ প্রসেসিং শুরু হচ্ছে...", reply_markup=stop_button())
    count = 0
    total_rolls = end - start + 1

    for i, roll in enumerate(range(start, end+1), 1):
        # এখন স্টপ বাটন চাপা মাত্রই কাজ করবে
        if stop_requests.get(user_id):
            await message.reply_text(f"🛑 Search Stopped by User!\n📊 Found: {count}")
            return

        found_now = False
        tids = get_tran_ids(roll)
        for tid in tids:
            data, mobile = get_full_data(tid)
            if data:
                count += 1
                found_now = True
                await message.reply_text(f"📄 Result {count}:\n{data}", parse_mode="HTML", reply_markup=get_contact_buttons(mobile))

        # ঘনঘন আপডেট (প্রতি ৩ রোল পর পর অথবা ডাটা পাওয়া গেলে)
        if i % 3 == 0 or i == total_rolls or found_now:
            try:
                await status.edit_text(
                    f"⏳ Processing...\n🔢 Roll: {roll}\n📊 Found: {count}\n✅ Progress: {i}/{total_rolls}",
                    reply_markup=stop_button()
                )
            except: pass

        # ২ সেকেন্ড গ্যাপ (অ্যাসিনক্রোনাস স্লিপ যাতে স্টপ বাটন কাজ করে)
        await asyncio.sleep(2)

    await status.edit_text(f"✅ Done!\n📊 Total Found: {count}")
    await message.reply_text(f"👉 Next {total_rolls}?", reply_markup=next_button(total_rolls))

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    if text == "🚀 Start":
        await update.message.reply_text("✅ Ready!", reply_markup=get_keyboard())
        return

    if text == "📂 Search Database":
        await update.message.reply_text("👉 Roll বা Range দাও (max 500)")
        return

    if text == "📥 Download Data":
        if os.path.exists(FILE_NAME):
            await update.message.reply_document(open(FILE_NAME,"rb"))
        else:
            await update.message.reply_text("❌ No data")
        return

    if text.isdigit():
        roll = int(text)
        await update.message.reply_text(f"⏳ Searching for: {roll}...")
        tids = get_tran_ids(roll)
        if not tids:
            await update.message.reply_text("❌ No data found.")
        else:
            for i, tid in enumerate(tids, 1):
                data, mobile = get_full_data(tid)
                if data:
                    await update.message.reply_text(f"📄 Result {i}:\n{data}", parse_mode="HTML", reply_markup=get_contact_buttons(mobile))
        
        last_range[user_id] = (roll, roll)
        await update.message.reply_text("👉 Next Roll?", reply_markup=next_button(1))
        return

    if "-" in text:
        try:
            start_r, end_r = map(int, text.split("-"))
        except:
            await update.message.reply_text("❌ Wrong format (Use: 1001-1500)")
            return

        if (end_r - start_r + 1) > 500:
            await update.message.reply_text("❌ Maximum 500 limit!")
            return

        last_range[user_id] = (start_r, end_r)
        await run_range(update.message, context, start_r, end_r)
        return

    await update.message.reply_text("❌ Invalid input")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    # বাটন রিমুভ করা
    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "stop_search":
        stop_requests[user_id] = True
        await query.answer("🛑 Stopping...")
        return

    if query.data == "next_range":
        await query.answer()
        if user_id not in last_range:
            await query.message.reply_text("❌ No last range found!")
            return

        start_r, end_r = last_range[user_id]
        diff = end_r - start_r + 1
        new_start = end_r + 1
        new_end = end_r + diff
        last_range[user_id] = (new_start, new_end)

        await query.message.reply_text(f"🔄 Auto Search: {new_start}-{new_end}")
        await run_range(query.message, context, new_start, new_end)

# ================= RUN =================
init_file()
keep_alive()

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle))
app.add_handler(CallbackQueryHandler(handle_callback))

print("🤖 BOT ONLINE - STOP BUTTON & FAST UPDATE ACTIVE...")
app.run_polling()
