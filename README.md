# ✈️ SkyWatch — Aviation Discord Bot

A zero-cost, zero-API-key Discord bot for aviation enthusiasts, sim pilots, and VATSIM users.

## Data Sources (both free, no signup needed)

| Source | What it provides |
|---|---|
| [aviationweather.gov](https://aviationweather.gov) (NOAA) | METAR, TAF — official US government data |
| [data.vatsim.net/v3/vatsim-data.json](https://data.vatsim.net/v3/vatsim-data.json) | Live VATSIM pilots, ATC, ATIS, prefiles |

---

## Commands

### Weather
| Command | Description |
|---|---|
| `/metar <ICAO>` | Latest METAR with flight category, wind, vis, ceiling |
| `/taf <ICAO>` | Latest TAF (raw) |
| `/wx <ICAO>` | METAR + TAF combined |

### VATSIM Network
| Command | Description |
|---|---|
| `/vatsim_stats` | Live count: pilots, ATC, prefiles |
| `/pilot <callsign>` | Full pilot details — aircraft, route, altitude, speed |
| `/find_pilot <query>` | Search by partial callsign or CID |
| `/atc <station>` | ATC controllers at a facility (e.g. `KSFO`, `EGLL_APP`) |
| `/atis <ICAO>` | ATIS text for a station |
| `/traffic <ICAO>` | Departures & arrivals at an airport |

---

## Setup

### 1. Prerequisites
- Python 3.11+
- A Discord bot token (free from [discord.com/developers](https://discord.com/developers))

### 2. Create the bot on Discord
1. Go to https://discord.com/developers/applications → **New Application**
2. **Bot** tab → **Add Bot** → copy the token
3. **OAuth2 → URL Generator**: scopes = `bot` + `applications.commands`
4. Bot permissions: `Send Messages`, `Embed Links`, `Read Message History`
5. Open the generated URL to invite the bot to your server

### 3. Install & run
```bash
git clone <your-repo>
cd avbot
pip install -r requirements.txt
cp .env.example .env
# Edit .env and paste your DISCORD_TOKEN
python bot.py
```

### 4. Free hosting options (zero cost)
- **Railway** — free hobby tier, deploy from GitHub in minutes
- **Fly.io** — free tier, `flyctl deploy`
- **Oracle Cloud Free Tier** — always-free VM, runs indefinitely
- **Your own machine** — just leave it running

---

## Rate Limits & Notes

- **aviationweather.gov**: max 100 req/min — the bot's slash command usage is well within this.
- **VATSIM data feed**: updates every ~15 seconds, no auth required, no rate limit documented (be reasonable).
- The bot's status auto-updates every 5 minutes showing live VATSIM pilot/ATC count.

## No API keys needed — ever.
