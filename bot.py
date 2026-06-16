"""
Web3 Viral Tweet Writer — Advanced Bot v2
Features: 6 tones, 8 niches, content history, inline editing,
engagement scoring, topic suggestions, context memory, DeepSeek + NVIDIA
"""

import os
import json
import logging
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode, ChatAction

from openai import OpenAI
from prompts import (
    MASTER_SYSTEM_PROMPT,
    TONE_ADDONS,
    NICHE_ADDONS,
    EDIT_SYSTEM_PROMPT,
    SUGGEST_TOPICS_PROMPT,
    SCORE_PROMPT,
)
import database as db

# ─── Config ───────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8832243793:AAEy3u0BD-_pyI5QrBLIE8GOHxNZTYxCBZE")
ADMIN_ID            = int(os.getenv("ADMIN_ID", "5825181230"))
DEEPSEEK_API_KEY    = os.getenv("DEEPSEEK_API_KEY", "sk-b7b1b286f54749889e7503b6494ac6e0")
NVIDIA_API_KEY      = os.getenv("NVIDIA_API_KEY", "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")

deepseek = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
nvidia   = OpenAI(api_key=NVIDIA_API_KEY,   base_url="https://integrate.api.nvidia.com/v1")

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

TONES = {
    "builder":       "🏗️ Builder",
    "degen":         "🎲 Degen",
    "alpha":         "🔍 Alpha",
    "educator":      "📚 Educator",
    "controversial": "🔥 Controversial",
    "storyteller":   "📖 Storyteller",
}

NICHES = {
    "defi":      "💰 DeFi",
    "nft":       "🖼️ NFT",
    "l1l2":      "⚙️ L1/L2",
    "trading":   "📈 Trading",
    "ai_web3":   "🤖 AI×Web3",
    "memecoins": "🐸 Memecoins",
    "dao":       "🗳️ DAO",
    "gamefi":    "🎮 GameFi",
}

CONTENT_TYPES = {
    "tweet":      "✍️ Single Tweet",
    "thread":     "🧵 Thread (6-9 tweets)",
    "hooks":      "🎣 3 Hook Variations",
    "thread_mini":"⚡ Mini Thread (3 tweets)",
}

# ─── Guards ───────────────────────────────────────────────────────────────────

def is_admin(uid): return uid == ADMIN_ID

