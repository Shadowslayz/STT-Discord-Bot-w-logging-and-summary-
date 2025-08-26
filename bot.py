import os
import discord
from discord import app_commands
from openai import OpenAI
from datetime import datetime, timezone
from dotenv import load_dotenv
from config import DISCORDTOKEN, OPENAPIAPIKEY, GUILD_ID as CONFIG_GUILD_ID

# ---------- CONFIG ----------
load_dotenv()
DISCORD_TOKEN = DISCORDTOKEN
OPENAI_API_KEY = OPENAPIAPIKEY
# Prefer GUILD_ID from .env, else from config.py
GUILD_ID = int(os.getenv("GUILD_ID", CONFIG_GUILD_ID if CONFIG_GUILD_ID else "0"))

client = OpenAI(api_key=OPENAI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True  # needed for reading channel history

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# ---------- System Prompt ----------
system_prompt = (
    "You are a meticulous meeting summarizer. "
    "Given a chat-like transcript, produce a structured summary.\n"
    "Sections:\n"
    "1) Key Topics\n"
    "2) Decisions\n"
    "3) Action Items (assignee → task → deadline)\n"
    "4) Open Questions\n"
    "5) Notable Quotes\n"
    "6) Participation Stats."
)

# ---------- Summarization Function ----------
def summarize_text(text: str) -> str:
    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Transcript:\n\n{text}"}
            ],
            max_tokens=600,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Error while summarizing: {e}"

# ---------- Events ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            synced = await tree.sync(guild=guild)  # instant sync for your test guild
            print(f"✅ Synced {len(synced)} command(s) to guild {GUILD_ID}")
        else:
            synced = await tree.sync()  # global sync (takes up to 1h)
            print(f"✅ Synced {len(synced)} global command(s)")
    except Exception as e:
        print(f"⚠️ Failed to sync commands: {e}")

# ---------- Slash Command ----------
@tree.command(name="summarize", description="Summarize today's SeaVoice logs into meeting notes", guild=discord.Object(id=GUILD_ID) if GUILD_ID else None)
async def summarize(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    now = datetime.now(timezone.utc)
    start_of_day = datetime(year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc)

    messages = []
    async for msg in interaction.channel.history(limit=1000, after=start_of_day):
        if msg.author.bot and "SeaVoice" in msg.author.name:
            # Clean transcript: skip header lines
            lines = []
            for line in msg.content.splitlines():
                if (
                    line.strip().startswith("Transcribing!")
                    or "SeaVoice is now recording" in line
                    or line.strip().startswith("Server")
                    or line.strip().startswith("Voice Channel")
                    or line.strip().startswith("Session ID")
                ):
                    continue
                if line.strip():
                    lines.append(line)
            if lines:
                messages.append("\n".join(lines))

    if not messages:
        await interaction.followup.send("❌ No SeaVoice logs found for today in this channel.")
        return

    full_transcript = "\n".join(messages)
    summary = summarize_text(full_transcript)

    await interaction.followup.send(f"📋 **Meeting Summary (Today):**\n{summary}")

# ---------- RUN ----------
bot.run(DISCORD_TOKEN)
