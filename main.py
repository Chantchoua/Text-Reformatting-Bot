import os
import logging
import threading
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- FLASK SERVER (For Render Web Service Health Check) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Telegram Bot is active!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# Run Flask server in a separate thread
threading.Thread(target=run_flask, daemon=True).start()

# --- TELEGRAM BOT ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds to the /start command in private messages."""
    user = update.effective_user
    welcome_text = (
        f"👋 Hello {user.first_name}!\n\n"
        "I am the message reformatting bot with action buttons.\n\n"
        "📌 **How to use me?**\n"
        "1. Add me to your group or channel.\n"
        "2. Grant me admin rights (Message Deletion).\n"
        "3. When an admin posts a message containing links, I will propose to reformat it "
        "or send you a preview in DM."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if the message sender is an administrator."""
    chat = update.effective_chat
    user = update.effective_user
    
    if not user:
        return False

    if chat.type == "private":
        return True

    try:
        chat_member = await context.bot.get_chat_member(chat.id, user.id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logging.error(f"Error checking admin status: {e}")
        return False


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intercepts messages and channel posts containing links."""
    message = update.effective_message or update.channel_post
    
    if not message:
        return

    full_text = message.text or message.caption
    if not full_text:
        return
        
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        if not await is_admin(update, context):
            return

    entities = message.entities or message.caption_entities or []
    links = []

    for entity in entities:
        if entity.type == "url":
            url = full_text[entity.offset : entity.offset + entity.length]
            links.append((url, url))
        elif entity.type == "text_link":
            anchor_text = full_text[entity.offset : entity.offset + entity.length]
            links.append((anchor_text, entity.url))

    if not links:
        return

    msg_key = f"msg_{chat.id}_{message.message_id}"
    context.bot_data[msg_key] = {
        "text": full_text,
        "links": links,
        "chat_id": chat.id,
        "message_id": message.message_id,
    }

    keyboard = [
        [
            InlineKeyboardButton("✨ Reformat", callback_data=f"pub_{msg_key}"),
            InlineKeyboardButton("👁️ Preview", callback_data=f"prev_{msg_key}")
        ],
        [
            InlineKeyboardButton("❌ Ignore", callback_data=f"del_{msg_key}")
        ]
    ]
    
    await message.reply_text(
        "💡 **Admin Option:** This message contains links.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all button interactions."""
    query = update.callback_query
    await query.answer()

    data = query.data
    action, msg_key = data.split("_", 1)
    stored_data = context.bot_data.get(msg_key)

    if action == "del":
        await query.delete_message()
        return

    if not stored_data:
        await query.edit_message_text("⚠️ The data for this message has expired.")
        return

    original_text = stored_data["text"]
    links = stored_data["links"]
    chat_id = stored_data["chat_id"]
    orig_msg_id = stored_data["message_id"]

    # Organize buttons in rows of 2
    link_buttons = []
    row = []

    for label, url in links:
        btn_label = label if len(label) <= 15 else label[:12] + "..."
        row.append(InlineKeyboardButton(text=f"🔗 {btn_label}", url=url))
        
        if len(row) == 2:
            link_buttons.append(row)
            row = []

    if row:
        link_buttons.append(row)

    if action == "prev":
        user_id = query.from_user.id
        preview_keyboard = list(link_buttons)
        preview_keyboard.append([
            InlineKeyboardButton("🚀 Confirm and post to chat", callback_data=f"pub_{msg_key}")
        ])

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"👁️ **MESSAGE PREVIEW**\n\n---\n\n{original_text}",
                reply_markup=InlineKeyboardMarkup(preview_keyboard),
                disable_web_page_preview=True,
                parse_mode="Markdown"
            )
            await query.edit_message_text("📩 The preview has been sent to your private messages.")
        except Exception:
            await query.edit_message_text(
                "❌ Unable to send you a DM. Please make sure you have started the bot privately (`/start`)."
            )

    elif action == "pub":
        await context.bot.send_message(
            chat_id=chat_id,
            text=original_text,
            reply_markup=InlineKeyboardMarkup(link_buttons),
            disable_web_page_preview=True
        )

        if query.message.chat.type == "private":
            await query.edit_message_text("✅ Message successfully published to the channel/group!")
        else:
            await query.delete_message()

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=orig_msg_id)
        except Exception:
            pass

        context.bot_data.pop(msg_key, None)


def main():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing.")

    bot_app = ApplicationBuilder().token(TOKEN).build()

    text_or_caption = (filters.TEXT | filters.CAPTION) & ~filters.COMMAND

    # Register handlers
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(MessageHandler(text_or_caption, handle_admin_message))
    bot_app.add_handler(MessageHandler(filters.ChatType.CHANNEL & text_or_caption, handle_admin_message))
    bot_app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot is up and running...")
    bot_app.run_polling()


if __name__ == "__main__":
    main()
    
