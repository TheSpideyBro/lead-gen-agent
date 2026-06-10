# Lead Generation Agent

AI-powered sales automation for digital marketing agencies. Outreach via email AND WhatsApp Business.

## Features

- **Prospect Discovery**: Free scrapers using DuckDuckGo to find businesses
- **AI Email Sequences**: 3-step nurture sequences via Groq/Gemini (free)
- **WhatsApp Outreach**: Playwright automation for WhatsApp Business
- **Lead Scoring**: Industry/location/size scoring system
- **Response Handling**: AI-powered reply classification and response
- **CLI Interface**: Full control from command line

## Setup

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure environment
copy .env.example .env
# Edit .env with your credentials

# Run the agent
python main.py
```

## Free Resources Required

- **Groq API**: https://console.groq.com (free, required for AI)
- **Gmail**: App password for sending emails
- **WhatsApp Business**: Phone number with WhatsApp

## .env Configuration

```
GROQ_API_KEY=your_groq_key
EMAIL_ADDRESS=you@gmail.com
EMAIL_PASSWORD=app_password
FROM_NAME=Your Name
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
AI_MAX_RETRIES=3
```

## Usage

Run `python main.py` and select options:
1. Run prospecting (find new leads)
2. Send email outreach
3. Send WhatsApp outreach
4. View hot leads
5. View pending followups
6. Daily report
7. Connect WhatsApp (one-time QR scan)
8. Exit

## WhatsApp Setup

On first run, select option 7 to connect WhatsApp Web. A browser window will open - scan the QR code with your WhatsApp Business app. Your session persists in `data/whatsapp/` for future runs.

## Outreach Channels

**Email**: 3-step sequence (immediate, 48h followup, 96h followup)  
**WhatsApp**: 3-step sequence (immediate, 24h followup, 72h followup)

## Lead Scoring

Hot leads (60+): High-value industry + employees + location + email  
Warm leads (40-59): Medium fit  
Cold leads (<40): Standard prospects

## Automation

For 24/7 operation, use Windows Task Scheduler:
```
# Run prospecting daily at 9 AM
python main.py --prospect

# Process followups every 6 hours
python main.py --outreach
```