# Personal Telegram Assistant

A private AI assistant that lives in Telegram. Send it a voice message, an
audio file, or text and it transcribes your speech with OpenAI, queries GPT
with tool calling, and can:

- **Google Calendar** — check, add, move, and cancel events
- **Google Tasks** — list, add, complete, and delete tasks
- **Gmail** — read unread mail, search, read full threads, draft replies, and send email
- **Google Drive** — search files and read the contents of Docs, Sheets, and PDFs
- **Web search** — look up current news, scores, prices, business hours, and other time-sensitive facts
- **Weather** — current conditions and a 7-day forecast for any location
- **General questions** — answer anything from GPT's knowledge

It remembers conversation context across messages and replies in plain text.
The bot only responds to your own Telegram user ID.

## Prerequisites

- Python 3.11+
- ffmpeg installed locally (`brew install ffmpeg` on Mac, `apt install ffmpeg` on Linux)
- A Telegram account
- An OpenAI account with API credits
- A Google account with Calendar, Tasks, Gmail, and Drive
- The following Google APIs enabled in your Google Cloud project:
  - Google Calendar API
  - Google Tasks API
  - Gmail API
  - Google Drive API

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
- Enable these four APIs in the project:
  - Google Calendar API
  - Google Tasks API
  - Gmail API
  - Google Drive API
- Go to APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
- Application type: Desktop app
- Download the credentials and copy the Client ID and Client Secret

> If you already set the bot up before Gmail and Drive were added, enable the
> two new APIs and run `python auth_google.py` again to re-authorize with the
> expanded scopes.

**5. Configure the project**
```bash
cp .env.example .env
# Edit .env and fill in all values, including USER_LOCATION and USER_TIMEZONE
```

**6. Install dependencies**
```bash
pip install -r requirements.txt
```

**7. Authenticate with Google (one-time)**
```bash
python auth_google.py
```
This opens a browser window. Sign in and approve access to Calendar, Tasks,
Gmail, and Drive. A `token.json` file is saved locally. Re-run this script
whenever the requested scopes change.

**8. Run the bot**
```bash
python bot.py
```

Open Telegram, find your bot by its username, and start chatting.

## Deploying to Fly.io

```bash
# Install flyctl if you haven't: https://fly.io/docs/flyctl/install/
fly launch
fly secrets set TELEGRAM_BOT_TOKEN=xxx OPENAI_API_KEY=xxx GOOGLE_CLIENT_ID=xxx \
  GOOGLE_CLIENT_SECRET=xxx ALLOWED_USER_ID=xxx USER_LOCATION="Your City, State" \
  USER_TIMEZONE=America/Chicago
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

**Gmail:**
- "Do I have any unread emails?"
- "Did anyone email me about the invoice?"
- "Read me John's latest email"
- "Draft a reply to John saying I'll have it done by Friday"
- "Send John an email letting him know I'll be 10 minutes late"
- "Any emails from Amazon this week?"

**Google Drive:**
- "Find my Q3 report"
- "What did my notes from last Tuesday say?"
- "Search Drive for the contractor proposal"
- "Read me the contents of the meeting notes doc"

**Web Search:**
- "What's the score of the Cubs game?"
- "What time does Home Depot in Dubuque close today?"
- "What's the latest on the Fed rate decision?"
- "Is there any news about [topic]?"

**Weather:**
- "What's the weather like today?"
- "Should I bring an umbrella this week?"
- "What's the forecast for the weekend?"
- "What's the weather in Chicago tomorrow?"

**General:**
- Ask it anything — it answers from GPT's knowledge
- Context carries between messages so follow-ups work naturally
- `/clear` to start a fresh conversation

## Email: drafts vs. sending

The bot can both draft and send email. It drafts by default — when you say
"draft a reply," it stages a draft in Gmail for you to review. It only sends
when you clearly ask it to ("send John an email..."). Drafts and sent mail
both appear in your normal Gmail.

## Commands

| Command | Action |
|---|---|
| `/start` | Show capabilities |
| `/clear` | Clear conversation history |

## Cost

Roughly $3–5/month total:
- ~$1–3/month Fly.io hosting
- ~$0.003 per voice question in API costs (transcription + GPT)

| Addition | Cost |
|---|---|
| Calendar / Tasks / Gmail / Drive tools | $0 (Google APIs are free at personal scale) |
| Weather (Open-Meteo) | $0 (free, no API key) |
| Web search | ~$0.001–0.003 per search (OpenAI web search pricing) |
| Extra GPT tokens from tool results | Negligible at personal use volume |

## License

MIT — see [LICENSE](LICENSE).
