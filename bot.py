import asyncio
import httpx
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

# এটিই আসল সমাধান: গ্লোবাল কন্ট্রোল
user_search_lock = {}  # {user_id: bool} - নিশ্চিত করবে একবারে একটাই সার্চ চলবে
user_stop_signal = {}  # {user_id: bool} - স্টপ সিগন্যাল
last_range = {}

def init_file():
    if not os.path.exists(FILE_NAME):
        with open(FILE_NAME, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Name","Roll","Board","Mobile","Date","TranID"])

def save_data(name, roll, board, mobile, date, tran_id):
    with open(FILE_NAME, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, roll, board, mobile, date, tran_id])

# ----------------- আসিনক্রোনাস ফেচিং -----------------
async def get_tran_ids(client, roll):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Search?searchStr={roll}"
    try:
        res = await client.get(url, timeout=5.0)
        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.find("table")
        if not table: return []
        return [r.find_all("td")[1].text.strip() for r in table.find_all("tr")[1:]]
    except: return []

async def get_full_data(client, tran_id):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Voucher/{tran_id}"
    try:
        res = await client.get(url, timeout=5.0)
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

# ----------------- কীবোর্ড ও বাটন -----------------
def stop_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Search", callback_data="stop_search")]])

def next_button(num):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"➡️ Next {num}", callback_data="next_range")]])

# ----------------- মূল সার্চ ইঞ্জিন (বুলেটপ্রুফ) -----------------
async def run_search(message, context, start, end):
    user_id = message.chat_id
    
    # লক চেক: যদি আগে থেকেই সার্চ চলে তবে নতুনটা শুরু হতে দেবে না
    if user_search_lock.get(user_id, False):
        await message.reply_text("⚠️ ভাই আগে একটা তো থামান! উপরের স্টপ বাটনে চাপ দিন।")
        return

    user_search_lock[user_id] = True
    user_stop_signal[user_id] = False
    
    status_msg = await message.reply_text("⏳ ইঞ্জিন চালু হচ্ছে...", reply_markup=stop_button())
    count = 0
    total = end - start + 1

    async with httpx.AsyncClient() as client:
        for i, roll in enumerate(range(start, end+1), 1):
            # একদম শুরুতে চেক
            if user_stop_signal.get(user_id, False): break

            tids = await get_tran_ids(client, roll)
            
            for tid in tids:
                # রিকোয়েস্টের মাঝখানেও চেক
                if user_stop_signal.get(user_id, False): break
                
                data, mobile = await get_full_data(client, tid)
                if data:
                    count += 1
                    try: await status_msg.delete()
                    except: pass
                    
                    await message.reply_text(f"📄 Result {count}:\n{data}", parse_mode="HTML")
                    status_msg = await message.reply_text(f"⏳ Processing: {roll}\n📊 Found: {count}\n✅ {i}/{total}", reply_markup=stop_button())

            # বিরতি (স্টপ কমান্ড নেওয়ার জন্য সময় দেওয়া)
            for _ in range(10):
                if user_stop_signal.get(user_id, False): break
                await asyncio.sleep(0.2)

    # লুপ শেষ হওয়ার পর ক্লিয়ারেন্স
    was_stopped = user_stop_signal.get(user_id, False)
    user_search_lock[user_id] = False # লক খুলে দেওয়া হলো
    
    try: await status_msg.delete()
    except: pass
    
    if was_stopped:
        await message.reply_text(f"🛑 সফলভাবে বন্ধ হয়েছে!\n📊 মোট পাওয়া গেছে: {count}")
    else:
        await message.reply_text(f"✅ সার্চ সম্পন্ন!\n📊 মোট: {count}")
        await message.reply_text(f"👉 Next {total}?", reply_markup=next_button(total))

# ----------------- হ্যান্ডলারস -----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    
    if text == "🚀 Start":
        await update.message.reply_text("✅ Ready!", reply_markup=ReplyKeyboardMarkup([["🚀 Start"],["📂 Search Database"],["📥 Download Data"]], resize_keyboard=True))
    elif text.isdigit():
        last_range[user_id] = (int(text), int(text))
        await run_search(update.message, context, int(text), int(text))
    elif "-" in text:
        try:
            s, e = map(int, text.split("-"))
            last_range[user_id] = (s, e)
            await run_search(update.message, context, s, e)
        except: pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data == "stop_search":
        user_stop_signal[user_id] = True # সিগন্যাল লাল!
        await query.answer("🛑 বন্ধ করা হচ্ছে...")
    elif query.data == "next_range":
        await query.answer()
        s, e = last_range.get(user_id, (0,0))
        diff = e - s + 1
        await run_search(query.message, context, e + 1, e + diff)

# ================= RUN =================
if __name__ == '__main__':
    init_file()
    keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("🤖 Bot is Guarded - Dual Lock System Active...")
    app.run_polling()
