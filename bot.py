"""
Web3 Viral Tweet Writer v3 — Main Bot
Bulletproof, advanced, MySQL-backed, fresh UI.
"""

from __future__ import annotations  # FIX: enables X | Y type hints on Python 3.9

import os
import json
import logging
import asyncio
import re
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
from telegram.error import BadRequest

from openai import OpenAI
import database as db
from prompts import (
    MASTER_SYSTEM_PROMPT,
    TONE_ADDONS,
    NICHE_ADDONS,
    EDIT_PROMPT,       # FIX: was EDIT_SYSTEM_PROMPT in original prompts.py — renamed there
    SCORE_PROMPT,
    SUGGEST_PROMPT,    # FIX: was SUGGEST_TOPICS_PROMPT in original prompts.py — renamed there
)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8832243793:AAEy3u0BD-_pyI5QrBLIE8GOHxNZTYxCBZE")
ADMIN_ID       = int(os.getenv("ADMIN_ID", "5825181230"))
DEEPSEEK_KEY   = os.getenv("DEEPSEEK_API_KEY", "sk-b7b1b286f54749889e7503b6494ac6e0")
NVIDIA_KEY     = os.getenv("NVIDIA_API_KEY", "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")

# ══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("TweetBot")

# ══════════════════════════════════════════════════════════════════════════════
# AI CLIENTS
# ══════════════════════════════════════════════════════════════════════════════

deepseek = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com")
nvidia   = OpenAI(api_key=NVIDIA_KEY,   base_url="https://integrate.api.nvidia.com/v1")

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

TONES = {
    "builder":       "🏗 Builder",
    "degen":         "🎲 Degen",
    "alpha":         "🔍 Alpha",
    "educator":      "📚 Educator",
    "controversial": "🔥 Controversial",
    "storyteller":   "📖 Storyteller",
}

NICHES = {
    "defi":      "💰 DeFi",
    "nft":       "🖼 NFT",
    "l1l2":      "⚙️ L1/L2",
    "trading":   "📈 Trading",
    "ai_web3":   "🤖 AI×Web3",
    "memecoins": "🐸 Memecoins",
    "dao":       "🗳 DAO",
    "gamefi":    "🎮 GameFi",
}

FORMATS = {
    "tweet":       "✍️ Single Tweet",
    "thread":      "🧵 Thread (6-9)",
    "hooks":       "🎣 3 Hook Variants",
    "thread_mini": "⚡ Mini Thread (3)",
}

TONE_LIST  = list(TONES.keys())
NICHE_LIST = list(NICHES.keys())

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def safe_md(text: str) -> str:
    """Escape characters that break Telegram MarkdownV1."""
    text = text.replace("\u2014", "-").replace("\u2013", "-")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return text


def truncate(text: str, n: int = 50) -> str:
    return text[:n] + "…" if len(text) > n else text


async def safe_delete(msg):
    try:
        await msg.delete()
    except Exception:
        pass


async def safe_edit(msg, text: str, **kwargs):
    try:
        await msg.edit_text(text, **kwargs)
    except BadRequest:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# AI ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _build_system(tone: str, niche: str) -> str:
    return (
        MASTER_SYSTEM_PROMPT
        + "\n\n"
        + TONE_ADDONS.get(tone, TONE_ADDONS["builder"])
        + "\n\n"
        + NICHE_ADDONS.get(niche, NICHE_ADDONS["defi"])
    )


