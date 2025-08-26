import discord
from discord.ext import commands

# --- CONFIG ---
from config import DISCORDTOKEN as DISCORD_BOT_TOKEN, OPENAPIAPIKEY as OPENAI_API_KEY  # noqa: F401

# --- INTENTS ---
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

# --- BOT ---
bot = commands.Bot(command_prefix="!", intents=intents)

# --- UTIL: safe reply helpers ---
async def safe_defer(ctx: discord.ApplicationContext, ephemeral: bool = True):
    """Defer once; ignore if already responded/acknowledged."""
    try:
        await ctx.defer(ephemeral=ephemeral)
    except discord.HTTPException:
        pass

async def safe_followup(ctx: discord.ApplicationContext, content: str, ephemeral: bool = True):
    """Send followup even if initial interaction got ack’d/expired."""
    try:
        await ctx.followup.send(content, ephemeral=ephemeral)
    except discord.HTTPException:
        # Last resort: DM the user if followup fails
        try:
            await ctx.author.send(content)
        except Exception:
            pass

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    print("Guilds I'm in:")
    for g in bot.guilds:
        print(f"- {g.name} (ID: {g.id})")

# --- SYNC COMMANDS ---
@bot.slash_command(
    name="sync_here",
    description="Admin: sync slash commands to THIS server only",
    default_member_permissions=discord.Permissions(administrator=True)
)
async def sync_here(ctx: discord.ApplicationContext):
    await safe_defer(ctx)
    try:
        await bot.sync_commands(guild_ids=[ctx.guild.id])
        await safe_followup(ctx, f"✅ Synced {len(bot.application_commands)} commands to **{ctx.guild.name}**.")
    except Exception as e:
        await safe_followup(ctx, f"❌ Sync here failed: `{e}`")

@bot.slash_command(
    name="sync_global",
    description="Admin: sync slash commands globally",
    default_member_permissions=discord.Permissions(administrator=True)
)
async def sync_global(ctx: discord.ApplicationContext):
    await safe_defer(ctx)
    try:
        await bot.sync_commands()
        await safe_followup(ctx, f"✅ Requested global sync for {len(bot.application_commands)} commands.")
    except Exception as e:
        await safe_followup(ctx, f"❌ Global sync failed: `{e}`")

@bot.slash_command(
    name="list_commands",
    description="Debug: list registered application command names",
    default_member_permissions=discord.Permissions(manage_guild=True)
)
async def list_commands(ctx: discord.ApplicationContext):
    await safe_defer(ctx)
    names = ", ".join(sorted(cmd.name for cmd in bot.application_commands)) or "(none)"
    await safe_followup(ctx, f"🧰 Commands: {names}")

# --- VOICE TEST COMMANDS ---
@bot.slash_command(name="join", description="Join the voice channel you're in.")
async def join(ctx: discord.ApplicationContext):
    await safe_defer(ctx)
    if not ctx.author.voice or not ctx.author.voice.channel:
        await safe_followup(ctx, "❌ You're not in a voice channel.", ephemeral=True)
        return

    channel = ctx.author.voice.channel
    try:
        vc = ctx.guild.voice_client
        if vc and vc.is_connected():
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
                await safe_followup(ctx, f"🔄 Moved to **{channel.name}**.")
            else:
                await safe_followup(ctx, f"ℹ️ Already in **{channel.name}**.")
        else:
            await channel.connect()
            await safe_followup(ctx, f"✅ Joined **{channel.name}**.")
    except Exception as e:
        await safe_followup(ctx, f"❌ Join failed: `{e}`")

@bot.slash_command(name="leave", description="Leave the voice channel.")
async def leave(ctx: discord.ApplicationContext):
    await safe_defer(ctx)
    try:
        vc = ctx.guild.voice_client
        if vc and vc.is_connected():
            await vc.disconnect(force=True)
            await safe_followup(ctx, "👋 Left the voice channel.")
        else:
            await safe_followup(ctx, "❌ I'm not in a voice channel.", ephemeral=True)
    except Exception as e:
        await safe_followup(ctx, f"❌ Leave failed: `{e}`")

# --- RUN ---
if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
