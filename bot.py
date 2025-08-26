import os
import io
import re
import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List

import discord
from discord.ext import tasks, commands
from discord import app_commands

from dotenv import load_dotenv
from vosk import Model, KaldiRecognizer
from pydub import AudioSegment

# OpenAI (v1)
from openai import OpenAI

# ========= CONFIG / SECRETS =========
# You can put these in a config.py or in .env
try:
    from config import DISCORDTOKEN as DISCORD_BOT_TOKEN, OPENAPIAPIKEY as OPENAI_API_KEY
except Exception:
    load_dotenv()
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

def _clean_token(t: str) -> str:
    t = (t or "").strip()
    return t[4:].strip() if t.lower().startswith("bot ") else t

TOKEN = _clean_token(DISCORD_BOT_TOKEN)
if not TOKEN or not re.match(r'^[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{20,}$', TOKEN or ""):
    raise SystemExit("Discord bot token missing/malformed. Get it from Developer Portal → Bot → Reset Token.")

# Safer Windows path (avoid \v escape)
MODEL_PATH = os.path.join("models", "vosk-model-en-us-0.42-gigaspeech")
OPENAI_MODEL = "gpt-4o-mini"

# Point PyDub to local ffmpeg/ffprobe if they’re in the same folder as bot.py
AudioSegment.converter = os.path.join(os.getcwd(), "ffmpeg.exe")
AudioSegment.ffprobe   = os.path.join(os.getcwd(), "ffprobe.exe")

# ========= INTENTS / BOT =========
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ========= GLOBALS / STATE =========
stt_model: Optional[Model] = None
is_logging = False
log_folder = "logs"
cfg_path = "guild_config.json"
os.makedirs(log_folder, exist_ok=True)

CHUNK_SECONDS = 60
MAX_LOG_LINES_TO_SUMMARIZE = 800

# Single active server lock
ACTIVE_GUILD_ID: Optional[int] = None
LAST_ACTIVITY: Optional[datetime] = None
SESSION_TIMEOUT_SECONDS = 30 * 60  # 30 minutes

# Per-guild config:
# { "<guild_id>": { "text_channel_id": int|None, "voice_channel_id": int|None, "use_nicknames": True } }
guild_config = {}

# ========= CONFIG PERSIST =========
def load_config():
    global guild_config
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                guild_config = json.load(f)
        except Exception:
            guild_config = {}
    else:
        guild_config = {}

def save_config():
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(guild_config, f, indent=2)
    except Exception as e:
        print(f"[config save error]: {e}")

def get_guild_cfg(guild_id: int) -> dict:
    g = guild_config.get(str(guild_id))
    if not g:
        g = {"text_channel_id": None, "voice_channel_id": None, "use_nicknames": True}
        guild_config[str(guild_id)] = g
    return g

def channel_allowed(inter: discord.Interaction) -> bool:
    g = get_guild_cfg(inter.guild.id)
    allowed_id = g.get("text_channel_id")
    return (allowed_id is None) or (inter.channel.id == allowed_id)

# ========= SESSION HELPERS =========
def session_claimable() -> bool:
    global ACTIVE_GUILD_ID, LAST_ACTIVITY
    if ACTIVE_GUILD_ID is None:
        return True
    if LAST_ACTIVITY and (datetime.utcnow() - LAST_ACTIVITY).total_seconds() > SESSION_TIMEOUT_SECONDS:
        return True
    return False

def touch_activity(guild_id: int):
    global ACTIVE_GUILD_ID, LAST_ACTIVITY
    ACTIVE_GUILD_ID = guild_id
    LAST_ACTIVITY = datetime.utcnow()

def release_session():
    global ACTIVE_GUILD_ID, LAST_ACTIVITY, is_logging
    ACTIVE_GUILD_ID = None
    LAST_ACTIVITY = None
    is_logging = False

def busy_message() -> str:
    return "⛔ I'm claimed by another server (single active server). Ask them to `/release` or wait for idle timeout."

# ========= STT HELPERS =========
def load_vosk_model():
    global stt_model
    if stt_model is None:
        if not os.path.isdir(MODEL_PATH):
            raise RuntimeError(f"Vosk model not found at: {MODEL_PATH}")
        stt_model = Model(MODEL_PATH)

