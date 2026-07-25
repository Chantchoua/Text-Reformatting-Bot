import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

import threading
from flask import Flask

# Petit serveur Web dummy pour valider le Web Service sur Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Telegram actif !"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# Lancer Flask dans un thread séparé
threading.Thread(target=run_flask, daemon=True).start()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Vérifie si l'expéditeur est un administrateur du groupe."""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == "private":
        return True
    
    chat_member = await context.bot.get_chat_member(chat.id, user.id)
    return chat_member.status in ["administrator", "creator"]

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intercepte les messages des admins et propose la reformatage/prévisualisation."""
    message = update.effective_message
    
    if not message or not message.text or not await is_admin(update, context):
        return

    entities = message.entities or []
    links = []

    for entity in entities:
        if entity.type == "url":
            url = message.text[entity.offset : entity.offset + entity.length]
            links.append((url, url))
        elif entity.type == "text_link":
            anchor_text = message.text[entity.offset : entity.offset + entity.length]
            links.append((anchor_text, entity.url))

    if not links:
        return

    # Sauvegarde des données associées au message
    msg_key = f"msg_{message.chat.id}_{message.message_id}"
    context.bot_data[msg_key] = {
        "text": message.text,
        "links": links,
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "user_id": update.effective_user.id
    }

    # Boutons d'action rapides dans le groupe
    keyboard = [
        [
            InlineKeyboardButton("✨ Reformater direct", callback_data=f"pub_{msg_key}"),
            InlineKeyboardButton("👁️ Prévisualiser en MP", callback_data=f"prev_{msg_key}")
        ],
        [
            InlineKeyboardButton("❌ Ignorer", callback_data=f"del_{msg_key}")
        ]
    ]
    
    await message.reply_text(
        "💡 **Option Admin :** Ce message contient des liens.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gère l'ensemble des interactions avec les boutons."""
    query = update.callback_query
    await query.answer()

    data = query.data
    action, msg_key = data.split("_", 1)
    stored_data = context.bot_data.get(msg_key)

    if action == "del":
        await query.delete_message()
        return

    if not stored_data:
        await query.edit_message_text("⚠️ Les données de ce message ont expiré.")
        return

    original_text = stored_data["text"]
    links = stored_data["links"]
    chat_id = stored_data["chat_id"]
    orig_msg_id = stored_data["message_id"]

    # Construction du clavier de liens
    link_buttons = []
    for label, url in links:
        btn_label = label if len(label) <= 30 else label[:27] + "..."
        link_buttons.append([InlineKeyboardButton(text=f"🔗 {btn_label}", url=url)])

    # --- CAS 1 : PRÉVISUALISATION PRIVÉE ---
    if action == "prev":
        user_id = query.from_user.id
        
        # On ajoute un bouton de validation au clavier de prévisualisation
        preview_keyboard = list(link_buttons)
        preview_keyboard.append([
            InlineKeyboardButton("🚀 Valider et publier dans le groupe", callback_data=f"pub_{msg_key}")
        ])

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"👁️ **PRÉVISUALISATION DU MESSAGE**\n\n---\n\n{original_text}",
                reply_markup=InlineKeyboardMarkup(preview_keyboard),
                disable_web_page_preview=True,
                parse_mode="Markdown"
            )
            # Met à jour le message d'invite dans le groupe
            await query.edit_message_text("📩 La prévisualisation vous a été envoyée en message privé.")
        except Exception:
            await query.edit_message_text(
                "❌ Impossible de vous envoyer un MP. Assurez-vous d'avoir démarré le bot en privé (`/start`)."
            )

    # --- CAS 2 : PUBLICATION DANS LE GROUPE ---
    elif action == "pub":
        # Envoie le message propre dans le groupe
        await context.bot.send_message(
            chat_id=chat_id,
            text=original_text,
            reply_markup=InlineKeyboardMarkup(link_buttons),
            disable_web_page_preview=True
        )

        # Nettoyage
        if query.message.chat.type == "private":
            await query.edit_message_text("✅ Message publié avec succès dans le groupe !")
        else:
            await query.delete_message()

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=orig_msg_id)
        except Exception:
            pass  # Le bot n'a pas la permission de suppression

        # Suppression des données en cache
        context.bot_data.pop(msg_key, None)

def main():
    if not TOKEN:
        raise ValueError("Le jeton TELEGRAM_BOT_TOKEN est manquant.")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_message))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Le bot est opérationnel...")
    app.run_polling()

if __name__ == "__main__":
    main()
      
