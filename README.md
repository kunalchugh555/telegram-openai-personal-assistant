# Personal Telegram Assistant

A private AI assistant that lives in Telegram. Send it a voice message, an
audio file, or text and it transcribes your speech with OpenAI, queries GPT
with tool calling, and can:

- **Google Calendar** — check, add, move, and cancel events
- **Google Tasks** — list, add, complete, and delete tasks
- **Gmail** — read unread mail, search, read full threads, draft replies, and send email
- **Google Drive** — search files and read the contents of Docs, Sheets, and PDFs
- **Web search** — look up current news, scores, prices, business hours, and other time-sensitive facts
- **Weather** — current conditions, 14-day forecast, 7-day past history, and hourly detail for any location
- **General questions** — answer anything from GPT's knowledge

It remembers conversation context across messages and replies in plain text.
The bot only responds to your own Telegram user ID.

## Prerequisites

- Python 3.11+
- ffmpeg installed locally (`brew install ffmpeg` on Mac, `apt install ffmpeg` on Linux)
- A Telegram account
- An OpenAI account with API credits
- A Google Cloud project (`personal-assistant-kunal`) with these APIs enabled:
  - Google Calendar API
  - Google Tasks API
  - Gmail API
  - Google Drive API

## Local Setup

**1. Get your Telegram bot token**
- Open Telegram and search for @BotFather
- Send `/newbot`, follow the prompts
- Copy the API token you receive

**2. Get your Telegram user ID**
- Message @userinfobot on Telegram — it replies with your numeric user ID

**3. Get your OpenAI API key**
- Sign in at platform.openai.com → API keys → create a new key

**4. Google OAuth credentials**
- Go to console.cloud.google.com → project `personal-assistant-kunal`
- APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
- Application type: Desktop app → Create
- Copy the Client ID and Client Secret

**5. Configure the project**
```bash
cp .env.example .env
# Edit .env and fill in all values
```

**6. Install dependencies**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**7. Authenticate with Google (one-time)**
```bash
python auth_google.py
```
A browser window opens. Sign in and approve access to Calendar, Tasks, Gmail,
and Drive. A `token.json` file is saved locally. Re-run this script if you
ever change the requested scopes.

**8. Run the bot**
```bash
python bot.py
```

Open Telegram, find your bot by its username, and start chatting.

## Deploying to Google Cloud (free, always-on)

The bot runs on a free-tier **e2-micro** Compute Engine VM in Google Cloud.
This VM is always on and costs $0/month under the Always Free tier.

### One-time VM creation (run locally)

```bash
# Enable Compute Engine
gcloud services enable compute.googleapis.com --project=personal-assistant-kunal

# Create the VM
gcloud compute instances create telegram-assistant \
  --machine-type=e2-micro \
  --zone=us-central1-a \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --project=personal-assistant-kunal

# Run the setup script on the VM (installs deps, clones repo, registers systemd service)
gcloud compute ssh telegram-assistant --zone=us-central1-a \
  --project=personal-assistant-kunal -- 'bash -s' < scripts/setup_vm.sh

# Copy your secrets to the VM
gcloud compute scp .env telegram-assistant:~/telegram-openai-personal-assistant/.env \
  --zone=us-central1-a --project=personal-assistant-kunal

gcloud compute scp token.json telegram-assistant:~/telegram-openai-personal-assistant/token.json \
  --zone=us-central1-a --project=personal-assistant-kunal

# Start the bot
gcloud compute ssh telegram-assistant --zone=us-central1-a \
  --project=personal-assistant-kunal -- \
  'sudo systemctl start telegram-assistant'
```

### Managing the bot on the VM

```bash
# SSH into the VM
gcloud compute ssh telegram-assistant --zone=us-central1-a --project=personal-assistant-kunal

# Then on the VM:
sudo systemctl status telegram-assistant   # check if running
sudo systemctl restart telegram-assistant  # restart
sudo journalctl -u telegram-assistant -f   # live logs
```

### Updating the bot after a code change

```bash
gcloud compute ssh telegram-assistant --zone=us-central1-a \
  --project=personal-assistant-kunal -- \
  'cd ~/telegram-openai-personal-assistant && git pull && sudo systemctl restart telegram-assistant'
```

### Re-authenticating Google OAuth

OAuth tokens occasionally expire. If the bot reports an auth error:

```bash
# Run locally to generate a fresh token.json
python auth_google.py

# Copy it to the VM
gcloud compute scp token.json telegram-assistant:~/telegram-openai-personal-assistant/token.json \
  --zone=us-central1-a --project=personal-assistant-kunal

# Restart the bot
gcloud compute ssh telegram-assistant --zone=us-central1-a \
  --project=personal-assistant-kunal -- \
  'sudo systemctl restart telegram-assistant'
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

**Gmail:**
- "Do I have any unread emails?"
- "Did anyone email me about the invoice?"
- "Draft a reply to John saying I'll have it done by Friday"
- "Send John an email letting him know I'll be 10 minutes late"

**Google Drive:**
- "Find my Q3 report"
- "Read me the contents of the meeting notes doc"
- "Search Drive for the contractor proposal"

**Web Search:**
- "What's the score of the Cubs game?"
- "What time does Home Depot close today?"
- "What's the latest on the Fed rate decision?"

**Weather:**
- "What's the weather like today?"
- "Should I bring an umbrella this week?"
- "What was the weather last Tuesday?"
- "What's the hourly forecast for tomorrow?"
- "Weather in Tokyo this weekend?"

Weather covers current conditions, the next 14 days, the past 7 days, and
hour-by-hour detail for any day within the last 92 days or the next 14.
Forecasts beyond about 7 days out are lower confidence.

**General:**
- Ask it anything — it answers from GPT's knowledge
- Context carries between messages so follow-ups work naturally
- `/clear` to start a fresh conversation

## Email: drafts vs. sending

The bot drafts by default — when you say "draft a reply," it stages a draft in
Gmail for you to review. It only sends when you clearly ask it to ("send John
an email..."). Drafts and sent mail both appear in your normal Gmail.

## Commands

| Command | Action |
|---|---|
| `/start` | Show capabilities |
| `/clear` | Clear conversation history |

## Cost

| Item | Cost |
|---|---|
| Google Cloud e2-micro VM (hosting) | $0 (Always Free tier) |
| Google APIs (Calendar, Tasks, Gmail, Drive) | $0 (free at personal scale) |
| Weather (Open-Meteo) | $0 (free, no API key) |
| OpenAI transcription per voice message (~30s) | ~$0.003 |
| OpenAI GPT per message | ~$0.0003 |
| OpenAI web search per search | ~$0.001–0.003 |

Rough total: **~$1–3/month** in OpenAI API costs only. Hosting is free.

## License

MIT — see [LICENSE](LICENSE).
