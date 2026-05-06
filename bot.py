"""
SkyWatch Discord Bot
Aviation-focused bot: METAR/TAF from aviationweather.gov (free, no key)
VATSIM live data from data.vatsim.net/v3/vatsim-data.json (free, no key)
"""

import os
import discord
from discord.ext import commands, tasks
import aiohttp
import json
import re
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
AWC_TAF_URL = "https://aviationweather.gov/api/data/taf"

# Flight category colours
FLIGHT_CAT_COLOURS = {
    "VFR": discord.Colour.green(),
    "MVFR": discord.Colour.blue(),
    "IFR": discord.Colour.red(),
    "LIFR": discord.Colour.purple(),
}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def fetch_json(url: str, params: dict = None) -> dict | list | None:
    headers = {"User-Agent": "SkyWatchDiscordBot/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            return None


async def fetch_text(url: str, params: dict = None) -> str | None:
    headers = {"User-Agent": "SkyWatchDiscordBot/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.text()
            return None


def flight_category_from_metar(metar_data: dict) -> str:
    """Derive flight category from aviationweather.gov JSON fields."""
    cat = metar_data.get("flightCategory") or metar_data.get("flight_category", "")
    return cat.upper() if cat else "UNKNOWN"


def wind_str(metar_data: dict) -> str:
    wdir = metar_data.get("wdir", "")
    wspd = metar_data.get("wspd", "")
    wgst = metar_data.get("wgst", "")
    if not wspd:
        return "Calm"
    direction = "VRB" if str(wdir).upper() == "VRB" else f"{wdir}°"
    gust = f" G{wgst}kt" if wgst else ""
    return f"{direction} @ {wspd}kt{gust}"


def format_metar_embed(metar_data: dict) -> discord.Embed:
    icao = metar_data.get("icaoId", "????").upper()
    raw = metar_data.get("rawOb", "N/A")
    cat = flight_category_from_metar(metar_data)
    colour = FLIGHT_CAT_COLOURS.get(cat, discord.Colour.greyple())

    vis = metar_data.get("visib", "N/A")
    temp = metar_data.get("temp", "N/A")
    dewp = metar_data.get("dewp", "N/A")
    altim = metar_data.get("altim", "N/A")  # hPa
    clouds = metar_data.get("clouds", [])

    cloud_str = ", ".join(
        f"{c.get('cover','?')} {c.get('base','?')}ft" for c in clouds
    ) if clouds else "Clear"

    # Convert hPa to inHg if available
    altim_inhg = ""
    try:
        altim_inhg = f" ({float(altim) * 0.02953:.2f} inHg)"
    except (TypeError, ValueError):
        pass

    obs_time = metar_data.get("obsTime", "")
    try:
        obs_dt = datetime.fromtimestamp(int(obs_time), tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    except (TypeError, ValueError):
        obs_dt = obs_time

    embed = discord.Embed(
        title=f"✈️ METAR — {icao}",
        description=f"```{raw}```",
        colour=colour,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="Flight Category", value=f"**{cat}**", inline=True)
    embed.add_field(name="Wind", value=wind_str(metar_data), inline=True)
    embed.add_field(name="Visibility", value=f"{vis} SM", inline=True)
    embed.add_field(name="Sky", value=cloud_str, inline=True)
    embed.add_field(name="Temp / Dew", value=f"{temp}°C / {dewp}°C", inline=True)
    embed.add_field(name="Altimeter", value=f"{altim} hPa{altim_inhg}", inline=True)
    embed.add_field(name="Observed", value=obs_dt, inline=False)
    embed.set_footer(text="Source: aviationweather.gov (NOAA)")
    return embed


# --------------------------------------------------------------------------- #
# Bot events
# --------------------------------------------------------------------------- #

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ SkyWatch online as {bot.user} ({bot.user.id})")
    update_status.start()


@tasks.loop(minutes=5)
async def update_status():
    try:
        data = await fetch_json(VATSIM_DATA_URL)
        if data:
            pilots = len(data.get("pilots", []))
            atc = len(data.get("controllers", []))
            await bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"{pilots} pilots | {atc} ATC on VATSIM",
                )
            )
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Slash commands — METAR / TAF
# --------------------------------------------------------------------------- #

@bot.tree.command(name="metar", description="Fetch the latest METAR for an airport (ICAO code)")
async def metar_cmd(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    data = await fetch_json(AWC_METAR_URL, params={"ids": icao, "format": "json", "hours": 2})
    if not data or not isinstance(data, list) or len(data) == 0:
        await interaction.followup.send(f"❌ No METAR found for **{icao}**. Check the ICAO code.")
        return
    embed = format_metar_embed(data[0])
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="taf", description="Fetch the latest TAF for an airport (ICAO code)")
async def taf_cmd(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    data = await fetch_json(AWC_TAF_URL, params={"ids": icao, "format": "json"})
    if not data or not isinstance(data, list) or len(data) == 0:
        await interaction.followup.send(f"❌ No TAF found for **{icao}**.")
        return

    taf = data[0]
    raw = taf.get("rawTAF", "N/A")
    icao_id = taf.get("icaoId", icao).upper()
    station_name = taf.get("stnName", "")

    embed = discord.Embed(
        title=f"🌤️ TAF — {icao_id}{' | ' + station_name if station_name else ''}",
        description=f"```{raw}```",
        colour=discord.Colour.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Source: aviationweather.gov (NOAA)")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="wx", description="Get METAR + TAF together for an airport")
async def wx_cmd(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    metar_data = await fetch_json(AWC_METAR_URL, params={"ids": icao, "format": "json", "hours": 2})
    taf_data = await fetch_json(AWC_TAF_URL, params={"ids": icao, "format": "json"})

    embeds = []
    if metar_data and isinstance(metar_data, list) and metar_data:
        embeds.append(format_metar_embed(metar_data[0]))
    else:
        embeds.append(discord.Embed(title=f"METAR — {icao}", description="No METAR available.", colour=discord.Colour.greyple()))

    if taf_data and isinstance(taf_data, list) and taf_data:
        raw = taf_data[0].get("rawTAF", "N/A")
        taf_embed = discord.Embed(
            title=f"🌤️ TAF — {icao}",
            description=f"```{raw}```",
            colour=discord.Colour.blue(),
        )
        embeds.append(taf_embed)

    await interaction.followup.send(embeds=embeds)


# --------------------------------------------------------------------------- #
# Slash commands — VATSIM
# --------------------------------------------------------------------------- #

@bot.tree.command(name="vatsim_stats", description="Show live VATSIM network statistics")
async def vatsim_stats(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return

    pilots = data.get("pilots", [])
    controllers = data.get("controllers", [])
    prefiles = data.get("prefiles", [])
    updated = data.get("general", {}).get("update_timestamp", "N/A")

    embed = discord.Embed(
        title="🌐 VATSIM Live Network Stats",
        colour=discord.Colour.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="✈️ Pilots Online", value=str(len(pilots)), inline=True)
    embed.add_field(name="🎙️ ATC Online", value=str(len(controllers)), inline=True)
    embed.add_field(name="📋 Prefiles", value=str(len(prefiles)), inline=True)
    embed.add_field(name="Last Updated", value=updated[:19].replace("T", " ") + "Z" if updated != "N/A" else "N/A", inline=False)
    embed.set_footer(text="Source: data.vatsim.net")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="pilot", description="Look up a VATSIM pilot by callsign")
async def pilot_cmd(interaction: discord.Interaction, callsign: str):
    await interaction.response.defer()
    callsign = callsign.upper().strip()
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return

    pilot = next((p for p in data.get("pilots", []) if p.get("callsign", "").upper() == callsign), None)
    if not pilot:
        await interaction.followup.send(f"❌ No pilot found with callsign **{callsign}**.")
        return

    fp = pilot.get("flight_plan") or {}

    embed = discord.Embed(
        title=f"✈️ Pilot: {callsign}",
        colour=discord.Colour.teal(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="CID", value=str(pilot.get("cid", "N/A")), inline=True)
    embed.add_field(name="Name", value=pilot.get("name", "N/A"), inline=True)
    embed.add_field(name="Server", value=pilot.get("server", "N/A"), inline=True)
    embed.add_field(name="Aircraft", value=fp.get("aircraft_faa", fp.get("aircraft", "N/A")), inline=True)
    embed.add_field(name="Departure", value=fp.get("departure", "N/A"), inline=True)
    embed.add_field(name="Arrival", value=fp.get("arrival", "N/A"), inline=True)
    embed.add_field(name="Altitude", value=f"FL{int(pilot.get('altitude', 0)) // 100}" if pilot.get("altitude") else "N/A", inline=True)
    embed.add_field(name="Ground Speed", value=f"{pilot.get('groundspeed', 'N/A')} kt", inline=True)
    embed.add_field(name="Heading", value=f"{pilot.get('heading', 'N/A')}°", inline=True)
    embed.add_field(name="Cruise Alt", value=fp.get("altitude", "N/A"), inline=True)
    embed.add_field(name="Route", value=fp.get("route", "N/A")[:1000] or "N/A", inline=False)
    embed.add_field(name="Remarks", value=fp.get("remarks", "N/A")[:500] or "N/A", inline=False)

    logon = pilot.get("logon_time", "")
    if logon:
        try:
            logon_dt = datetime.fromisoformat(logon.replace("Z", "+00:00"))
            online_mins = int((datetime.now(timezone.utc) - logon_dt).total_seconds() / 60)
            embed.add_field(name="Online For", value=f"{online_mins // 60}h {online_mins % 60}m", inline=True)
        except Exception:
            pass

    embed.set_footer(text="Source: VATSIM Data Feed v3")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="atc", description="Show active ATC at an airport or facility (e.g. KSFO, YSSY_TWR)")
async def atc_cmd(interaction: discord.Interaction, station: str):
    await interaction.response.defer()
    station = station.upper().strip()
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return

    controllers = [
        c for c in data.get("controllers", [])
        if station in c.get("callsign", "").upper()
    ]

    if not controllers:
        await interaction.followup.send(f"❌ No ATC online matching **{station}**.")
        return

    embed = discord.Embed(
        title=f"🎙️ ATC at {station}",
        colour=discord.Colour.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    for c in controllers[:10]:  # cap at 10
        callsign = c.get("callsign", "?")
        name = c.get("name", "?")
        freq = c.get("frequency", "?")
        rating = _rating_name(c.get("rating", 0))
        atis_raw = c.get("text_atis")
        atis = "\n".join(atis_raw) if isinstance(atis_raw, list) else (atis_raw or "")

        logon = c.get("logon_time", "")
        online_str = ""
        try:
            logon_dt = datetime.fromisoformat(logon.replace("Z", "+00:00"))
            mins = int((datetime.now(timezone.utc) - logon_dt).total_seconds() / 60)
            online_str = f" | Online {mins // 60}h {mins % 60}m"
        except Exception:
            pass

        value = f"**{name}** ({rating}) — {freq} MHz{online_str}"
        if atis:
            value += f"\n```{atis[:400]}```"

        embed.add_field(name=callsign, value=value, inline=False)

    embed.set_footer(text="Source: VATSIM Data Feed v3")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="atis", description="Show ATIS/D-ATIS for a facility on VATSIM")
async def atis_cmd(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return

    atis_stations = [
        c for c in data.get("atis", [])
        if icao in c.get("callsign", "").upper()
    ] + [
        c for c in data.get("controllers", [])
        if "ATIS" in c.get("callsign", "").upper() and icao in c.get("callsign", "").upper()
    ]

    if not atis_stations:
        await interaction.followup.send(f"❌ No ATIS found for **{icao}** on VATSIM.")
        return

    embed = discord.Embed(
        title=f"📻 ATIS — {icao}",
        colour=discord.Colour.dark_blue(),
        timestamp=datetime.now(timezone.utc),
    )
    for a in atis_stations[:3]:
        raw_atis = a.get("text_atis")
        atis_text = "\n".join(raw_atis) if isinstance(raw_atis, list) else (raw_atis or "No text available")
        embed.add_field(
            name=a.get("callsign", icao),
            value=f"**Freq:** {a.get('frequency', '?')} MHz\n```{atis_text[:600]}```",
            inline=False,
        )
    embed.set_footer(text="Source: VATSIM Data Feed v3")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="traffic", description="Show pilots departing/arriving at an airport on VATSIM")
async def traffic_cmd(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return

    departures = [
        p for p in data.get("pilots", [])
        if (p.get("flight_plan") or {}).get("departure", "").upper() == icao
    ]
    arrivals = [
        p for p in data.get("pilots", [])
        if (p.get("flight_plan") or {}).get("arrival", "").upper() == icao
    ]

    embed = discord.Embed(
        title=f"🛫 Traffic at {icao} on VATSIM",
        colour=discord.Colour.blurple(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name=f"🛫 Departures ({len(departures)})",
        value=_format_traffic_list(departures, "departure") or "None",
        inline=False,
    )
    embed.add_field(
        name=f"🛬 Arrivals ({len(arrivals)})",
        value=_format_traffic_list(arrivals, "arrival") or "None",
        inline=False,
    )
    embed.set_footer(text="Source: VATSIM Data Feed v3")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="find_pilot", description="Search for a VATSIM pilot by CID or partial callsign")
async def find_pilot_cmd(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return

    q = query.upper().strip()
    matches = [
        p for p in data.get("pilots", [])
        if q in p.get("callsign", "").upper() or str(p.get("cid", "")) == q
    ][:8]

    if not matches:
        await interaction.followup.send(f"❌ No pilots found matching **{query}**.")
        return

    embed = discord.Embed(
        title=f"🔍 VATSIM Pilot Search: {query}",
        colour=discord.Colour.teal(),
        timestamp=datetime.now(timezone.utc),
    )
    for p in matches:
        fp = p.get("flight_plan") or {}
        dep = fp.get("departure", "?")
        arr = fp.get("arrival", "?")
        alt = p.get("altitude", 0)
        gs = p.get("groundspeed", 0)
        embed.add_field(
            name=p.get("callsign", "?"),
            value=f"{p.get('name','?')} (CID {p.get('cid','?')})\n{dep}→{arr} | FL{int(alt)//100} | {gs}kt",
            inline=True,
        )
    embed.set_footer(text="Source: VATSIM Data Feed v3")
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="help", description="Show all SkyWatch commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✈️ SkyWatch — Aviation Discord Bot",
        description="All commands are slash commands. No API keys required!",
        colour=discord.Colour.gold(),
    )
    embed.add_field(
        name="🌤️ Weather (NOAA/aviationweather.gov)",
        value=(
            "`/metar <ICAO>` — Latest METAR\n"
            "`/taf <ICAO>` — Latest TAF\n"
            "`/wx <ICAO>` — METAR + TAF together"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛩️ VATSIM Network",
        value=(
            "`/vatsim_stats` — Live network totals\n"
            "`/pilot <callsign>` — Pilot details\n"
            "`/find_pilot <query>` — Search by callsign or CID\n"
            "`/atc <station>` — ATC online at a facility\n"
            "`/atis <ICAO>` — ATIS information\n"
            "`/traffic <ICAO>` — Departures & arrivals"
        ),
        inline=False,
    )
    embed.set_footer(text="Data: aviationweather.gov (NOAA) + data.vatsim.net — Zero cost, no API keys needed")
    await interaction.response.send_message(embed=embed)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _rating_name(rating: int) -> str:
    ratings = {1: "OBS", 2: "S1", 3: "S2", 4: "S3", 5: "C1", 7: "C3", 8: "I1", 10: "I3", 11: "SUP", 12: "ADM"}
    return ratings.get(rating, str(rating))


def _format_traffic_list(pilots: list, side: str) -> str:
    lines = []
    for p in pilots[:10]:
        cs = p.get("callsign", "?")
        fp = p.get("flight_plan") or {}
        other = fp.get("arrival" if side == "departure" else "departure", "?")
        ac = fp.get("aircraft_faa", fp.get("aircraft", "?"))
        alt = p.get("altitude", 0)
        gs = p.get("groundspeed", 0)
        lines.append(f"`{cs}` {ac} → {other} | FL{int(alt)//100} {gs}kt")
    if len(pilots) > 10:
        lines.append(f"...and {len(pilots) - 10} more")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌  DISCORD_TOKEN not set. Create a .env file with DISCORD_TOKEN=your_token_here")
        exit(1)
    bot.run(DISCORD_TOKEN)