def wav_bytes_to_text(wav_bytes: bytes) -> str:
    load_vosk_model()
    audio = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    raw = audio.raw_data

    rec = KaldiRecognizer(stt_model, 16000)
    rec.SetWords(True)

    chunk_size = 4000
    for i in range(0, len(raw), chunk_size):
        rec.AcceptWaveform(raw[i:i+chunk_size])

    try:
        data = json.loads(rec.FinalResult())
        return data.get("text", "").strip()
    except Exception:
        return ""

def speaker_name(member: discord.Member, use_nick: bool) -> str:
    return member.display_name if (use_nick and getattr(member, "display_name", None)) else member.name

def log_line(guild_id: int, content: str):
    if not content.strip():
        return
    dt = datetime.utcnow().strftime("%Y-%m-%d")
    path = os.path.join(log_folder, f"{guild_id}-{dt}.log")
    with open(path, "a", encoding="utf-8") as f:
        timestamp = datetime.utcnow().strftime("%H:%M:%S")
        f.write(f"[{timestamp} UTC] {content}\n")

def log_path_for_date(guild_id: int, date_str: str) -> str:
    return os.path.join(log_folder, f"{guild_id}-{date_str}.log")

def read_log_lines(path: str, max_lines: int = MAX_LOG_LINES_TO_SUMMARIZE) -> List[str]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return lines[-max_lines:] if len(lines) > max_lines else lines

async def ensure_in_user_voice(inter: discord.Interaction, target_vc: Optional[discord.VoiceChannel]) -> Optional[discord.VoiceClient]:
    if target_vc is None:
        if inter.user and isinstance(inter.user, discord.Member) and inter.user.voice and inter.user.voice.channel:
            target_vc = inter.user.voice.channel
        else:
            await inter.response.send_message("Join a voice channel or pass one to `/join`.", ephemeral=True)
            return None

    if inter.guild.voice_client and inter.guild.voice_client.is_connected():
        if inter.guild.voice_client.channel.id != target_vc.id:
            await inter.guild.voice_client.move_to(target_vc)
        return inter.guild.voice_client

    return await target_vc.connect(cls=discord.VoiceClient)

# ========= RECORDING LOOP (Py-Cord sinks) =========
async def _start_recording(vc: discord.VoiceClient, guild: discord.Guild):
    sink = discord.sinks.WaveSink()

    def finished_callback(sink, *args):
        g = get_guild_cfg(guild.id)
        use_nick = g.get("use_nicknames", True)
        for user, audio in sink.audio_data.items():
            try:
                wav_bytes = audio.file.getvalue()
                text = wav_bytes_to_text(wav_bytes)
                if text:
                    name = speaker_name(user, use_nick)
                    log_line(guild.id, f"{name} ({user.id}): {text}")
            except Exception as e:
                log_line(guild.id, f"[STT error for {getattr(user, 'name', 'Unknown')}]: {e}")

    try:
        vc.start_recording(sink, finished_callback)
    except Exception as e:
        log_line(guild.id, f"[start_recording error]: {e}")
        return

    await asyncio.sleep(CHUNK_SECONDS)
    if vc.recording:
        vc.stop_recording()

@tasks.loop(seconds=2.0)
async def recorder_loop():
    if not is_logging or ACTIVE_GUILD_ID is None:
        return
    for vc in bot.voice_clients:
        if vc.is_connected() and vc.guild and vc.guild.id == ACTIVE_GUILD_ID:
            try:
                if not getattr(vc, "recording", False):
                    await _start_recording(vc, vc.guild)
            except Exception as e:
                log_line(vc.guild.id, f"[recorder_loop error]: {e}")