def _build_user_msg(topic: str, fmt: str, history: list) -> str:
    fmt_map = {
        "tweet":       "Write ONE single viral tweet. Optimal 220-260 chars but don't force it.",
        "thread":      "Write a viral thread of 6-9 tweets. End tweet 1 with 🧵, number the rest 2/ 3/ etc.",
        "hooks":       "Write 3 completely different hook variations for this topic. Label them:\n\n🎣 Hook A — [archetype name]\n🎣 Hook B — [archetype name]\n🎣 Hook C — [archetype name]\n\nEach should use a completely different psychological angle.",
        "thread_mini": "Write a 3-tweet mini-thread. Tight, punchy, zero filler. Each tweet must deliver standalone value.",
    }

    context = ""
    if history:
        recent = history[-3:]
        context = "\n\n⚠️ VARIETY NOTE — you recently covered these topics, approach from a fresh angle:\n"
        for h in recent:
            context += f"• {h.get('topic','')[:80]}\n"

    return (
        f"{fmt_map.get(fmt, fmt_map['tweet'])}\n\n"
        f"TOPIC / CONTEXT FROM USER:\n{topic}"
        f"{context}\n\n"
        "Now write the content. Follow ALL system instructions. Human voice only."
    )


def _call_deepseek(messages: list, temp: float = 0.88, max_tok: int = 2000) -> str:
    r = deepseek.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=temp,
        max_tokens=max_tok,
    )
    return r.choices[0].message.content.strip()


def _call_nvidia(messages: list, temp: float = 0.88, max_tok: int = 2000) -> str:
    r = nvidia.chat.completions.create(
        model="meta/llama-3.3-70b-instruct",
        messages=messages,
        temperature=temp,
        max_tokens=max_tok,
    )
    return r.choices[0].message.content.strip()


async def generate(
    topic: str,
    fmt: str,
    tone: str,
    niche: str,
    history: list,
    force: str = "auto",
) -> tuple:  # FIX: was tuple[str, str] — requires Python 3.10+; use plain tuple for 3.9 compat
    """Returns (content, model_label). Auto tries DeepSeek → NVIDIA fallback."""
    msgs = [
        {"role": "system", "content": _build_system(tone, niche)},
        {"role": "user",   "content": _build_user_msg(topic, fmt, history)},
    ]

    if force == "nvidia":
        content = await asyncio.to_thread(_call_nvidia, msgs)
        return content, "NVIDIA"

    if force == "deepseek":
        content = await asyncio.to_thread(_call_deepseek, msgs)
        return content, "DeepSeek"

    # auto: DeepSeek first, NVIDIA fallback
    try:
        content = await asyncio.to_thread(_call_deepseek, msgs)
        return content, "DeepSeek"
    except Exception as e:
        log.warning(f"DeepSeek failed ({e}), falling back to NVIDIA")
        content = await asyncio.to_thread(_call_nvidia, msgs)
        return content, "NVIDIA ↩️"


async def ai_edit(original: str, instruction: str) -> str:
    msgs = [
        {"role": "system", "content": EDIT_PROMPT},
        {"role": "user",   "content": f"ORIGINAL:\n{original}\n\nINSTRUCTION: {instruction}"},
    ]
    try:
        return await asyncio.to_thread(_call_deepseek, msgs, 0.8)
    except Exception:
        return await asyncio.to_thread(_call_nvidia, msgs, 0.8)


async def ai_score(content: str):  # FIX: was -> dict | None (Python 3.10+ syntax)
    msgs = [
        {"role": "system", "content": SCORE_PROMPT},
        {"role": "user",   "content": content},
    ]
    try:
        raw = await asyncio.to_thread(_call_deepseek, msgs, 0.2, 600)
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"Score parse error: {e}")
        return None


async def ai_suggest() -> list:
    msgs = [
        {"role": "system", "content": SUGGEST_PROMPT},
        {"role": "user",   "content": "Generate 8 high-potential Web3 content ideas for right now."},
    ]
    try:
        raw = await asyncio.to_thread(_call_deepseek, msgs, 0.92, 1400)
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        return json.loads(raw).get("topics", [])
    except Exception as e:
        log.error(f"Suggest error: {e}")
        return []


# ══════════════════════════════════════════════════════════════════════════════
# UI — KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════════

def kb_home():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ Settings",     callback_data="menu:settings"),
            InlineKeyboardButton("📚 History",      callback_data="menu:history"),
        ],
        [
            InlineKeyboardButton("💡 Topic Ideas",  callback_data="menu:suggest"),
            InlineKeyboardButton("❓ Help",          callback_data="menu:help"),
        ],
    ])


