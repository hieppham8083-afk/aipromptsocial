# Signal & Prompt

Local Flask MVP for an AI social website focused on:

- AI ideas
- prompt sharing
- workflow writeups
- trending prompt discovery
- creator profiles

## Run

```bash
cd /Users/hiep_pham/Desktop/ai-prompt-hub
python3 app.py
```

Then open:

`http://127.0.0.1:5055`

## Demo login

`demo@signalprompt.local`

`demo1234`

## Current MVP features

- feed with `Latest` and `Trending` sorting
- global, following, and saved views
- sign up, log in, and log out
- prompt / idea / workflow post composer
- tag filtering
- keyword search
- creator profile pages
- likes and comments
- save prompts
- follow creators
- seeded demo content in SQLite

## Next logical upgrades

- real authentication
- saves / reposts / follows
- image attachments
- prompt versioning
- AI-based recommendation ranking
- moderation and reporting

## Deploy

This repo is prepared for a simple Flask deployment.

### Render

1. Push this folder to GitHub.
2. In Render, create a new Blueprint or Web Service from the repo.
3. Use the included `render.yaml`.
4. After deploy, attach:
   - `aipromptsocial.com`
   - `www.aipromptsocial.com`
5. In your domain registrar, point DNS to Render using the target Render gives you.

### Required environment behavior

- `SECRET_KEY` should be set in production.
- `DATABASE_PATH` should point at persistent disk storage.
- `SESSION_COOKIE_SECURE=true` should be enabled for HTTPS.

### Local production-style run

```bash
cd /Users/hiep_pham/Desktop/ai-prompt-hub
pip3 install -r requirements.txt
gunicorn app:app
```