# ========= OpenAI SUMMARY =========
def summarize_text_with_openai(lines: List[str], date_str: str, guild_name: str) -> str:
    if not OPENAI_API_KEY:
        return "❌ OPENAI_API_KEY is not set."
    client = OpenAI(api_key=OPENAI_API_KEY)

    trimmed = []
    for ln in lines:
        ln = ln.strip()
        if len(ln) > 1000:
            ln = ln[:1000] + " …"
        trimmed.append(ln)
    transcript = "\n".join(trimmed[-MAX_LOG_LINES_TO_SUMMARIZE:])

    system = (
        "You are a meticulous meeting notes assistant. "
        "Given a timestamped chat-like transcript, produce a crisp, faithful summary.\n"
        "Sections: 1) Key Topics 2) Decisions 3) Action Items (assignee → task → deadline) "
        "4) Open Questions 5) Notable Quotes (short) 6) Participation Stats (approx per speaker). "
        "Be concise and do not invent facts."
    )
    user = f"Server: {guild_name}\nDate (UTC): {date_str}\nTranscript:\n---BEGIN---\n{transcript}\n---END---"

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.2,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"❌ OpenAI error: {e}"

# ========= EVENTS =========
@bot.event
async def on_ready():
    load_config()
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("Guilds I'm in:")
    for g in bot.guilds:
        print(f"- {g.name} (ID: {g.id})")

    # Instant: copy global commands into each guild & sync
    try:
        print("Commands discovered at import:", [c.name for c in tree.get_commands()])
        total = 0
        for g in bot.guilds:
            guild_obj = discord.Object(id=g.id)
            tree.copy_global_to(guild=guild_obj)
            synced = await tree.sync(guild=guild_obj)
            print(f"✅ Synced {len(synced)} commands to guild {g.id} ({g.name})")
            total += len(synced)
        if total == 0:
            print("ℹ️ Still 0? Then your decorators didn’t execute.")
    except Exception as e:
        print(f"❌ Guild sync failed: {e}")

    recorder_loop.start()

# ========= ADMIN: sync here on demand =========
@tree.command(name="sync_here", description="Admin: sync slash commands to THIS server")
@app_commands.default_permissions(administrator=True)
async def sync_here(inter: discord.Interaction):
    try:
        guild_obj = discord.Object(id=inter.guild.id)
        tree.copy_global_to(guild=guild_obj)
        synced = await tree.sync(guild=guild_obj)
        await inter.response.send_message(f"✅ Synced {len(synced)} commands to this guild.", ephemeral=True)
    except Exception as e:
        await inter.response.send_message(f"❌ Sync failed here: {e}", ephemeral=True)

# ========= SLASH COMMANDS (GLOBAL definitions) =========
def _block_if_busy(inter: discord.Interaction) -> bool:
    if ACTIVE_GUILD_ID is None:
        return False
    if ACTIVE_GUILD_ID == inter.guild_id:
        return False
    if session_claimable():
        return False
    return True

# Claim/release
@tree.command(name="claim", description="Claim the bot for this server (single active server).")
@app_commands.default_permissions(manage_guild=True)
async def claim(inter: discord.Interaction):
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    global ACTIVE_GUILD_ID
    if ACTIVE_GUILD_ID is None or session_claimable():
        touch_activity(inter.guild.id)
        await inter.response.send_message(f"✅ Session claimed for **{inter.guild.name}** (idle timeout {SESSION_TIMEOUT_SECONDS//60} min).")
    elif ACTIVE_GUILD_ID == inter.guild.id:
        touch_activity(inter.guild.id)
        await inter.response.send_message("✅ You already own the session; refreshed the timer.")
    else:
        await inter.response.send_message(busy_message(), ephemeral=True)

@tree.command(name="release", description="Release this server's claim so another server can use the bot.")
@app_commands.default_permissions(manage_guild=True)
async def release(inter: discord.Interaction):
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    if ACTIVE_GUILD_ID in (None, inter.guild_id) or session_claimable():
        if inter.guild.voice_client and getattr(inter.guild.voice_client, "recording", False):
            inter.guild.voice_client.stop_recording()
        if inter.guild.voice_client and inter.guild.voice_client.is_connected():
            await inter.guild.voice_client.disconnect()
        release_session()
        await inter.response.send_message("🟢 Session released. Any server can now `/claim` or `/join`.")
    else:
        await inter.response.send_message(busy_message(), ephemeral=True)