def kb_settings(prefs: dict):
    tone  = prefs.get("tone", "builder")
    niche = prefs.get("niche", "defi")
    fmt   = prefs.get("content_type", "tweet")

    def tone_row(keys):
        return [
            InlineKeyboardButton(
                ("✅ " if tone == k else "") + TONES[k],
                callback_data=f"set:tone:{k}"
            ) for k in keys
        ]

    def niche_row(keys):
        return [
            InlineKeyboardButton(
                ("✅ " if niche == k else "") + NICHES[k],
                callback_data=f"set:niche:{k}"
            ) for k in keys
        ]

    def fmt_row(keys):
        return [
            InlineKeyboardButton(
                ("✅ " if fmt == k else "") + FORMATS[k],
                callback_data=f"set:fmt:{k}"
            ) for k in keys
        ]

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("━━━━ TONE ━━━━", callback_data="noop")],
        tone_row(["builder", "degen", "alpha"]),
        tone_row(["educator", "controversial", "storyteller"]),
        [InlineKeyboardButton("━━━━ NICHE ━━━━", callback_data="noop")],
        niche_row(["defi", "nft", "l1l2", "trading"]),
        niche_row(["ai_web3", "memecoins", "dao", "gamefi"]),
        [InlineKeyboardButton("━━━━ FORMAT ━━━━", callback_data="noop")],
        fmt_row(["tweet", "thread"]),
        fmt_row(["hooks", "thread_mini"]),
        [InlineKeyboardButton("✅ Done", callback_data="menu:close")],
    ])


def kb_post(gen_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Score",         callback_data=f"score:{gen_id}"),
            InlineKeyboardButton("✏️ Edit",           callback_data=f"edit:{gen_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Redo DeepSeek", callback_data=f"redo:deepseek:{gen_id}"),
            InlineKeyboardButton("⚡ Redo NVIDIA",   callback_data=f"redo:nvidia:{gen_id}"),
        ],
        [
            InlineKeyboardButton("🎲 Alt Tone",      callback_data=f"alttone:{gen_id}"),
            InlineKeyboardButton("🧵 → Thread",      callback_data=f"tothread:{gen_id}"),
        ],
        [
            InlineKeyboardButton("🗑 Delete",         callback_data=f"delete:{gen_id}"),
            InlineKeyboardButton("🏠 Home",           callback_data="menu:home"),
        ],
    ])


def kb_score(gen_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚡ Apply Quick Fix", callback_data=f"quickfix:{gen_id}"),
            InlineKeyboardButton("✏️ Edit Manually",   callback_data=f"edit:{gen_id}"),
        ],
        [InlineKeyboardButton("🔙 Back to Post",       callback_data=f"backpost:{gen_id}")],
    ])


def kb_history(rows: list):
    buttons = []
    for r in rows[:8]:
        tone_label  = TONES.get(r["tone"], r["tone"])
        label = f"{tone_label} · {truncate(r['topic'], 28)}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"view:{r['id']}")])
    buttons.append([InlineKeyboardButton("🔙 Close", callback_data="menu:close")])
    return InlineKeyboardMarkup(buttons)


