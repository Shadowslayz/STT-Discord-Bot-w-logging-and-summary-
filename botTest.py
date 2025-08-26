import os
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
from dotenv import load_dotenv
from config import DISCORDTOKEN
load_dotenv()
DISCORD_BOT_TOKEN = DISCORDTOKEN

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# --- Simple commands (GLOBAL definitions; we’ll copy+sync them to each guild) ---

@tree.command(name="ping", description="Simple ping")
async def ping(inter: discord.Interaction):
    await inter.response.send_message("Pong!")

@tree.command(name="echo", description="Echo back your text")
@app_commands.describe(text="What should I say back?")
async def echo(inter: discord.Interaction, text: str):
    await inter.response.send_message(text)

@tree.command(name="sync_here", description="Admin: sync slash commands to THIS server")
@app_commands.default_permissions(administrator=True)
async def sync_here(inter: discord.Interaction):
    try:
        guild_obj = discord.Object(id=inter.guild.id)
        # copy all global commands into this guild, then sync
        tree.copy_global_to(guild=guild_obj)
        synced = await tree.sync(guild=guild_obj)
        await inter.response.send_message(
            f"✅ Synced {len(synced)} commands to this guild.",
            ephemeral=True
        )
    except Exception as e:
        await inter.response.send_message(f"❌ Sync failed: {e}", ephemeral=True)

# --- Startup: show commands and sync to each guild instantly ---
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    print("Commands discovered at import:", [c.name for c in tree.get_commands()])

    print("Guilds I'm in:")
    for g in bot.guilds:
        print(f"- {g.name} (ID: {g.id})")

    # Instant per-guild sync (don’t wait for global propagation)
    try:
        total = 0
        for g in bot.guilds:
            guild_obj = discord.Object(id=g.id)
            tree.copy_global_to(guild=guild_obj)
            synced = await tree.sync(guild=guild_obj)
            print(f"✅ Synced {len(synced)} commands to guild {g.id} ({g.name})")
            total += len(synced)
        if total == 0:
            print("ℹ️ Still 0? Then your decorators didn’t execute or wrong library is installed.")
    except Exception as e:
        print(f"❌ Guild sync failed: {e}")

# --- Run ---
if __name__ == "__main__":
    if not DISCORD_BOT_TOKEN:
        raise SystemExit("❌ Set DISCORD_BOT_TOKEN in your .env")
    bot.run(DISCORD_BOT_TOKEN)
