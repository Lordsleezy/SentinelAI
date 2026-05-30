# SentinelAI Configuration Files

This directory stores configuration and authentication tokens for various integrations.

## Files

### Google OAuth Tokens

- **`google_creds.json`** — Google Cloud OAuth 2.0 client credentials
  - Download from: https://console.cloud.google.com/apis/credentials
  - Required for: Google Calendar, Google Contacts
  - Permissions needed: Calendar API, People API

- **`calendar_token.pickle`** — Google Calendar OAuth token cache (auto-generated)
- **`contacts_token.pickle`** — Google Contacts OAuth token cache (auto-generated)

### Database

- **`reminders.db`** — SQLite database for OpenClaw reminders
  - Schema: `id, title, due_dt, repeat, dismissed, created_at`
  - Auto-created on first run

### Spotify

- **`spotify_token.json`** — Spotify OAuth token cache (auto-generated)
  - Created after first authentication flow
  - Refresh token stored for automatic renewal

### Camera Credentials (optional, for direct integration fallback)

- **`blink_creds.json`** — Blink camera credentials
  ```json
  {
    "email": "your@email.com",
    "password": "your_password"
  }
  ```

- **`eufy_creds.json`** — Eufy camera credentials
  ```json
  {
    "email": "your@email.com",
    "password": "your_password"
  }
  ```

- **`arlo_creds.json`** — Arlo camera credentials
  ```json
  {
    "email": "your@email.com",
    "password": "your_password"
  }
  ```

**Note:** Camera credentials are only needed if not using Home Assistant as the universal bridge (recommended).

## Security

⚠️ **IMPORTANT:** All files in this directory contain sensitive credentials.

- Never commit this directory to git (already in .gitignore)
- Restrict file permissions: `chmod 600 config/*`
- Back up tokens to a secure location

## Setup Order

1. **Google Calendar/Contacts:**
   - Create OAuth 2.0 credentials in Google Cloud Console
   - Download and save as `google_creds.json`
   - Run SentinelAI - will prompt for OAuth flow on first use
   - Tokens cached automatically

2. **Spotify:**
   - Create app at https://developer.spotify.com/dashboard
   - Set redirect URI to `http://localhost:8888/callback`
   - Add `SPOTIPY_CLIENT_ID` and `SPOTIPY_CLIENT_SECRET` to `.env`
   - Token cached on first playback command

3. **Reminders:**
   - Auto-created, no manual setup needed

4. **Cameras:**
   - Recommended: Use Home Assistant (no credentials needed here)
   - Fallback: Create JSON files with credentials as shown above

## Troubleshooting

**OAuth errors:**
- Delete the `.pickle` files and re-authenticate
- Check that Google Cloud project has the required APIs enabled
- Verify OAuth consent screen is configured

**Permission denied:**
- Check file ownership: `sudo chown -R $USER:$USER config/`
- Set restrictive permissions: `chmod 700 config && chmod 600 config/*`

**Token refresh failures:**
- Spotify: Delete `spotify_token.json` and re-authenticate
- Google: Delete `.pickle` files and re-authenticate
