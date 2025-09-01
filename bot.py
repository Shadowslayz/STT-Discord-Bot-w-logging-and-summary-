import os
import io
import discord
from discord import app_commands
from openai import OpenAI
from datetime import datetime, timezone
from dotenv import load_dotenv
from config import DISCORDTOKEN, OPENAPIAPIKEY

# ---------- CONFIG ----------
load_dotenv()
DISCORD_TOKEN = DISCORDTOKEN
OPENAI_API_KEY = OPENAPIAPIKEY

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

# ---------- Chunking Helper ----------
def chunk_text(text, max_chars=6000):
    """Split transcript into smaller chunks under max_chars each."""
    chunks, current = [], []
    length = 0
    for line in text.splitlines():
        if length + len(line) > max_chars:
            chunks.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line)
    if current:
        chunks.append("\n".join(current))
    return chunks

# ---------- Summarization ----------
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

def summarize_large_transcript(full_transcript: str) -> str:
    # 1. Break transcript into chunks
    chunks = chunk_text(full_transcript)

    # 2. Summarize each chunk
    chunk_summaries = []
    for i, chunk in enumerate(chunks, 1):
        summary = summarize_text(chunk)
        chunk_summaries.append(f"--- Chunk {i} ---\n{summary}")

    # 3. Combine summaries into one and do a "summary of summaries"
    combined = "\n\n".join(chunk_summaries)
    final_summary = summarize_text("These are summaries of transcript chunks:\n\n" + combined)

    return final_summary

# ---------- Events ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()  # global sync
        print(f"✅ Synced {len(synced)} global command(s)")
    except Exception as e:
        print(f"⚠️ Failed to sync commands: {e}")

# ---------- Slash Command ----------
@tree.command(name="summarize", description="Summarize today's SeaVoice logs into meeting notes")
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
    summary = summarize_large_transcript(full_transcript)

    # ✅ If summary is too long, send as a file
    if len(summary) > 2000:
        file = discord.File(
            io.BytesIO(summary.encode("utf-8")),
            filename=f"meeting_summary_{now.strftime('%Y-%m-%d')}.txt"
        )
        await interaction.followup.send(
            content="📋 **Meeting Summary (Today):** Attached as file (too long for chat).",
            file=file
        )
    else:
        await interaction.followup.send(f"📋 **Meeting Summary (Today):**\n{summary}")

# ---------- RUN ----------
bot.run(DISCORD_TOKEN)