def kb_suggest(topics: list, offset: int = 0):
    buttons = []
    for i, t in enumerate(topics[offset:offset+8], start=offset+1):
        emoji = "🧵" if t.get("type") == "thread" else "✍️"
        buttons.append([InlineKeyboardButton(
            f"{emoji} #{i}: {truncate(t.get('title',''), 38)}",
            callback_data=f"usetopic:{i-1}"
        )])
    buttons.append([InlineKeyboardButton("🔄 Refresh Ideas", callback_data="menu:suggest")])
    return InlineKeyboardMarkup(buttons)


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_score(data: dict) -> str:
    if not data:
        return "❌ Scoring failed. Try again."

    s = data.get("scores", {})
    overall = data.get("overall", 0)

    def bar(n: float) -> str:
        n = max(0, min(10, int(n)))
        filled = round(n * 6 / 10)
        return "▓" * filled + "░" * (6 - filled) + f"  {n}/10"

    grade = (
        "🟢 *Strong*"      if overall >= 8  else
        "🟡 *Decent*"      if overall >= 6  else
        "🟠 *Needs work*"  if overall >= 4  else
        "🔴 *Weak*"
    )

    return (
        f"📊 *ENGAGEMENT SCORE*\n"
        f"{'─'*30}\n"
        f"`Hook strength   ` {bar(s.get('hook', 0))}\n"
        f"`Reply trigger   ` {bar(s.get('reply_potential', 0))}\n"
        f"`Bookmark value  ` {bar(s.get('bookmark_value', 0))}\n"
        f"`Repost chance   ` {bar(s.get('repost_potential', 0))}\n"
        f"`Algorithm fit   ` {bar(s.get('algo_fit', 0))}\n"
        f"`Authenticity    ` {bar(s.get('authenticity', 0))}\n"
        f"`Niche relevance ` {bar(s.get('niche_relevance', 0))}\n"
        f"`Timing          ` {bar(s.get('timing', 0))}\n"
        f"{'─'*30}\n"
        f"*Overall: {overall}/10 — {grade}*\n\n"
        f"💬 _{data.get('verdict', '')}_\n\n"
        # FIX: SCORE_PROMPT returns "strength"/"weakness" keys — matched here
        f"✅ *Best thing:* {data.get('strength', '')}\n"
        f"⚠️ *Weakness:* {data.get('weakness', '')}\n"
        f"⚡ *Quick fix:* _{data.get('quick_fix', '')}_"
    )


def fmt_suggest(topics: list) -> str:
    if not topics:
        return "❌ No ideas generated."
    lines = ["💡 *Fresh content ideas — right now:*\n"]
    for i, t in enumerate(topics, 1):
        emoji = "🧵" if t.get("type") == "thread" else "✍️"
        niche = NICHES.get(t.get("niche", ""), "")
        lines.append(
            f"*{i}.* {emoji} {niche} `{t.get('title', '')}`\n"
            f"Hook: _{t.get('hook', '')[:90]}_\n"
            f"Why: {t.get('why', '')[:80]}\n"
        )
    return "\n".join(lines)


