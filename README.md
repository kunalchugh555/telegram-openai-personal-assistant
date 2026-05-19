# Personal Telegram Assistant

A private AI assistant that lives in Telegram. Send it a voice message, an
audio file, or text and it transcribes your speech with OpenAI, queries GPT
with tool calling, and can:

- **Google Calendar** — check, add, move, and cancel events
- **Google Tasks** — list, add, complete, and delete tasks
- **Gmail** — read unread mail, search, read full threads, draft replies, and send email
- **Google Drive** — search files and read the contents of Docs, Sheets, and PDFs
- **Google Maps** — travel time and directions (driving, walking, transit, biking), and nearby place search
- **Web search** — look up current news, scores, prices, business hours, and other time-sensitive facts
- **Weather** — current conditions, 14-day forecast, 7-day past history, and hourly detail for any location
- **Daily rain/snow alert** — automatically emails you at 5am if rain or snow is forecast for your location
- **Google Meet** — automatically generates a Meet link when you create a meeting
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

**5. Get a Google Maps API key** (for travel time and nearby search)
- Go to Google Cloud Console → APIs & Services → Library
- Enable **Directions API** and **Places API**
- Go to Credentials → Create Credentials → API Key
- Copy the key (this is separate from the OAuth credentials)

**6. Configure the project**
```bash
cp .env.example .env
# Edit .env and fill in all values including USER_EMAIL and GOOGLE_MAPS_API_KEY
```

**7. Install dependencies**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**8. Authenticate with Google (one-time)**
```bash
python auth_google.py
```
A browser window opens. Sign in and approve access to Calendar, Tasks, Gmail,
and Drive. A `token.json` file is saved locally. Re-run this script if you
ever change the requested scopes.

**9. Run the bot**
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

**Google Maps:**
- "How long does it take to drive to O'Hare?"
- "How far is downtown Chicago from here?"
- "Find a coffee shop near me"
- "Best pizza places nearby"
- "Walking time from my place to Millennium Park"

**Calendar with Meet:**
- "Schedule a team call tomorrow at 2pm with a Meet link"
- "Add a 30-minute call on Friday at 10am and add a Google Meet link"

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

## Security

### What's hardened out of the box

**Bot access control**
The bot only responds to the Telegram user ID set in `ALLOWED_USER_ID`. Every handler checks this before doing anything else. Anyone else who finds your bot gets silence.

**Prompt injection defense**
The LLM system prompt explicitly treats email bodies, calendar descriptions, Drive file contents, and web search results as untrusted data. If any of that content contains text like "ignore previous instructions" or asks the bot to send an email or delete something, the bot is instructed to flag it to you and stop. It will never act on instructions embedded in your data without a clear request from you in the current message.

**No secrets in code**
API keys, tokens, and credentials are read exclusively from environment variables via `.env`. The `.gitignore` ensures `.env`, `token.json`, and `assistant.db` are never committed. The Google OAuth token is generated locally and copied to the VM — it never passes through any third-party system.

**Dependency security**
All dependencies are pinned to specific versions and audited with `pip-audit`. The current set has zero known CVEs. Run `pip-audit` after any `pip install` to verify.

**SQL injection prevention**
All database queries in `core/db.py` use parameterized statements. There is no string-formatted SQL anywhere in the codebase.

**No unsafe code execution**
There is no `eval()`, `exec()`, `subprocess` with `shell=True`, or any other mechanism that could execute arbitrary code. Tool dispatch uses a hard-coded whitelist — GPT cannot call functions outside that list.

**TLS verification**
All outbound HTTPS requests use verified TLS (`verify=False` appears nowhere in the codebase).

---

### VM and infrastructure hardening (GCP)

**SSH**
- Password authentication is disabled — key-only login
- Root login is disabled
- `block-project-ssh-keys=true` on the VM instance — project-wide SSH keys cannot SSH in
- `fail2ban` monitors the SSH jail and auto-bans IPs after repeated failed attempts

**No service account on the VM**
The VM has no GCP service account attached. If malware ran on the VM and tried to call the GCP metadata server at `169.254.169.254` to steal a token, it would get HTTP 404. The bot has no GCP IAM permissions.

**systemd sandboxing**
The bot runs as a non-root user under a hardened systemd unit (security score 3.2/10 — lower is better). Key restrictions:
- `NoNewPrivileges`, `PrivateTmp`, `PrivateDevices`
- `ProtectSystem=strict` with write access limited to the app directory only
- Empty `CapabilityBoundingSet` — the process has no Linux capabilities
- `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX` — only internet and local socket families
- `RestrictNamespaces`, `RestrictRealtime`, `RestrictSUIDSGID`, `LockPersonality`

**File permissions**
`.env`, `token.json`, and `assistant.db` are all `chmod 600` (owner-read/write only) on both your local machine and the VM.

**Auto security patches**
`unattended-upgrades` is installed and active on the VM — OS security patches apply automatically without manual intervention.

**Firewall**
Only three GCP firewall rules are active: SSH (port 22), internal VPC traffic, and ICMP (ping). No other ports are open.

**Budget alert**
A $5/month budget alert is set on the GCP project. You'll receive an email at 50%, 90%, and 100% of that limit — a signal if something unexpected is running.

---

### What you should do manually

**1. Set an OpenAI spending limit**
Go to [platform.openai.com](https://platform.openai.com) → Billing → Usage limits. Set a hard monthly cap. The bot costs roughly $1–3/month at normal personal use; a limit of $10–20 prevents runaway charges if something goes wrong.

**2. Rotate any credentials that appeared in chat**
If you pasted API keys, tokens, or passwords into the Telegram chat during setup, rotate them now:
- Telegram bot token: message @BotFather → `/mybots` → select your bot → API Token → Revoke
- OpenAI API key: platform.openai.com → API keys → delete the old one, create a new one
- Google OAuth: if the client secret was shared, regenerate it in Google Cloud Console → Credentials

**3. Keep token.json off shared systems**
`token.json` grants full read/write access to your Calendar, Tasks, Gmail, and Drive. Never put it in cloud storage, email it, or commit it. The `.gitignore` prevents accidental commits, but be deliberate about where you copy it.

**4. Re-run pip-audit after updates**
```bash
source .venv/bin/activate
pip-audit
```
If any CVEs appear, upgrade the affected package and re-test.

---

## License

MIT — see [LICENSE](LICENSE).