async def guard(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Private bot.")
        return False
    return True

# ─── AI Engine ────────────────────────────────────────────────────────────────

def build_system_prompt(tone: str, niche: str) -> str:
    base = MASTER_SYSTEM_PROMPT
    base += "\n\n" + TONE_ADDONS.get(tone, TONE_ADDONS["builder"])
    base += "\n\n" + NICHE_ADDONS.get(niche, NICHE_ADDONS["defi"])
    return base


def build_user_prompt(topic: str, content_type: str, context_history: list) -> str:
    type_instructions = {
        "tweet":       "Write ONE single viral tweet.",
        "thread":      "Write a viral thread of 6-9 tweets. Use 🧵 at end of tweet 1, then number the rest.",
        "hooks":       "Write 3 completely different hook variations for this topic — each a different archetype. Label them Hook A, Hook B, Hook C.",
        "thread_mini": "Write a punchy 3-tweet mini-thread. Tight, high-signal, no filler.",
    }

    context_note = ""
    if context_history:
        recent = context_history[-3:]
        context_note = "\n\nPrevious topics you've written about (for variety, don't repeat these angles):\n"
        for c in recent:
            context_note += f"- {c['topic']}: {c['snippet'][:100]}...\n"

    return f"""{type_instructions.get(content_type, type_instructions['tweet'])}

TOPIC / CONTEXT:
{topic}
{context_note}
Follow ALL system instructions. Be human. Be specific. Make it undeniably good."""


def call_deepseek(messages, temperature=0.88, max_tokens=2000):
    response = deepseek.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


def call_nvidia(messages, temperature=0.88, max_tokens=2000):
    response = nvidia.chat.completions.create(
        model="meta/llama-3.3-70b-instruct",
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


async def generate(
    topic: str,
    content_type: str,
    tone: str,
    niche: str,
    context_history: list,
    force_nvidia: bool = False,
    force_deepseek: bool = False,
) -> tuple[str, str]:
    """Generate content. Returns (content, model_used)."""
    sys_prompt = build_system_prompt(tone, niche)
    usr_prompt = build_user_prompt(topic, content_type, context_history)
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user",   "content": usr_prompt},
    ]

    if force_nvidia:
        content = await asyncio.to_thread(call_nvidia, messages)
        return content, "NVIDIA"

    if force_deepseek:
        content = await asyncio.to_thread(call_deepseek, messages)
        return content, "DeepSeek"

    # Default: DeepSeek first, fallback to NVIDIA
    try:
        content = await asyncio.to_thread(call_deepseek, messages)
        return content, "DeepSeek"
    except Exception as e:
        log.warning(f"DeepSeek failed: {e} — trying NVIDIA")
        content = await asyncio.to_thread(call_nvidia, messages)
        return content, "NVIDIA (fallback)"


async def score_content(content: str) -> dict:
    """Score content with AI. Returns parsed score dict."""
    messages = [
        {"role": "system", "content": SCORE_PROMPT},
        {"role": "user",   "content": f"Score this content:\n\n{content}"},
    ]
    try:
        raw = await asyncio.to_thread(call_deepseek, messages, 0.3, 800)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        log.error(f"Scoring failed: {e}")
        return None


async def suggest_topics_ai() -> list:
    """AI-generated topic suggestions."""
    messages = [
        {"role": "system", "content": SUGGEST_TOPICS_PROMPT},
        {"role": "user",   "content": "Give me 8 high-potential Web3 content ideas for today."},
    ]
    try:
        raw = await asyncio.to_thread(call_deepseek, messages, 0.9, 1200)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return data.get("topics", [])
    except Exception as e:
        log.error(f"Topic suggestions failed: {e}")
        return []


async def edit_content(original: str, instruction: str) -> str:
    """Edit existing content based on instruction."""
    messages = [
        {"role": "system", "content": EDIT_SYSTEM_PROMPT},
        {"role": "user",   "content": f"Original content:\n{original}\n\nEdit instruction: {instruction}"},
    ]
    try:
        return await asyncio.to_thread(call_deepseek, messages, 0.8, 1500)
    except Exception:
        return await asyncio.to_thread(call_nvidia, messages, 0.8, 1500)

# ─── Keyboards ────────────────────────────────────────────────────────────────

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
         InlineKeyboardButton("📚 History", callback_data="menu_history")],
        [InlineKeyboardButton("💡 Topic Ideas", callback_data="menu_suggest"),
         InlineKeyboardButton("❓ Help", callback_data="menu_help")],
    ])


def kb_after_gen(gen_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Score It", callback_data=f"score_{gen_id}"),
         InlineKeyboardButton("✏️ Edit", callback_data=f"edit_{gen_id}")],
        [InlineKeyboardButton("🔄 Redo (DeepSeek)", callback_data=f"redo_ds_{gen_id}"),
         InlineKeyboardButton("⚡ Redo (NVIDIA)", callback_data=f"redo_nv_{gen_id}")],
        [InlineKeyboardButton("🎲 Try Different Tone", callback_data=f"alttone_{gen_id}"),
         InlineKeyboardButton("🧵 Make It a Thread", callback_data=f"tothread_{gen_id}")],
        [InlineKeyboardButton("💾 Saved ✓", callback_data=f"saved_{gen_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{gen_id}")],
    ])


def kb_settings(prefs: dict):
    tone = prefs.get("tone", "builder")
    niche = prefs.get("niche", "defi")
    ctype = prefs.get("content_type", "tweet")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("── TONE ──", callback_data="noop")],
        [InlineKeyboardButton(
            f"{'✅ ' if tone == k else ''}{v}", callback_data=f"set_tone_{k}"
        ) for k, v in list(TONES.items())[:3]],
        [InlineKeyboardButton(
            f"{'✅ ' if tone == k else ''}{v}", callback_data=f"set_tone_{k}"
        ) for k, v in list(TONES.items())[3:]],
        [InlineKeyboardButton("── NICHE ──", callback_data="noop")],
        [InlineKeyboardButton(
            f"{'✅ ' if niche == k else ''}{v}", callback_data=f"set_niche_{k}"
        ) for k, v in list(NICHES.items())[:4]],
        [InlineKeyboardButton(
            f"{'✅ ' if niche == k else ''}{v}", callback_data=f"set_niche_{k}"
        ) for k, v in list(NICHES.items())[4:]],
        [InlineKeyboardButton("── FORMAT ──", callback_data="noop")],
        [InlineKeyboardButton(
            f"{'✅ ' if ctype == k else ''}{v}", callback_data=f"set_type_{k}"
        ) for k, v in list(CONTENT_TYPES.items())[:2]],
        [InlineKeyboardButton(
            f"{'✅ ' if ctype == k else ''}{v}", callback_data=f"set_type_{k}"
        ) for k, v in list(CONTENT_TYPES.items())[2:]],
        [InlineKeyboardButton("✅ Done", callback_data="menu_close")],
    ])


