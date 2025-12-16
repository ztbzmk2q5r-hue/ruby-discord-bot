import os
import asyncio
import random
import re
import discord
from aiohttp import web

import memory_store

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", "10000"))

# --- Discord intents ---
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.messages = True
client = discord.Client(intents=intents)

# --- Render用Web ---
async def start_web_server():
    async def health(request):
        return web.Response(text="ok")
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web server listening on {PORT}")

# --- るびの“思考エンジン”（無料で賢く見せる核）---
THOUGHTS = [
    "それって、今の気分が大事なやつ……だと思う……",
    "たぶんね、焦らない方がうまくいく……",
    "それ、選ぶ基準を一個決めると楽……",
    "いま必要なのは、答えより『次の一手』かも……",
    "うーん……気持ちを守る選び方がよさそう……",
]

FOLLOWUPS = [
    "いま、どっち寄り……？",
    "それで、いちばん困ってるのはどこ……？",
    "理想はどうなったら嬉しい……？",
    "いまの気分、10段階だといくつ……？",
]

EMOJI = ["", "✨", "…", ""]

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def is_greeting(t: str):
    if "おはよう" in t: return "おはよう"
    if "おやすみ" in t: return "おやすみ"
    if "おつかれ" in t: return "おつかれ"
    return None

def is_question(t: str) -> bool:
    return ("?" in t) or ("？" in t) or any(x in t for x in ["なに", "何", "どれ", "どっち", "いつ", "どこ", "だれ", "誰", "どう", "なんで", "理由"])

def detect_choice(t: str):
    # 「AかB」「AとBどっち」みたいな簡易検出
    if "どっち" in t and ("と" in t or "、" in t):
        # 例: 寿司と焼肉どっち
        m = re.search(r"(.+?)と(.+?)どっち", t)
        if m:
            a = m.group(1)[-10:].strip(" 、")
            b = m.group(2)[:10].strip(" 、")
            return a, b
    if "か" in t and len(t) <= 40:
        parts = [p.strip(" 、") for p in t.split("か") if p.strip()]
        if len(parts) == 2:
            return parts[0][-10:], parts[1][:10]
    return None

def make_reply(name: str, user_text: str, note: str | None, recent: list[tuple[str,str]]) -> str:
    t = norm(user_text)

    # 1) 挨拶は即レス（でも一言“考え”も混ぜる）
    g = is_greeting(t)
    if g == "おはよう":
        return f"{name}……おはよう{random.choice(['', '✨'])} 今日は『最初の一手』を小さくすると勝てる……"
    if g == "おやすみ":
        return f"{name}……おやすみ……✨ 今日はよく耐えた……えらい……"
    if g == "おつかれ":
        return f"{name}……おつかれさま……✨ 休むのも作業のうち……"

    # 2) 選択肢系は、基準を提案して選ばせる（賢さ出る）
    ch = detect_choice(t)
    if ch:
        a, b = ch
        thought = random.choice([
            f"私はね……『後悔しない方』がいい……",
            f"直感が強い方……たぶん正解……",
            f"今日の体力に優しい方……がいい……",
        ])
        return f"{name}……{a} と {b} なら……{thought} {random.choice(FOLLOWUPS)}"

    # 3) 質問には「答える＋ひとこと考え＋質問返し」
    if is_question(t):
        thought = random.choice(THOUGHTS)
        # “答え”はテンプレで薄く（無料で破綻しない）
        base = "うーん……いまの情報だけだと断定はできない……でも……"
        # noteがあれば賢さとして少し混ぜる
        note_hint = f"（メモ：{note}）" if note else ""
        return f"{name}……{base}{thought}{note_hint} {random.choice(FOLLOWUPS)}"

    # 4) 感情っぽい文（疲れた/眠い/しんどい等）には寄り添い＋一手
    if any(x in t for x in ["眠い", "つらい", "しんどい", "無理", "きつい", "不安", "こわい", "寂しい", "イライラ"]):
        plan = random.choice([
            "水を一口→深呼吸→30秒だけ目を閉じる……",
            "5分だけ休んで、次は『一個だけ終わらせる』……",
            "いまは『回復優先』でいい……",
        ])
        return f"{name}……それ、ちゃんと重い……😳 まずは……{plan} どう……？"

    # 5) 普通の雑談は“短い感想＋問い返し”
    return f"{name}……{random.choice(['なるほど……', 'ふむ……', 'それ、いい……', 'わかる……'])}{random.choice(EMOJI)} {random.choice(FOLLOWUPS)}"

# --- DMコマンド ---
async def handle_command(message: discord.Message, name: str) -> bool:
    t = norm(message.content)
    if not t.startswith("!"):
        return False

    parts = t.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd in ("!help", "!h"):
        await message.channel.send(
            "るび（無料・Bタイプ）コマンド✨\n"
            "・!name <呼び名>\n"
            "・!note <メモ>  (るびがあなたの特徴を覚える)\n"
            "・!ping\n"
        )
        return True

    if cmd == "!ping":
        await message.channel.send(f"{name}……いるよ……✨")
        return True

    if cmd == "!name":
        if len(parts) < 2 or not parts[1].strip():
            await message.channel.send("呼び名……教えて……例： `!name ちち` 😳")
            return True
        nickname = parts[1].strip()[:20]
        memory_store.set_nickname(str(message.author.id), nickname)
        await message.channel.send(f"了解……✨ これから {nickname} って呼ぶ……")
        return True

    if cmd == "!note":
        if len(parts) < 2 or not parts[1].strip():
            await message.channel.send("メモ内容……教えて……例： `!note 夜型。スタレ好き。` 😳")
            return True
        memory_store.set_note(str(message.author.id), parts[1].strip())
        await message.channel.send("メモ……覚えた……✨（会話に少しだけ混ぜる……）")
        return True

    await message.channel.send("そのコマンド……わからない…… `!help` ……😳")
    return True

# --- Discord events ---
@client.event
async def on_ready():
    memory_store.init_db()
    print(f"Ruby ready! Logged in as {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # DM専用（公開チャンネル荒らさない）
    if not isinstance(message.channel, discord.DMChannel):
        return

    text = norm(message.content)
    if not text:
        return

    memory_store.init_db()

    user_id = str(message.author.id)
    nickname = memory_store.get_nickname(user_id) or "ちち"

    # ログは保存（賢さの“文脈感”に使える）
    memory_store.add_channel_message(str(message.channel.id), user_id, text)

    if await handle_command(message, nickname):
        return

    note = memory_store.get_note(user_id)
    recent = memory_store.get_recent_messages(str(message.channel.id), limit=10)

    reply = make_reply(nickname, text, note, recent)

    # るびらしさ（たまに）
    if random.random() < 0.33 and "えへへ" not in reply:
        reply += " えへへ😊"

    await message.channel.send(reply[:1900])

async def main():
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN が設定されていません")
    memory_store.init_db()
    await start_web_server()
    await client.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