# Config commands
@tree.command(name="settext", description="Restrict bot replies to a specific text channel.")
@app_commands.default_permissions(manage_guild=True)
async def settext(inter: discord.Interaction, channel: discord.TextChannel):
    g = get_guild_cfg(inter.guild.id)
    g["text_channel_id"] = channel.id
    save_config()
    touch_activity(inter.guild.id)
    await inter.response.send_message(f"✅ I’ll only respond in {channel.mention} now. Use `/cleartext` to remove restriction.")

@tree.command(name="cleartext", description="Remove text-channel restriction.")
@app_commands.default_permissions(manage_guild=True)
async def cleartext(inter: discord.Interaction):
    g = get_guild_cfg(inter.guild.id)
    g["text_channel_id"] = None
    save_config()
    touch_activity(inter.guild.id)
    await inter.response.send_message("✅ Text-channel restriction cleared.")

@tree.command(name="setvoice", description="Set the preferred voice channel.")
@app_commands.default_permissions(manage_guild=True)
async def setvoice(inter: discord.Interaction, channel: discord.VoiceChannel):
    g = get_guild_cfg(inter.guild.id)
    g["voice_channel_id"] = channel.id
    save_config()
    touch_activity(inter.guild.id)
    await inter.response.send_message(f"✅ Preferred voice channel set to **{channel.name}**.")

# nicknames with explicit choices
@tree.command(name="nicknames", description="Use server nicknames in logs on/off.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.choices(
    mode=[
        app_commands.Choice(name="on", value="on"),
        app_commands.Choice(name="off", value="off"),
    ]
)
async def nicknames(inter: discord.Interaction, mode: app_commands.Choice[str]):
    g = get_guild_cfg(inter.guild.id)
    g["use_nicknames"] = (mode.value == "on")
    save_config()
    touch_activity(inter.guild.id)
    await inter.response.send_message(f"✅ Use nicknames: **{g['use_nicknames']}**")

# Voice/session commands
@tree.command(name="join", description="Join your current voice channel or a specified one.")
async def join(inter: discord.Interaction, channel: Optional[discord.VoiceChannel] = None):
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    if _block_if_busy(inter):
        await inter.response.send_message(busy_message(), ephemeral=True)
        return
    touch_activity(inter.guild.id)
    vc_target = channel or None
    vc = await ensure_in_user_voice(inter, vc_target)
    if vc:
        await inter.response.send_message(f"Joined **{vc.channel.name}**.")

@tree.command(name="leave", description="Leave voice and stop logging.")
async def leave(inter: discord.Interaction):
    global is_logging
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    is_logging = False
    if inter.guild.voice_client:
        try:
            if getattr(inter.guild.voice_client, "recording", False):
                inter.guild.voice_client.stop_recording()
        except Exception:
            pass
        await inter.guild.voice_client.disconnect()
        await inter.response.send_message("Left voice channel and stopped logging.")
    else:
        await inter.response.send_message("I'm not in a voice channel.", ephemeral=True)
    touch_activity(inter.guild.id)

@tree.command(name="startlog", description=f"Start STT logging (chunks={CHUNK_SECONDS}s).")
async def startlog(inter: discord.Interaction):
    global is_logging
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    if _block_if_busy(inter):
        await inter.response.send_message(busy_message(), ephemeral=True)
        return
    if not inter.guild.voice_client or not inter.guild.voice_client.is_connected():
        await inter.response.send_message("I'm not connected to a voice channel. Use `/join` first.", ephemeral=True)
        return
    touch_activity(inter.guild.id)
    is_logging = True
    dt = datetime.utcnow().strftime("%Y-%m-%d")
    await inter.response.send_message(f"✅ Logging started. Appending to `logs/{inter.guild.id}-{dt}.log` (UTC).")

@tree.command(name="stoplog", description="Stop STT logging.")
async def stoplog(inter: discord.Interaction):
    global is_logging
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    if _block_if_busy(inter):
        await inter.response.send_message(busy_message(), ephemeral=True)
        return
    is_logging = False
    if inter.guild.voice_client and getattr(inter.guild.voice_client, "recording", False):
        inter.guild.voice_client.stop_recording()
    await inter.response.send_message("⏹️ Logging stopped.")
    touch_activity(inter.guild.id)

