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

# Configuration du logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- SERVEUR FLASK (Pour valider le Web Service Render) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot Telegram actif !"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# Lancement du serveur Web dans un thread séparé
threading.Thread(target=run_flask, daemon=True).start()

# --- BOT TELEGRAM ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Répond à la commande /start en message privé."""
    user = update.effective_user
    welcome_text = (
        f"👋 Bonjour {user.first_name} !\n\n"
        "Je suis le bot de reformatage de messages avec boutons.\n\n"
        "📌 **Comment m'utiliser ?**\n"
        "1. Ajoutez-moi à votre groupe ou canal.\n"
        "2. Donnez-moi les droits d'administrateur (suppression de messages).\n"
        "3. Lorsqu'un admin publie un message contenant des liens, je proposerai de le reformater "
        "ou d'envoyer une prévisualisation ici en privé."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Vérifie si l'expéditeur du message est un administrateur."""
    chat = update.effective_chat
    user = update.effective_user
    
    # S'il n'y a pas d'utilisateur (ex: post automatique de canal), on refuse ou gère différemment
    if not user:
        return False

    if chat.type == "private":
        return True

    try:
        chat_member = await context.bot.get_chat_member(chat.id, user.id)
        return chat_member.status in ["administrator", "creator"]
    except Exception as e:
        logging.error(f"Erreur lors de la vérification admin: {e}")
        return False


async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Intercepte les messages et channel posts contenant des liens."""
    # Récupère le message qu'il vienne d'un groupe ou d'un canal
    message = update.effective_message or update.channel_post
    
    if not message:
        return

    # On récupère le texte (soit un message texte classique, soit la légende d'un média)
    full_text = message.text or message.caption
    if not full_text:
        return
        
    # Dans un canal, les posts sont TOUJOURS faits par des admins. 
    # On ne vérifie is_admin que si on est dans un groupe/supergroupe.
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        if not await is_admin(update, context):
            return

    # Extraction des entités (liens)
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

    # Organise les boutons par rangées de 2
    link_buttons = []
    row = []

    for label, url in links:
        btn_label = label if len(label) <= 15 else label[:12] + "..."
        row.append(InlineKeyboardButton(text=f"🔗 {btn_label}", url=url))
    
        # Dès qu'on a 2 boutons, on valide la ligne
        if len(row) == 2:
            link_buttons.append(row)
            row = []

    # S'il reste un bouton impair à la fin
    if row:
        link_buttons.append(row)
    

    if action == "prev":
        user_id = query.from_user.id
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
            await query.edit_message_text("📩 La prévisualisation vous a été envoyée en message privé.")
        except Exception:
            await query.edit_message_text(
                "❌ Impossible de vous envoyer un MP. Assurez-vous d'avoir démarré le bot en privé (`/start`)."
            )

    elif action == "pub":
        await context.bot.send_message(
            chat_id=chat_id,
            text=original_text,
            reply_markup=InlineKeyboardMarkup(link_buttons),
            disable_web_page_preview=True
        )

        if query.message.chat.type == "private":
            await query.edit_message_text("✅ Message publié avec succès dans le groupe !")
        else:
            await query.delete_message()

        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=orig_msg_id)
        except Exception:
            pass

        context.bot_data.pop(msg_key, None)


def main():
    if not TOKEN:
        raise ValueError("Le jeton TELEGRAM_BOT_TOKEN est manquant.")

    bot_app = ApplicationBuilder().token(TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start_command))
    
    # MODIFICATION ICI : On écoute TEXTE + LÉGENDES D'IMAGES, dans Groupes ET Canaux
    text_or_caption = (filters.TEXT | filters.CAPTION) & ~filters.COMMAND
    
    # Handler pour les groupes / MP
    bot_app.add_handler(MessageHandler(text_or_caption, handle_admin_message))
    
    # Handler spécifique pour les CANAUX (Channel Posts)
    bot_app.add_handler(MessageHandler(filters.ChatType.CHANNEL & text_or_caption, handle_admin_message))
    
    bot_app.add_handler(CallbackQueryHandler(button_callback))

    print("Le bot est opérationnel...")
    bot_app.run_polling()
    

if __name__ == "__main__":
    main()
    
