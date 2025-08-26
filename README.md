# Discord STT + Summarizer Bot

This project is a Discord bot built with [Py-Cord](https://github.com/Pycord-Development/pycord) that can join voice channels, record conversations, transcribe speech to text using [Vosk](https://alphacephei.com/vosk/), and save transcripts per guild. It also integrates with OpenAI GPT to summarize conversations into meeting notes, including key topics, decisions, action items, and notable quotes. The bot is designed for **one active server at a time**, preventing conflicts across multiple guilds, with per-guild configuration for text channels, voice channels, and nickname usage. Commands are implemented with **slash commands** for easy use.  

---

## 🚀 Features
- `/join` and `/leave` — manage voice channel connections.  
- `/startlog` and `/stoplog` — start/stop live speech-to-text logging.  
- `/summarize` — generate GPT summaries from transcripts (today, yesterday, date, or last N lines).  
- `/settext` & `/setvoice` — configure per-guild text/voice preferences.  
- `/claim` & `/release` — single-server lock control.  
- `/status` — show active settings.  

---

## ⚙️ Setup

1. Clone this repo and `cd` into it.
2. Download and extract the [Vosk English model](https://alphacephei.com/vosk/models) into `models/vosk-model-en-us-0.42-gigaspeech/`.
3. Place `ffmpeg.exe` and `ffprobe.exe` in the project root (or install FFmpeg system-wide).
4. Install requirements:
   ```bash
   pip install -r requirements.txt


create a config.py with:
DISCORDTOKEN = "your_discord_bot_token_here"
OPENAPIAPIKEY = "your_openai_api_key_here"