@tree.command(name="logfile", description="Show today's log filename.")
async def logfile(inter: discord.Interaction):
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    dt = datetime.utcnow().strftime("%Y-%m-%d")
    path = log_path_for_date(inter.guild.id, dt)
    await inter.response.send_message(f"`{path}`")
    touch_activity(inter.guild.id)

@tree.command(name="summarize", description="Summarize transcript with GPT.")
@app_commands.describe(scope="today | yesterday | date | last", value="YYYY-MM-DD for date, or N for last")
async def summarize(inter: discord.Interaction, scope: str = "today", value: Optional[str] = None):
    if not channel_allowed(inter):
        await inter.response.send_message("This command is restricted to the configured text channel.", ephemeral=True)
        return
    if _block_if_busy(inter):
        await inter.response.send_message(busy_message(), ephemeral=True)
        return

    from datetime import datetime as _dt
    date_utc = datetime.utcnow().date()
    last_n = None

    scope = (scope or "today").lower()
    if scope == "today":
        pass
    elif scope == "yesterday":
        date_utc = date_utc - timedelta(days=1)
    elif scope == "date":
        if not value or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            await inter.response.send_message("Provide `value=YYYY-MM-DD` when scope=`date`.", ephemeral=True)
            return
        try:
            date_utc = _dt.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            await inter.response.send_message("Invalid date format. Use YYYY-MM-DD.", ephemeral=True)
            return
    elif scope == "last":
        if not value or not value.isdigit():
            await inter.response.send_message("Provide `value=N` (e.g., 250) when scope=`last`.", ephemeral=True)
            return
        last_n = max(1, min(int(value), MAX_LOG_LINES_TO_SUMMARIZE))
    else:
        await inter.response.send_message("scope must be one of: today, yesterday, date, last", ephemeral=True)
        return

    date_str = date_utc.strftime("%Y-%m-%d")
    path = log_path_for_date(inter.guild.id, date_str)
    lines = read_log_lines(path, max_lines=MAX_LOG_LINES_TO_SUMMARIZE)
    if not lines:
        await inter.response.send_message(f"No transcript found for **{date_str}**.", ephemeral=True)
        return
    if last_n is not None:
        lines = lines[-last_n:]

    await inter.response.send_message("🧠 Summarizing…", ephemeral=True)
    summary = summarize_text_with_openai(lines, date_str, inter.guild.name) or "No summary produced."
    # chunk to avoid 2000-char limit
    while summary:
        chunk = summary[:1900]
        summary = summary[1900:]
        await inter.followup.send(chunk)
    touch_activity(inter.guild.id)

@tree.command(name="status", description="Show current settings and session owner.")
async def status(inter: discord.Interaction):
    g = get_guild_cfg(inter.guild.id)
    tchan = inter.guild.get_channel(g.get("text_channel_id")) if g.get("text_channel_id") else None
    vchan = inter.guild.get_channel(g.get("voice_channel_id")) if g.get("voice_channel_id") else None
    owner = ACTIVE_GUILD_ID
    remaining = None
    if LAST_ACTIVITY and ACTIVE_GUILD_ID is not None:
        elapsed = (datetime.utcnow() - LAST_ACTIVITY).total_seconds()
        remaining = max(0, SESSION_TIMEOUT_SECONDS - int(elapsed))
    msg = [
        f"**Logging:** {is_logging}",
        f"**Allowed text channel:** {tchan.mention if tchan else 'All'}",
        f"**Preferred voice channel:** {vchan.name if vchan else 'None'}",
        f"**Use nicknames in logs:** {g.get('use_nicknames', True)}",
        f"**Chunk length (s):** {CHUNK_SECONDS}",
        f"**Summary model:** {OPENAI_MODEL}",
        f"**Active server:** {('None' if owner is None else f'{owner}')} "
        + ("" if remaining is None else f"(idle timeout in ~{remaining//60}m {remaining%60}s)")
    ]
    await inter.response.send_message("\n".join(msg), ephemeral=True)

# ========= RUN =========
if __name__ == "__main__":
    bot.run(TOKEN)