def kb_history(items: list):
    rows = []
    for item in items[:8]:
        short = item["topic"][:28] + "…" if len(item["topic"]) > 28 else item["topic"]
        label = f"{TONES.get(item['tone'], '?')} | {short}"
        rows.append([InlineKeyboardButton(label, callback_data=f"view_{item['id']}")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="menu_close")])
    return InlineKeyboardMarkup(rows)


def kb_score(score_data: dict, gen_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Apply Quick Fix", callback_data=f"quickfix_{gen_id}"),
         InlineKeyboardButton("🔙 Back", callback_data=f"back_{gen_id}")],
    ])

# ─── Score Formatter ──────────────────────────────────────────────────────────

def format_score(score_data: dict) -> str:
    if not score_data:
        return "❌ Scoring failed — try again."

    s = score_data.get("scores", {})
    overall = score_data.get("overall", 0)

    def bar(n):
        filled = round(n / 10 * 8)
        return "█" * filled + "░" * (8 - filled) + f" {n}/10"

    grade = "🟢 Strong" if overall >= 8 else "🟡 Decent" if overall >= 6 else "🔴 Needs work"

    return (
        f"📊 *ENGAGEMENT SCORE*\n\n"
        f"Hook strength      {bar(s.get('hook', 0))}\n"
        f"Reply potential    {bar(s.get('reply_potential', 0))}\n"
        f"Bookmark value     {bar(s.get('bookmark_value', 0))}\n"
        f"Repost potential   {bar(s.get('repost_potential', 0))}\n"
        f"Algo fit           {bar(s.get('algo_fit', 0))}\n"
        f"Authenticity       {bar(s.get('authenticity', 0))}\n"
        f"Niche relevance    {bar(s.get('niche_relevance', 0))}\n"
        f"Timing             {bar(s.get('timing', 0))}\n\n"
        f"*Overall: {overall}/10 — {grade}*\n\n"
        f"💬 _{score_data.get('verdict', '')}_\n\n"
        f"✅ *Strength:* {score_data.get('top_strength', '')}\n"
        f"⚠️ *Weakness:* {score_data.get('top_weakness', '')}\n"
        f"⚡ *Quick fix:* {score_data.get('quick_fix', '')}"
    )

