# Personal Telegram Assistant

A private AI assistant that lives in Telegram. Send it a voice message (or text)
and it transcribes your speech with OpenAI, queries GPT with tool calling, and
can read and modify your Google Calendar and Google Tasks — adding events,
moving meetings, checking your to-do list, completing tasks, and more. It
remembers conversation context across messages and replies in plain text. The
bot only responds to your own Telegram user ID.

## Prerequisites

- Python 3.11+
- ffmpeg installed locally (`brew install ffmpeg` on Mac, `apt install ffmpeg` on Linux)
- A Telegram account
- An OpenAI account with API credits
- A Google account with Calendar and Tasks

## Setup

**1. Get your Telegram bot token**
- Open Telegram and search for @BotFather
- Send `/newbot`, follow the prompts
- Copy the API token you receive

**2. Get your Telegram user ID**
- Message @userinfobot on Telegram
- It replies with your numeric user ID

**3. Get your OpenAI API key**
- Sign in at platform.openai.com
- Go to API keys, create a new key

**4. Set up Google OAuth credentials**
- Go to console.cloud.google.com
- Create a new project
- Enable the Google Calendar API and Google Tasks API
- Go to APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
- Application type: Desktop app
- Download the credentials and copy the Client ID and Client Secret

**5. Configure the project**
```bash
cp .env.example .env
# Edit .env and fill in all values
```

**6. Install dependencies**
```bash
pip install -r requirements.txt
```

**7. Authenticate with Google (one-time)**
```bash
python auth_google.py
```
This opens a browser window. Sign in and approve access. A `token.json` file is saved locally.

**8. Run the bot**
```bash
python bot.py
```

Open Telegram, find your bot by its username, and start chatting.

## Deploying to Fly.io

```bash
# Install flyctl if you haven't: https://fly.io/docs/flyctl/install/
fly launch
fly secrets set TELEGRAM_BOT_TOKEN=xxx OPENAI_API_KEY=xxx GOOGLE_CLIENT_ID=xxx GOOGLE_CLIENT_SECRET=xxx ALLOWED_USER_ID=xxx
fly volumes create assistant_data --size 1

# Copy your local token.json to the Fly volume
fly ssh sftp shell
put token.json /data/token.json

fly deploy
```

## Usage Examples

**Calendar:**
- "What's on my calendar this week?"
- "Add a dentist appointment Thursday at 2pm for an hour"
- "Move my 3pm meeting to 4pm"
- "Cancel tomorrow's lunch"

**Tasks:**
- "What's on my to-do list?"
- "Add 'call the bank' to my tasks"
- "Add 'submit report' due Friday"
- "Mark the bank task as done"
- "What task lists do I have?"

**General:**
- Ask it anything — it answers from GPT's knowledge
- Context carries between messages so follow-ups work naturally
- `/clear` to start a fresh conversation

## Commands

| Command | Action |
|---|---|
| `/start` | Show capabilities |
| `/clear` | Clear conversation history |

## Cost

Roughly $3–5/month total:
- ~$1–3/month Fly.io hosting
- ~$0.003 per voice question in API costs (Whisper + GPT)

## License

MIT — see [LICENSE](LICENSE).