def fmt_header(gen: dict, model_used: str) -> str:
    tone_label  = TONES.get(gen["tone"], gen["tone"])
    niche_label = NICHES.get(gen["niche"], gen["niche"])
    fmt_label   = FORMATS.get(gen["content_type"], gen["content_type"])
    topic_short = truncate(gen["topic"], 55)
    return (
        f"┌─ {tone_label}  {niche_label}  {fmt_label}\n"
        f"│  _{topic_short}_\n"
        f"│  via {model_used}\n"
        f"└{'─'*35}\n\n"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CORE GENERATION FLOW
# ══════════════════════════════════════════════════════════════════════════════

async def do_generate(
    send_to,
    typing_chat,
    topic: str,
    uid: int,
    force: str = "auto",
    override_fmt = None,   # FIX: was str | None — Python 3.10+ syntax; use None default only
    override_tone = None,  # FIX: same
):
    """Central generation function."""
    prefs   = db.get_prefs(uid)
    session = db.get_session(uid)

    fmt   = override_fmt  or prefs["content_type"]
    tone  = override_tone or prefs["tone"]
    niche = prefs["niche"]

    await typing_chat.send_action(ChatAction.TYPING)

    try:
        content, model_used = await generate(
            topic, fmt, tone, niche,
            session.get("context_history", []),
            force=force,
        )
    except Exception as e:
        log.error(f"Generation error: {e}")
        await send_to(f"❌ Generation failed: `{str(e)[:120]}`\n\nTry again or switch model.")
        return

    gen_id  = db.save_generation(topic, content, fmt, tone, niche, model_used)
    db.save_session(uid, last_topic=topic, last_content=content, last_gen_id=gen_id)

    gen_row = db.get_generation(gen_id)
    header  = fmt_header(gen_row, model_used)

    safe_content = safe_md(content)
    await send_to(header + safe_content, reply_markup=kb_post(gen_id))


# ══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Private bot.")
        return

    uid   = update.effective_user.id
    prefs = db.get_prefs(uid)
    count_hist = len(db.get_history(100))

    await update.message.reply_text(
        "🚀 *Web3 Viral Tweet Writer v3*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "The most intelligent Web3 content engine.\n\n"
        f"*Your settings:*\n"
        f"  Tone   →  {TONES.get(prefs['tone'])}\n"
        f"  Niche  →  {NICHES.get(prefs['niche'])}\n"
        f"  Format →  {FORMATS.get(prefs['content_type'])}\n"
        f"  Saved  →  {count_hist} generations\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "*Just send any topic to generate.*\n\n"
        "Or pick an option below:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_home(),
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    await update.message.reply_text(
        "📖 *Complete Guide*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🟢 Basic:*\n"
        "Send any topic → get viral content instantly\n\n"
        "*🔵 After generating:*\n"
        "📊 Score — 8-dim AI engagement score + quick fix\n"
        "✏️ Edit — natural language: 'make it shorter', 'add a stat'\n"
        "🔄 Redo — regenerate same topic, fresh output\n"
        "🎲 Alt Tone — same topic, next tone in rotation\n"
        "🧵 → Thread — expand any tweet to full thread\n"
        "🗑 Delete — remove from history\n\n"
        "*🟡 Settings (/settings):*\n"
        "6 Tones: Builder, Degen, Alpha, Educator, Controversial, Storyteller\n"
        "8 Niches: DeFi, NFT, L1/L2, Trading, AI×Web3, Memecoins, DAO, GameFi\n"
        "4 Formats: Tweet, Thread, 3 Hooks, Mini Thread\n\n"
        "*🟣 Pro tips:*\n"
        "• More context = better output\n"
        "• Score every post before publishing\n"
        "• /suggest gives 8 AI-generated topic ideas\n"
        "• Switch tones to see same topic in 6 voices\n"
        "• History saves everything — /history to browse",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    prefs = db.get_prefs(update.effective_user.id)
    await update.message.reply_text(
        "⚙️ *Settings*\n"
        "Tap to switch — ✅ marks your active selection.\n\n"
        "_Changes apply to your next generation._",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_settings(prefs),
    )


async def cmd_history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    rows = db.get_history(10)
    if not rows:
        await update.message.reply_text("📭 No generations yet. Send a topic to get started!")
        return
    await update.message.reply_text(
        f"📚 *Last {len(rows)} generations*\nTap any to view:\n",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_history(rows),
    )


async def cmd_suggest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    msg = await update.message.reply_text("💡 Generating ideas with AI...")
    await update.message.chat.send_action(ChatAction.TYPING)

    topics = await ai_suggest()
    if not topics:
        await safe_edit(msg, "❌ Couldn't generate ideas right now. Try again in a moment.")
        return

    ctx.bot_data["suggested_topics"] = topics
    await safe_edit(msg, fmt_suggest(topics), parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text(
        "Tap to generate from any idea 👇",
        reply_markup=kb_suggest(topics),
    )


# ══════════════════════════════════════════════════════════════════════════════
# MESSAGE HANDLER
# ══════════════════════════════════════════════════════════════════════════════

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Private bot.")
        return

    uid  = update.effective_user.id
    text = update.message.text.strip()

    session = db.get_session(uid)
    if session.get("edit_active"):
        await _handle_edit(update, uid, text, session)
        return

    prefs = db.get_prefs(uid)
    status = await update.message.reply_text(
        f"⚙️ _Generating {FORMATS.get(prefs['content_type'], 'content')}..._\n"
        f"_{TONES.get(prefs['tone'])} · {NICHES.get(prefs['niche'])}_",
        parse_mode=ParseMode.MARKDOWN,
    )

    async def send(text_out, reply_markup=None):
        await safe_delete(status)
        await update.message.reply_text(
            text_out,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
        )

    await do_generate(send, update.message.chat, text, uid)


async def _handle_edit(update: Update, uid: int, instruction: str, session: dict):
    gen_id   = session.get("edit_gen_id")
    original = session.get("edit_content", "")

    db.clear_edit_mode(uid)

    status = await update.message.reply_text("✏️ _Applying your changes..._", parse_mode=ParseMode.MARKDOWN)
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        revised = await ai_edit(original, instruction)
        gen = db.get_generation(gen_id) or {}
        new_id = db.save_generation(
            gen.get("topic", "edited"),
            revised,
            gen.get("content_type", "tweet"),
            gen.get("tone", "builder"),
            gen.get("niche", "defi"),
            "DeepSeek (edit)",
        )
        await safe_delete(status)
        await update.message.reply_text(
            safe_md(revised),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_post(new_id),
        )
    except Exception as e:
        await safe_edit(status, f"❌ Edit failed: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)


# ══════════════════════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════════════════════

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    uid = q.from_user.id

    if not is_admin(uid):
        await q.answer("⛔ Unauthorized.", show_alert=True)
        return

    await q.answer()
    data = q.data

    if data == "noop":
        return

    # ── MENU ─────────────────────────────────────────────────────────────────
    if data == "menu:home":
        await q.message.reply_text(
            "🏠 *Home*\n\nSend any topic to generate content.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_home(),
        )

    elif data == "menu:settings":
        prefs = db.get_prefs(uid)
        await q.message.reply_text(
            "⚙️ *Settings* — ✅ = active\n_Tap to switch. Changes apply instantly._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_settings(prefs),
        )

    elif data == "menu:history":
        rows = db.get_history(10)
        if not rows:
            await q.message.reply_text("📭 No history yet.")
            return
        await q.message.reply_text(
            f"📚 *Last {len(rows)} generations:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_history(rows),
        )

    elif data == "menu:suggest":
        loading = await q.message.reply_text("💡 _Generating fresh ideas..._", parse_mode=ParseMode.MARKDOWN)
        topics  = await ai_suggest()
        ctx.bot_data["suggested_topics"] = topics
        await safe_delete(loading)
        if not topics:
            await q.message.reply_text("❌ Couldn't generate ideas. Try again.")
            return
        await q.message.reply_text(fmt_suggest(topics), parse_mode=ParseMode.MARKDOWN)
        await q.message.reply_text("Tap to generate 👇", reply_markup=kb_suggest(topics))

    elif data == "menu:help":
        await q.message.reply_text(
            "📖 Send any topic to generate.\n\n"
            "After generating:\n"
            "📊 Score · ✏️ Edit · 🔄 Redo · 🎲 Alt Tone · 🧵 Thread\n\n"
            "/settings — tone, niche, format\n"
            "/suggest — AI topic ideas\n"
            "/history — past generations\n"
            "/help — full guide",
        )

    elif data == "menu:close":
        await safe_delete(q.message)

    # ── SETTINGS ─────────────────────────────────────────────────────────────
    elif data.startswith("set:tone:"):
        tone = data.split(":")[2]
        db.save_prefs(uid, tone=tone)
        prefs = db.get_prefs(uid)
        try:
            await q.edit_message_reply_markup(reply_markup=kb_settings(prefs))
        except BadRequest:
            pass

    elif data.startswith("set:niche:"):
        niche = data.split(":")[2]
        db.save_prefs(uid, niche=niche)
        prefs = db.get_prefs(uid)
        try:
            await q.edit_message_reply_markup(reply_markup=kb_settings(prefs))
        except BadRequest:
            pass

    elif data.startswith("set:fmt:"):
        fmt = data.split(":")[2]
        db.save_prefs(uid, content_type=fmt)
        prefs = db.get_prefs(uid)
        try:
            await q.edit_message_reply_markup(reply_markup=kb_settings(prefs))
        except BadRequest:
            pass

    # ── SCORE ────────────────────────────────────────────────────────────────
    elif data.startswith("score:"):
        gen_id = int(data.split(":")[1])
        gen = db.get_generation(gen_id)
        if not gen:
            await q.message.reply_text("❌ Generation not found.")
            return

        loading = await q.message.reply_text("📊 _Scoring your content..._", parse_mode=ParseMode.MARKDOWN)
        score_data = await ai_score(gen["content"])
        await safe_delete(loading)

        if score_data and score_data.get("overall"):
            db.update_score(gen_id, score_data["overall"])
            ctx.bot_data[f"score:{gen_id}"] = score_data

        await q.message.reply_text(
            fmt_score(score_data),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_score(gen_id),
        )

    # ── QUICK FIX ────────────────────────────────────────────────────────────
    elif data.startswith("quickfix:"):
        gen_id     = int(data.split(":")[1])
        gen        = db.get_generation(gen_id)
        score_data = ctx.bot_data.get(f"score:{gen_id}")

        if not gen:
            await q.message.reply_text("❌ Generation not found.")
            return
        if not score_data:
            await q.message.reply_text("⚠️ Please tap 📊 Score first, then Quick Fix.")
            return

        fix = score_data.get("quick_fix", "Strengthen the hook with a specific number or stat.")
        loading = await q.message.reply_text(
            f"⚡ _Applying fix:_ _{fix[:80]}_", parse_mode=ParseMode.MARKDOWN
        )
        await q.message.chat.send_action(ChatAction.TYPING)

        try:
            revised = await ai_edit(gen["content"], fix)
            new_id  = db.save_generation(
                gen["topic"], revised, gen["content_type"],
                gen["tone"], gen["niche"], "DeepSeek (quick fix)"
            )
            await safe_delete(loading)
            new_gen = db.get_generation(new_id)
            await q.message.reply_text(
                fmt_header(new_gen, "Quick Fix ⚡") + safe_md(revised),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_post(new_id),
            )
        except Exception as e:
            await safe_edit(loading, f"❌ Quick fix failed: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)

    # ── EDIT ─────────────────────────────────────────────────────────────────
    elif data.startswith("edit:"):
        gen_id = int(data.split(":")[1])
        gen    = db.get_generation(gen_id)
        if not gen:
            await q.message.reply_text("❌ Generation not found.")
            return

        db.set_edit_mode(uid, gen_id, gen["content"])
        await q.message.reply_text(
            "✏️ *Edit Mode*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Type your instruction and send it. Examples:\n\n"
            "• _make it shorter_\n"
            "• _more aggressive tone_\n"
            "• _add a specific stat about Ethereum TVL_\n"
            "• _rewrite the hook as a story opener_\n"
            "• _make it sound less like AI_\n"
            "• _turn this into a thread_\n"
            "• _add a forced-choice question at the end_\n\n"
            "Type your instruction now 👇",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── REDO ─────────────────────────────────────────────────────────────────
    elif data.startswith("redo:"):
        parts  = data.split(":")
        force  = parts[1]
        gen_id = int(parts[2])
        gen    = db.get_generation(gen_id)
        if not gen:
            await q.message.reply_text("❌ Generation not found.")
            return

        model_label = "DeepSeek" if force == "deepseek" else "NVIDIA"
        loading = await q.message.reply_text(f"🔄 _Regenerating with {model_label}..._", parse_mode=ParseMode.MARKDOWN)
        await q.message.chat.send_action(ChatAction.TYPING)

        async def send(text_out, reply_markup=None):
            await safe_delete(loading)
            await q.message.reply_text(text_out, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        await do_generate(
            send, q.message.chat, gen["topic"], uid,
            force=force,
            override_fmt=gen["content_type"],
            override_tone=gen["tone"],
        )

    # ── ALT TONE ─────────────────────────────────────────────────────────────
    elif data.startswith("alttone:"):
        gen_id = int(data.split(":")[1])
        gen    = db.get_generation(gen_id)
        if not gen:
            await q.message.reply_text("❌ Generation not found.")
            return

        cur_idx   = TONE_LIST.index(gen["tone"]) if gen["tone"] in TONE_LIST else 0
        next_tone = TONE_LIST[(cur_idx + 1) % len(TONE_LIST)]
        tone_lbl  = TONES[next_tone]

        loading = await q.message.reply_text(
            f"🎲 _Rewriting in {tone_lbl} voice..._", parse_mode=ParseMode.MARKDOWN
        )
        await q.message.chat.send_action(ChatAction.TYPING)

        async def send(text_out, reply_markup=None):
            await safe_delete(loading)
            await q.message.reply_text(text_out, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        await do_generate(
            send, q.message.chat, gen["topic"], uid,
            override_fmt=gen["content_type"],
            override_tone=next_tone,
        )

    # ── TO THREAD ─────────────────────────────────────────────────────────────
    elif data.startswith("tothread:"):
        gen_id = int(data.split(":")[1])
        gen    = db.get_generation(gen_id)
        if not gen:
            await q.message.reply_text("❌ Generation not found.")
            return

        loading = await q.message.reply_text("🧵 _Expanding to thread..._", parse_mode=ParseMode.MARKDOWN)
        await q.message.chat.send_action(ChatAction.TYPING)

        expanded_topic = (
            f"Expand this into a full 6-9 tweet viral thread. "
            f"Original topic: {gen['topic']}\n\n"
            f"Original content to build from:\n{gen['content'][:400]}"
        )

        async def send(text_out, reply_markup=None):
            await safe_delete(loading)
            await q.message.reply_text(text_out, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        await do_generate(
            send, q.message.chat, expanded_topic, uid,
            override_fmt="thread",
            override_tone=gen["tone"],
        )

    # ── VIEW HISTORY ITEM ────────────────────────────────────────────────────
    elif data.startswith("view:"):
        gen_id = int(data.split(":")[1])
        gen    = db.get_generation(gen_id)
        if not gen:
            await q.message.reply_text("❌ Not found.")
            return

        created   = str(gen.get("created_at", ""))[:16]
        score_str = f" · ⭐ {gen['score']:.1f}/10" if gen.get("score") else ""

        header = (
            f"📅 _{created}{score_str}_\n"
            + fmt_header(gen, gen.get("model_used", "AI"))
        )
        await q.message.reply_text(
            header + safe_md(gen["content"]),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_post(gen_id),
        )

    # ── USE SUGGESTED TOPIC ──────────────────────────────────────────────────
    elif data.startswith("usetopic:"):
        idx    = int(data.split(":")[1])
        topics = ctx.bot_data.get("suggested_topics", [])
        if not topics or idx >= len(topics):
            await q.message.reply_text("⚠️ Topics expired. Use /suggest to refresh.")
            return

        t     = topics[idx]
        topic = t.get("hook") or t.get("title", "")
        niche = t.get("niche", "defi")
        db.save_prefs(uid, niche=niche)

        loading = await q.message.reply_text(
            f"⚙️ _Generating from idea #{idx+1}..._", parse_mode=ParseMode.MARKDOWN
        )
        await q.message.chat.send_action(ChatAction.TYPING)

        async def send(text_out, reply_markup=None):
            await safe_delete(loading)
            await q.message.reply_text(text_out, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

        await do_generate(send, q.message.chat, topic, uid)

    # ── DELETE ───────────────────────────────────────────────────────────────
    elif data.startswith("delete:"):
        gen_id = int(data.split(":")[1])
        db.delete_generation(gen_id)
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
        await q.answer("🗑 Deleted.", show_alert=False)

    # ── BACK TO POST ─────────────────────────────────────────────────────────
    elif data.startswith("backpost:"):
        gen_id = int(data.split(":")[1])
        gen    = db.get_generation(gen_id)
        if not gen:
            return
        await q.message.reply_text(
            fmt_header(gen, gen.get("model_used", "AI")) + safe_md(gen["content"]),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_post(gen_id),
        )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    log.info("Connecting to MySQL...")
    db.init_db()
    log.info("✅ Database ready.")

    log.info("Starting Web3 Tweet Writer v3...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("history",  cmd_history))
    app.add_handler(CommandHandler("suggest",  cmd_suggest))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("✅ Bot running — waiting for messages.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