# ─── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    uid = update.effective_user.id
    prefs = db.get_prefs(uid)

    tone_label  = TONES.get(prefs["tone"], prefs["tone"])
    niche_label = NICHES.get(prefs["niche"], prefs["niche"])
    type_label  = CONTENT_TYPES.get(prefs["content_type"], prefs["content_type"])

    await update.message.reply_text(
        "🚀 *Web3 Viral Tweet Writer v2*\n\n"
        "The most advanced Web3 content engine on Telegram.\n\n"
        f"*Current settings:*\n"
        f"Tone → {tone_label}\n"
        f"Niche → {niche_label}\n"
        f"Format → {type_label}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Just *send any topic or idea* to generate content.\n\n"
        "Or use /settings to customize your voice, niche and format.\n"
        "Or use /suggest to get AI topic ideas.\n\n"
        "*Commands:*\n"
        "/settings — tone, niche, format\n"
        "/suggest — AI topic ideas\n"
        "/history — past generations\n"
        "/help — full guide",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_main(),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    await update.message.reply_text(
        "📖 *How to use this bot*\n\n"
        "*Basic:*\n"
        "Send any topic → get viral content\n\n"
        "*After generation:*\n"
        "📊 Score It — AI engagement score + advice\n"
        "✏️ Edit — Tell the bot what to change\n"
        "🔄 Redo — Regenerate same topic, different output\n"
        "🎲 Try Different Tone — Alt tone same topic\n"
        "🧵 Make It a Thread — Expand tweet to thread\n\n"
        "*Settings:*\n"
        "6 tones: Builder, Degen, Alpha, Educator, Controversial, Storyteller\n"
        "8 niches: DeFi, NFT, L1/L2, Trading, AI×Web3, Memecoins, DAO, GameFi\n"
        "4 formats: Single tweet, Thread, 3 Hook variations, Mini thread\n\n"
        "*Pro tips:*\n"
        "• Give context, not just keywords: 'we just hit $10M TVL on our DeFi vault protocol' > 'DeFi'\n"
        "• Use /suggest when you're stuck on what to post\n"
        "• Switch tones to see the same topic from different angles\n"
        "• Score your content before posting — the quick fix is always gold\n"
        "• History saves everything — go back and reuse best content",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    uid = update.effective_user.id
    prefs = db.get_prefs(uid)
    await update.message.reply_text(
        "⚙️ *Settings*\n\nChoose your tone, niche, and format.\nActive settings are marked ✅",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_settings(prefs),
    )


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    history = db.get_history(10)
    if not history:
        await update.message.reply_text("📭 No history yet. Generate some content first!")
        return
    await update.message.reply_text(
        f"📚 *Last {len(history)} generations* — tap to view:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_history(history),
    )


async def cmd_suggest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await guard(update): return
    msg = await update.message.reply_text("💡 Generating topic ideas with AI...")
    await update.message.chat.send_action(ChatAction.TYPING)

    topics = await suggest_topics_ai()
    if not topics:
        await msg.edit_text("❌ Couldn't generate ideas right now. Try again.")
        return

    text = "💡 *Hot content ideas right now:*\n\n"
    buttons = []
    for i, t in enumerate(topics[:8], 1):
        emoji = "🧵" if t.get("type") == "thread" else "✍️"
        text += f"*{i}.* {emoji} _{t.get('title', '')}_\n"
        text += f"Hook: `{t.get('hook', '')[:80]}`\n"
        text += f"Why: {t.get('why', '')[:80]}\n\n"
        # Button to use this topic directly
        short_hook = t.get("hook", "")[:50]
        buttons.append([InlineKeyboardButton(
            f"{emoji} Use #{i}: {t.get('title', '')[:30]}",
            callback_data=f"usetopic_{i}"
        )])

    # Store topics for callback use
    ctx.user_data["suggested_topics"] = topics

    await msg.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(
        "Tap a topic to generate content instantly 👇",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

# ─── Message Handler ──────────────────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Private bot.")
        return

    uid = update.effective_user.id
    topic = update.message.text.strip()

    # Check if we're in edit mode
    if ctx.user_data.get("edit_mode"):
        await handle_edit_instruction(update, ctx, topic)
        return

    prefs   = db.get_prefs(uid)
    session = db.get_session(uid)
    tone    = prefs["tone"]
    niche   = prefs["niche"]
    ctype   = prefs["content_type"]

    tone_label  = TONES.get(tone, tone)
    niche_label = NICHES.get(niche, niche)
    type_label  = CONTENT_TYPES.get(ctype, ctype)

    await update.message.chat.send_action(ChatAction.TYPING)
    status = await update.message.reply_text(
        f"⚙️ Generating your {type_label}...\n"
        f"Tone: {tone_label} | Niche: {niche_label}\n"
        f"_Usually takes 10–20 seconds_",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        content, model_used = await generate(
            topic, ctype, tone, niche,
            session.get("context_history", [])
        )

        # Save to DB
        gen_id = db.save_generation(topic, content, ctype, tone, niche, model_used)
        db.save_session(uid, last_topic=topic, last_content=content, last_gen_id=gen_id)

        header = (
            f"_Generated with {model_used} · {tone_label} · {niche_label}_\n"
            f"_Topic: {topic[:50]}{'…' if len(topic)>50 else ''}_\n\n"
        )

        await status.delete()
        await update.message.reply_text(
            header + content,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_after_gen(gen_id),
        )

    except Exception as e:
        log.error(f"Generation error: {e}")
        await status.edit_text(
            f"❌ Generation failed.\n\n`{str(e)[:150]}`\n\nTry again in a moment.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_edit_instruction(update: Update, ctx: ContextTypes.DEFAULT_TYPE, instruction: str):
    """Handle edit instructions when in edit mode."""
    gen_id   = ctx.user_data.get("edit_gen_id")
    original = ctx.user_data.get("edit_content")

    ctx.user_data.pop("edit_mode", None)
    ctx.user_data.pop("edit_gen_id", None)
    ctx.user_data.pop("edit_content", None)

    await update.message.chat.send_action(ChatAction.TYPING)
    status = await update.message.reply_text("✏️ Applying your changes...")

    try:
        revised = await edit_content(original, instruction)
        # Save revised as new generation
        session = db.get_session(update.effective_user.id)
        last_gen = db.get_generation(gen_id)
        new_id = db.save_generation(
            last_gen["topic"] if last_gen else "edited",
            revised,
            last_gen["content_type"] if last_gen else "tweet",
            last_gen["tone"] if last_gen else "builder",
            last_gen["niche"] if last_gen else "defi",
            "DeepSeek (edit)",
        )
        await status.delete()
        await update.message.reply_text(
            revised,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_after_gen(new_id),
        )
    except Exception as e:
        await status.edit_text(f"❌ Edit failed: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)

# ─── Callback Handler ─────────────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    uid  = query.from_user.id
    data = query.data

    # ── Settings ──────────────────────────────────────────────────────────────
    if data.startswith("set_tone_"):
        tone = data.replace("set_tone_", "")
        db.save_prefs(uid, tone=tone)
        prefs = db.get_prefs(uid)
        await query.edit_message_reply_markup(reply_markup=kb_settings(prefs))
        await query.answer(f"Tone set to {TONES.get(tone, tone)}", show_alert=False)

    elif data.startswith("set_niche_"):
        niche = data.replace("set_niche_", "")
        db.save_prefs(uid, niche=niche)
        prefs = db.get_prefs(uid)
        await query.edit_message_reply_markup(reply_markup=kb_settings(prefs))
        await query.answer(f"Niche set to {NICHES.get(niche, niche)}", show_alert=False)

    elif data.startswith("set_type_"):
        ctype = data.replace("set_type_", "")
        db.save_prefs(uid, content_type=ctype)
        prefs = db.get_prefs(uid)
        await query.edit_message_reply_markup(reply_markup=kb_settings(prefs))
        await query.answer(f"Format set to {CONTENT_TYPES.get(ctype, ctype)}", show_alert=False)

    # ── Menus ─────────────────────────────────────────────────────────────────
    elif data == "menu_settings":
        prefs = db.get_prefs(uid)
        await query.message.reply_text(
            "⚙️ *Settings* — tap to switch, ✅ = active",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_settings(prefs),
        )

    elif data == "menu_history":
        history = db.get_history(10)
        if not history:
            await query.answer("No history yet!", show_alert=True)
            return
        await query.message.reply_text(
            f"📚 *Last {len(history)} generations:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_history(history),
        )

    elif data == "menu_suggest":
        await query.message.reply_text("💡 Fetching topic ideas...")
        topics = await suggest_topics_ai()
        if not topics:
            await query.message.reply_text("❌ Couldn't generate ideas. Try again.")
            return

        text = "💡 *Hot content ideas right now:*\n\n"
        buttons = []
        for i, t in enumerate(topics[:8], 1):
            emoji = "🧵" if t.get("type") == "thread" else "✍️"
            text += f"*{i}.* {emoji} _{t.get('title', '')}_\n"
            text += f"`{t.get('hook', '')[:90]}`\n\n"
            buttons.append([InlineKeyboardButton(
                f"{emoji} #{i}: {t.get('title', '')[:35]}",
                callback_data=f"usetopic_{i}"
            )])

        ctx.user_data["suggested_topics"] = topics
        await query.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        await query.message.reply_text("Tap to generate instantly 👇", reply_markup=InlineKeyboardMarkup(buttons))

    elif data == "menu_help":
        await query.message.reply_text(
            "📖 *Quick guide:*\n\n"
            "• Send any topic to generate\n"
            "• 📊 Score It — AI engagement scoring\n"
            "• ✏️ Edit — tell it what to change\n"
            "• 🔄 Redo — fresh version, same topic\n"
            "• 🎲 Try Different Tone — alternate voice\n"
            "• 🧵 Make Thread — expand to thread\n"
            "• /settings — tone, niche, format\n"
            "• /suggest — AI topic ideas\n"
            "• /history — saved generations",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "menu_close":
        try:
            await query.message.delete()
        except Exception:
            pass

    elif data == "noop":
        pass  # section headers

    # ── Use Suggested Topic ───────────────────────────────────────────────────
    elif data.startswith("usetopic_"):
        idx = int(data.replace("usetopic_", "")) - 1
        topics = ctx.user_data.get("suggested_topics", [])
        if not topics or idx >= len(topics):
            await query.answer("Topic expired. Use /suggest again.", show_alert=True)
            return

        topic = topics[idx].get("hook") or topics[idx].get("title", "")
        prefs   = db.get_prefs(uid)
        session = db.get_session(uid)

        await query.message.reply_text(f"⚙️ Generating from idea #{idx+1}...")
        await query.message.chat.send_action(ChatAction.TYPING)

        try:
            content, model_used = await generate(
                topic, prefs["content_type"], prefs["tone"], prefs["niche"],
                session.get("context_history", [])
            )
            gen_id = db.save_generation(topic, content, prefs["content_type"], prefs["tone"], prefs["niche"], model_used)
            db.save_session(uid, last_topic=topic, last_content=content, last_gen_id=gen_id)

            await query.message.reply_text(
                f"_Generated from AI suggestion_\n\n{content}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_after_gen(gen_id),
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Error: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)

    # ── View History Item ─────────────────────────────────────────────────────
    elif data.startswith("view_"):
        gen_id = int(data.replace("view_", ""))
        gen = db.get_generation(gen_id)
        if not gen:
            await query.answer("Not found.", show_alert=True)
            return

        tone_label  = TONES.get(gen["tone"], gen["tone"])
        niche_label = NICHES.get(gen["niche"], gen["niche"])
        created = gen.get("created_at", "")[:16]

        header = (
            f"📅 _{created}_ · {tone_label} · {niche_label}\n"
            f"🏷️ _{gen['topic'][:60]}_\n\n"
        )
        await query.message.reply_text(
            header + gen["content"],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_after_gen(gen_id),
        )

    # ── Score ─────────────────────────────────────────────────────────────────
    elif data.startswith("score_"):
        gen_id = int(data.replace("score_", ""))
        gen = db.get_generation(gen_id)
        if not gen:
            await query.answer("Not found.", show_alert=True)
            return

        await query.message.reply_text("📊 Scoring your content...")
        await query.message.chat.send_action(ChatAction.TYPING)

        score_data = await score_content(gen["content"])

        if score_data and score_data.get("overall"):
            db.update_score(gen_id, score_data["overall"])
            ctx.user_data[f"score_data_{gen_id}"] = score_data

        await query.message.reply_text(
            format_score(score_data),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_score(score_data, gen_id),
        )

    # ── Quick Fix ─────────────────────────────────────────────────────────────
    elif data.startswith("quickfix_"):
        gen_id = int(data.replace("quickfix_", ""))
        gen = db.get_generation(gen_id)
        score_data = ctx.user_data.get(f"score_data_{gen_id}")

        if not gen or not score_data:
            await query.answer("Score first!", show_alert=True)
            return

        quick_fix = score_data.get("quick_fix", "Improve the hook and add a specific number or stat.")
        await query.message.reply_text(f"⚡ Applying quick fix: _{quick_fix}_", parse_mode=ParseMode.MARKDOWN)

        try:
            revised = await edit_content(gen["content"], quick_fix)
            new_id = db.save_generation(
                gen["topic"], revised, gen["content_type"], gen["tone"], gen["niche"], "DeepSeek (quick fix)"
            )
            await query.message.reply_text(
                revised,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_after_gen(new_id),
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Quick fix failed: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)

    # ── Edit ─────────────────────────────────────────────────────────────────
    elif data.startswith("edit_"):
        gen_id = int(data.replace("edit_", ""))
        gen = db.get_generation(gen_id)
        if not gen:
            await query.answer("Not found.", show_alert=True)
            return

        ctx.user_data["edit_mode"] = True
        ctx.user_data["edit_gen_id"] = gen_id
        ctx.user_data["edit_content"] = gen["content"]

        await query.message.reply_text(
            "✏️ *Edit mode active*\n\n"
            "Tell me what to change. Examples:\n"
            "• _make it shorter_\n"
            "• _more aggressive tone_\n"
            "• _add a specific stat about ETH TVL_\n"
            "• _change the hook to a story format_\n"
            "• _make it less technical, more normie-friendly_\n"
            "• _turn this into a thread_\n\n"
            "Type your instruction now 👇",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Redo ──────────────────────────────────────────────────────────────────
    elif data.startswith("redo_"):
        parts = data.split("_")
        model = parts[1]  # "ds" or "nv"
        gen_id = int(parts[2])
        gen = db.get_generation(gen_id)
        if not gen:
            await query.answer("Not found.", show_alert=True)
            return

        force_nvidia   = model == "nv"
        force_deepseek = model == "ds"
        label = "NVIDIA" if force_nvidia else "DeepSeek"

        await query.message.reply_text(f"🔄 Regenerating with {label}...")
        await query.message.chat.send_action(ChatAction.TYPING)

        session = db.get_session(uid)
        try:
            content, model_used = await generate(
                gen["topic"], gen["content_type"], gen["tone"], gen["niche"],
                session.get("context_history", []),
                force_nvidia=force_nvidia, force_deepseek=force_deepseek,
            )
            new_id = db.save_generation(gen["topic"], content, gen["content_type"], gen["tone"], gen["niche"], model_used)
            await query.message.reply_text(
                f"_Regenerated with {model_used}_\n\n{content}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_after_gen(new_id),
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Failed: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)

    # ── Alt Tone ──────────────────────────────────────────────────────────────
    elif data.startswith("alttone_"):
        gen_id = int(data.replace("alttone_", ""))
        gen = db.get_generation(gen_id)
        if not gen:
            await query.answer("Not found.", show_alert=True)
            return

        # Rotate to next tone
        tone_keys = list(TONES.keys())
        current_idx = tone_keys.index(gen["tone"]) if gen["tone"] in tone_keys else 0
        next_tone = tone_keys[(current_idx + 1) % len(tone_keys)]
        tone_label = TONES[next_tone]

        await query.message.reply_text(f"🎲 Rewriting in *{tone_label}* tone...", parse_mode=ParseMode.MARKDOWN)
        await query.message.chat.send_action(ChatAction.TYPING)

        session = db.get_session(uid)
        try:
            content, model_used = await generate(
                gen["topic"], gen["content_type"], next_tone, gen["niche"],
                session.get("context_history", []),
            )
            new_id = db.save_generation(gen["topic"], content, gen["content_type"], next_tone, gen["niche"], model_used)
            await query.message.reply_text(
                f"_{tone_label} tone · {model_used}_\n\n{content}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_after_gen(new_id),
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Failed: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)

    # ── To Thread ─────────────────────────────────────────────────────────────
    elif data.startswith("tothread_"):
        gen_id = int(data.replace("tothread_", ""))
        gen = db.get_generation(gen_id)
        if not gen:
            await query.answer("Not found.", show_alert=True)
            return

        await query.message.reply_text("🧵 Expanding to thread...")
        await query.message.chat.send_action(ChatAction.TYPING)

        expand_prompt = f"Expand this tweet into a full viral thread (6-9 tweets):\n\n{gen['content']}"
        session = db.get_session(uid)

        try:
            content, model_used = await generate(
                expand_prompt, "thread", gen["tone"], gen["niche"],
                session.get("context_history", []),
            )
            new_id = db.save_generation(gen["topic"], content, "thread", gen["tone"], gen["niche"], model_used)
            await query.message.reply_text(
                f"_Expanded to thread · {model_used}_\n\n{content}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_after_gen(new_id),
            )
        except Exception as e:
            await query.message.reply_text(f"❌ Failed: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)

    # ── Delete ─────────────────────────────────────────────────────────────────
    elif data.startswith("del_"):
        gen_id = int(data.replace("del_", ""))
        db.delete_generation(gen_id)
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.answer("🗑️ Deleted", show_alert=False)

    elif data.startswith("saved_"):
        await query.answer("✅ Already saved to history!", show_alert=False)

    elif data.startswith("back_"):
        await query.answer()

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    db.init_db()
    log.info("Starting Advanced Web3 Tweet Writer Bot v2...")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("history",  cmd_history))
    app.add_handler(CommandHandler("suggest",  cmd_suggest))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
