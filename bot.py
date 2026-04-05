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

# এটিই আসল ট্র্যাকার
stop_signal = {} 
is_searching = {}
last_range = {}

def init_file():
    if not os.path.exists(FILE_NAME):
        with open(FILE_NAME, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["Name","Roll","Board","Mobile","Date","TranID"])

def save_data(name, roll, board, mobile, date, tran_id):
    with open(FILE_NAME, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([name, roll, board, mobile, date, tran_id])

# ----------------- ডাটা ফেচিং -----------------
def get_tran_ids(roll):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Search?searchStr={roll}"
    try:
        # টাইমআউট একদম কমিয়ে ৩ সেকেন্ড করে দিলাম যাতে বেশি না আটকায়
        res = requests.get(url, timeout=3)
        soup = BeautifulSoup(res.text, "html.parser")
        table = soup.find("table")
        if not table: return []
        return [r.find_all("td")[1].text.strip() for r in table.find_all("tr")[1:]]
    except: return []

def get_full_data(tran_id):
    url = f"https://billpay.sonalibank.com.bd/BoardRescrutiny/Home/Voucher/{tran_id}"
    try:
        res = requests.get(url, timeout=3)
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

# ----------------- বাটন লজিক -----------------
def stop_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop Search", callback_data="stop_search")]])

def next_button(num):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"➡️ Next {num}", callback_data="next_range")]])

def get_contact_buttons(mobile):
    n = mobile.replace("+","").replace(" ","")
    if n.startswith("01"): n = "880"+n[1:]
    return InlineKeyboardMarkup([[InlineKeyboardButton("📱 WhatsApp", url=f"https://wa.me/{n}"), InlineKeyboardButton("✈️ Telegram", url=f"https://t.me/+{n}")]])

# ----------------- কোর সার্চ ইঞ্জিন -----------------
async def run_search(message, context, start, end):
    user_id = message.chat_id
    
    if is_searching.get(user_id, False):
        await message.reply_text("⚠️ ভাই আগে একটা তো শেষ হোক!")
        return

    is_searching[user_id] = True
    stop_signal[user_id] = False # স্টপ সিগন্যাল বন্ধ
    
    status_msg = await message.reply_text("⏳ সার্চ শুরু হচ্ছে...", reply_markup=stop_button())
    count = 0
    total = end - start + 1

    try:
        for i, roll in enumerate(range(start, end+1), 1):
            # প্রতিটি রোলের শুরুতে চেক: ইউজার কি স্টপ বাটন চেপেছে?
            if stop_signal.get(user_id, False): 
                break

            found_now = False
            tids = get_tran_ids(roll)
            
            # আবার চেক: ডাটা পাওয়ার আগেও চেক
            if stop_signal.get(user_id, False): break

            for tid in tids:
                data, mobile = get_full_data(tid)
                if data:
                    count += 1
                    found_now = True
                    try: await status_msg.delete() # পুরনো মেসেজ মুছা
                    except: pass
                    
                    await message.reply_text(f"📄 Result {count}:\n{data}", parse_mode="HTML", reply_markup=get_contact_buttons(mobile))
                    status_msg = await message.reply_text(f"⏳ Processing...\n🔢 Roll: {roll}\n📊 Found: {count}\n✅ Progress: {i}/{total}", reply_markup=stop_button())

            # স্ট্যাটাস আপডেট
            if not found_now and (i % 2 == 0 or i == total):
                try: await status_msg.edit_text(f"⏳ Processing...\n🔢 Roll: {roll}\n📊 Found: {count}\n✅ Progress: {i}/{total}", reply_markup=stop_button())
                except: pass

            # ২ সেকেন্ডের গ্যাপ - এখন এটি সুপার স্মুথ হবে
            for _ in range(10): 
                if stop_signal.get(user_id, False): break
                await asyncio.sleep(0.2) # ছোট বিরতি যাতে বাটন ধরা যায়
                
    finally:
        is_stopped = stop_signal.get(user_id, False)
        is_searching[user_id] = False
        try: await status_msg.delete()
        except: pass
        
        if is_stopped:
            await message.reply_text(f"🛑 Search Stopped!\n📊 Found: {count}")
        else:
            await message.reply_text(f"✅ Done!\n📊 Total: {count}")
            await message.reply_text(f"👉 Next {total}?", reply_markup=next_button(total))

# ----------------- হ্যান্ডলারস -----------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    if text == "🚀 Start":
        await update.message.reply_text("✅ Ready!", reply_markup=ReplyKeyboardMarkup([["🚀 Start"],["📂 Search Database"],["📥 Download Data"]], resize_keyboard=True))
    elif text == "📂 Search Database":
        await update.message.reply_text("👉 Roll বা Range দিন। (১০০০-২০০০)")
    elif text == "📥 Download Data":
        if os.path.exists(FILE_NAME): await update.message.reply_document(open(FILE_NAME,"rb"))
        else: await update.message.reply_text("❌ কোনো ডাটা নেই।")
    elif text.isdigit():
        roll = int(text)
        last_range[user_id] = (roll, roll)
        await run_search(update.message, context, roll, roll)
    elif "-" in text:
        try:
            s, e = map(int, text.split("-"))
            if (e-s+1) > 500: await update.message.reply_text("❌ সর্বোচ্চ ৫০০!")
            else:
                last_range[user_id] = (s, e)
                await run_search(update.message, context, s, e)
        except: await update.message.reply_text("❌ ফরম্যাট ভুল।")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if query.data == "stop_search":
        stop_signal[user_id] = True # কমান্ড পাওয়া মাত্রই ট্রু করে দেবে
        await query.answer("🛑 সার্চ বন্ধ করা হচ্ছে...")
        await query.edit_message_reply_markup(reply_markup=None) # বাটন সাথে সাথে গায়েব
    elif query.data == "next_range":
        await query.answer()
        s, e = last_range.get(user_id, (0,0))
        diff = e - s + 1
        new_s, new_e = e + 1, e + diff
        last_range[user_id] = (new_s, new_e)
        await query.message.reply_text(f"🔄 অটো সার্চ শুরু: {new_s}-{new_e}")
        await run_search(query.message, context, new_s, new_e)

# ================= RUN =================
if __name__ == '__main__':
    init_file()
    keep_alive()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("🤖 Bot is Online - Stop Button Master Fix Active...")
    app.run_polling()
