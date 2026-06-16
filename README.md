# Web3 Viral Tweet Writer v2 — Advanced Telegram Bot

The most advanced Web3 content generation bot. 6 tones, 8 niches, AI scoring, edit mode, history, topic suggestions, and context memory.

---

## What's New in v2

| Feature | v1 | v2 |
|---|---|---|
| Tones | ❌ | ✅ 6 tones (Builder, Degen, Alpha, Educator, Controversial, Storyteller) |
| Niches | ❌ | ✅ 8 niches (DeFi, NFT, L1/L2, Trading, AI×Web3, Memecoins, DAO, GameFi) |
| Formats | 2 | 4 (Tweet, Thread, 3 Hooks, Mini Thread) |
| AI Scoring | ❌ | ✅ 8-dimension engagement score with quick fix |
| Edit Mode | ❌ | ✅ Natural language editing ("make it shorter", "add a stat") |
| Content History | ❌ | ✅ SQLite, browse/reuse past generations |
| Topic Suggestions | ❌ | ✅ AI-generated hot topic ideas |
| Context Memory | ❌ | ✅ Remembers last 5 generations for variety |
| Alt Tone | ❌ | ✅ Try same topic in a different voice |
| Expand to Thread | ❌ | ✅ Turn any tweet into a thread |
| Training Data | Basic | Massive (50+ viral examples, 10 sections) |
| System Prompt | ~500 chars | ~8,000 chars of expert Web3 knowledge |

---

## File Structure

```
tweet_bot/
├── bot.py          ← Main bot (handlers, callbacks, logic)
├── prompts.py      ← Massive system prompt + training data
├── database.py     ← SQLite layer (history, prefs, sessions)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Setup

### 1. Install
```bash
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env with your values
```

### 3. Run
```bash
export $(cat .env | xargs)
python bot.py
```

---

## Environment Variables

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_user_id
DEEPSEEK_API_KEY=your_deepseek_key
NVIDIA_API_KEY=your_nvidia_key
DB_PATH=tweet_bot.db          # optional, default: tweet_bot.db
```

---

## Commands

| Command | What it does |
|---|---|
| `/start` | Welcome + current settings |
| `/settings` | Change tone, niche, format (interactive) |
| `/suggest` | AI-generated topic ideas with 1-tap generation |
| `/history` | Browse past generations |
| `/help` | Full usage guide |

---

## How to Use

### Basic flow
1. `/settings` → pick your tone, niche, format
2. Send any topic, idea, or context
3. Get ready-to-post content

### Pro flow
1. Send topic → get content
2. Tap **📊 Score It** → see 8-dimension score + quick fix
3. Tap **Apply Quick Fix** → auto-improve
4. Tap **✏️ Edit** → type "make it shorter" or any instruction
5. Tap **🎲 Try Different Tone** → see same topic from another voice

### When you're stuck
- `/suggest` → get 8 AI-generated hot topic ideas
- Tap any idea → generates instantly with your current settings

---

## Tones Explained

| Tone | Personality | Best for |
|---|---|---|
| 🏗️ Builder | Shipping products, authentic failures | Project updates, builder lessons |
| 🎲 Degen | Trader energy, CT slang, high-conviction | Calls, trading, market takes |
| 🔍 Alpha | On-chain research, data-backed insights | Protocol analysis, whale watching |
| 📚 Educator | Complex → simple, no jargon | Explaining DeFi, onboarding content |
| 🔥 Controversial | Defensible hot takes, challenges consensus | Opinion pieces, debate starters |
| 📖 Storyteller | Narrative arc, emotional, personal | Personal stories, lessons learned |

---

## Niches Explained

| Niche | Target audience |
|---|---|
| 💰 DeFi | LP providers, yield farmers, protocol users |
| 🖼️ NFT | Collectors, artists, community builders |
| ⚙️ L1/L2 | Developers, infrastructure investors |
| 📈 Trading | Active traders, TA practitioners |
| 🤖 AI×Web3 | AI + crypto intersection builders/investors |
| 🐸 Memecoins | Degens, community participants |
| 🗳️ DAO | Governance participants, contributors |
| 🎮 GameFi | Gamers, game devs, play-to-earn vets |

---

## Scoring System

After generating content, tap **📊 Score It** to get:
- Hook strength (0-10)
- Reply potential (0-10)
- Bookmark value (0-10)
- Repost potential (0-10)
- Algo fit for 2026 X algorithm (0-10)
- Human authenticity (0-10)
- Niche relevance (0-10)
- Timing relevance (0-10)
- Overall verdict + top strength + top weakness
- **Quick Fix**: one specific change that adds +10-15% performance

---

## Running 24/7

### screen
```bash
screen -S tweetbot
export $(cat .env | xargs)
python bot.py
# Ctrl+A, D to detach
# screen -r tweetbot to reattach
```

### systemd (recommended for VPS)
```ini
# /etc/systemd/system/tweetbot.service
[Unit]
Description=Web3 Tweet Writer Bot v2
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/path/to/tweet_bot
EnvironmentFile=/path/to/tweet_bot/.env
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tweetbot
sudo systemctl start tweetbot
sudo systemctl status tweetbot
sudo journalctl -u tweetbot -f   # live logs
```

---

## Security

- Never commit `.env` to git
- Add to `.gitignore`: `.env`, `tweet_bot.db`
- Rotate your API keys — they should never appear in code or documents
```
