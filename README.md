# SeaVoice Meeting Summarizer – Discord Bot

A Discord bot that converts **SeaVoice** voice channel transcripts into organized meeting notes using **OpenAI GPT-4.1-mini**.  
Designed for remote teams, this bot makes it simple to capture discussions, decisions, and action items directly in your Discord server.

---

## 🚀 Features
- **Slash Command `/summarize`** → instantly generates a structured summary of today’s SeaVoice transcripts.  
- **Automated transcript collection** → fetches all SeaVoice messages from the current day in the channel.  
- **Cleans boilerplate** → ignores standard “Transcribing! / Server / Voice Channel / Session ID” lines.  
- **Structured output** → summaries include:
  1. Key Topics  
  2. Decisions  
  3. Action Items (assignee → task → deadline)  
  4. Open Questions  
  5. Notable Quotes  
  6. Participation Stats  

---

## 📂 Project Structure
stt/
├── bot.py # Main bot logic (Discord + OpenAI integration)
├── config.py # Optional: store constants like DISCORDTOKEN, OPENAPIAPIKEY, GUILD_ID
├── .env # Environment variables (tokens + keys)
├── requirements.txt # Python dependencies

yaml
Copy code

---

## ⚙️ Setup & Installation

1. **Clone the repo**:
   ```bash
   git clone <your-repo-url>
   cd stt
Create a virtual environment (recommended):

bash
Copy code
python -m venv .venv
source .venv/bin/activate   # macOS/Linux
.venv\Scripts\activate      # Windows
Install dependencies:

bash
Copy code
pip install -r requirements.txt
Set up environment variables
Create a .env file in the project root:

env
Copy code
DISCORDTOKEN=your_discord_bot_token_here
OPENAPIAPIKEY=your_openai_api_key_here
GUILD_ID=123456789012345678   # Replace with your Discord server ID
Re-invite your bot
Generate an OAuth2 URL in the Discord Developer Portal:

Scopes: bot, applications.commands

Permissions: Send Messages, Read Messages/View Channels, Read Message History (or Administrator for testing).
Invite the bot to your server with this URL.

Run the bot:

bash
Copy code
python bot.py

▶️ Usage

Join a Discord voice channel with SeaVoice recording active.

After the session, run the command in the same text channel:

/summarize


The bot will:

Collect all SeaVoice logs from today

Strip out unnecessary header text

Generate a structured meeting summary

Example Output:

📋 Meeting Summary (Today):

1) Key Topics
- Discussed testing SeaVoice transcription.
- Talked about how the shuttle feature works.

2) Decisions
- Continue testing recording quality in the General channel.

3) Action Items
- shadowslayz → Test additional recording sessions → by tomorrow.

4) Open Questions
- How accurate is the transcription in longer meetings?

5) Notable Quotes
- "Okay, your shuttle actually works."

6) Participation Stats
- Participants: shadowslayz
- Messages: ~10 lines
