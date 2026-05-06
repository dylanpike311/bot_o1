"""
Aviation Discord Bot
METAR/TAF: aviationweather.gov (NOAA) — free, no key
VATSIM live data: data.vatsim.net/v3/vatsim-data.json — free, no key
"""

import os
import math
import random
import discord
from discord.ext import commands, tasks
import aiohttp
from datetime import datetime, timezone
from dotenv import load_dotenv
from urllib.parse import urlencode

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

VATSIM_DATA_URL = "https://data.vatsim.net/v3/vatsim-data.json"
AWC_METAR_URL = "https://aviationweather.gov/api/data/metar"
AWC_TAF_URL = "https://aviationweather.gov/api/data/taf"

FLIGHT_CAT_COLOURS = {
    "VFR": discord.Colour.green(),
    "MVFR": discord.Colour.blue(),
    "IFR": discord.Colour.red(),
    "LIFR": discord.Colour.purple(),
}

# Approximate cruise speeds (kts) for common aircraft types
AIRCRAFT_SPEEDS = {
    "B737": 450, "B738": 450, "B739": 450,
    "B744": 490, "B748": 490, "B772": 490, "B77W": 490, "B788": 490, "B789": 490,
    "A319": 450, "A320": 450, "A321": 450,
    "A332": 490, "A333": 490, "A343": 490, "A359": 490, "A35K": 490,
    "B190": 280, "DH8D": 280, "E175": 420, "E190": 430,
    "C172": 120, "C208": 180, "PC12": 270,
    "CRJ2": 430, "CRJ7": 430, "CRJ9": 430,
}

# SimBrief aircraft type mapping
SIMBRIEF_TYPES = {
    "B737": "B737", "B738": "B738", "B739": "B739",
    "B744": "B744", "B748": "B748", "B772": "B772", "B77W": "B77W",
    "B788": "B788", "B789": "B789",
    "A319": "A319", "A320": "A320", "A321": "A321",
    "A332": "A332", "A333": "A333", "A343": "A343", "A359": "A359",
    "B190": "B190", "DH8D": "DH8D", "E175": "E175", "E190": "E190",
    "C172": "C172", "C208": "C208", "CRJ2": "CRJ2", "CRJ7": "CRJ7", "CRJ9": "CRJ9",
}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents, help_command=None)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def fetch_json(url: str, params: dict = None):
    headers = {"User-Agent": "AviationDiscordBot/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            return None


def haversine_nm(lat1, lon1, lat2, lon2) -> float:
    """Great circle distance in nautical miles."""
    R = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def flight_category_from_metar(metar_data: dict) -> str:
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
    altim = metar_data.get("altim", "N/A")
    clouds = metar_data.get("clouds", [])
    cloud_str = ", ".join(f"{c.get('cover','?')} {c.get('base','?')}ft" for c in clouds) if clouds else "Clear"
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


def simbrief_url(origin: str, dest: str, aircraft: str) -> str:
    ac_type = SIMBRIEF_TYPES.get(aircraft.upper(), aircraft.upper())
    params = {"orig": origin, "dest": dest, "type": ac_type}
    return f"https://www.simbrief.com/system/dispatch.system.php?{urlencode(params)}"


# --------------------------------------------------------------------------- #
# Bot events
# --------------------------------------------------------------------------- #

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Bot online as {bot.user} ({bot.user.id})")
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
# Weather commands
# --------------------------------------------------------------------------- #

@bot.tree.command(name="metar", description="Fetch the latest METAR for an airport (ICAO code)")
async def metar_cmd(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    data = await fetch_json(AWC_METAR_URL, params={"ids": icao, "format": "json", "hours": 2})
    if not data or not isinstance(data, list) or len(data) == 0:
        await interaction.followup.send(f"❌ No METAR found for **{icao}**. Check the ICAO code.")
        return
    await interaction.followup.send(embed=format_metar_embed(data[0]))


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
        embeds.append(discord.Embed(title=f"🌤️ TAF — {icao}", description=f"```{raw}```", colour=discord.Colour.blue()))
    await interaction.followup.send(embeds=embeds)


# --------------------------------------------------------------------------- #
# VATSIM commands
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
    embed = discord.Embed(title="🌐 VATSIM Live Network Stats", colour=discord.Colour.gold(), timestamp=datetime.now(timezone.utc))
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
    embed = discord.Embed(title=f"✈️ Pilot: {callsign}", colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
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


@bot.tree.command(name="atc", description="Show active ATC at an airport or facility (e.g. KSFO, EGLL_APP)")
async def atc_cmd(interaction: discord.Interaction, station: str):
    await interaction.response.defer()
    station = station.upper().strip()
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    controllers = [c for c in data.get("controllers", []) if station in c.get("callsign", "").upper()]
    if not controllers:
        await interaction.followup.send(f"❌ No ATC online matching **{station}**.")
        return
    embed = discord.Embed(title=f"🎙️ ATC at {station}", colour=discord.Colour.orange(), timestamp=datetime.now(timezone.utc))
    for c in controllers[:10]:
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
        c for c in data.get("atis", []) if icao in c.get("callsign", "").upper()
    ] + [
        c for c in data.get("controllers", [])
        if "ATIS" in c.get("callsign", "").upper() and icao in c.get("callsign", "").upper()
    ]
    if not atis_stations:
        await interaction.followup.send(f"❌ No ATIS found for **{icao}** on VATSIM.")
        return
    embed = discord.Embed(title=f"📻 ATIS — {icao}", colour=discord.Colour.dark_blue(), timestamp=datetime.now(timezone.utc))
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
    departures = [p for p in data.get("pilots", []) if (p.get("flight_plan") or {}).get("departure", "").upper() == icao]
    arrivals = [p for p in data.get("pilots", []) if (p.get("flight_plan") or {}).get("arrival", "").upper() == icao]
    embed = discord.Embed(title=f"🛫 Traffic at {icao} on VATSIM", colour=discord.Colour.blurple(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name=f"🛫 Departures ({len(departures)})", value=_format_traffic_list(departures, "departure") or "None", inline=False)
    embed.add_field(name=f"🛬 Arrivals ({len(arrivals)})", value=_format_traffic_list(arrivals, "arrival") or "None", inline=False)
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
    matches = [p for p in data.get("pilots", []) if q in p.get("callsign", "").upper() or str(p.get("cid", "")) == q][:8]
    if not matches:
        await interaction.followup.send(f"❌ No pilots found matching **{query}**.")
        return
    embed = discord.Embed(title=f"🔍 VATSIM Pilot Search: {query}", colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
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


# --------------------------------------------------------------------------- #
# Route Generator
# --------------------------------------------------------------------------- #

@bot.tree.command(
    name="route",
    description="Find a route with live ATC coverage. E.g. /route B738 2h  or  /route B738 2h KSFO"
)
async def route_cmd(
    interaction: discord.Interaction,
    aircraft: str,
    flight_time: str,
    origin: str = None,
):
    await interaction.response.defer()

    # Parse flight time — accept "2h", "2.5h", "90m", "2"
    ft = flight_time.lower().strip()
    try:
        if "h" in ft:
            hours = float(ft.replace("h", ""))
        elif "m" in ft:
            hours = float(ft.replace("m", "")) / 60
        else:
            hours = float(ft)
    except ValueError:
        await interaction.followup.send("❌ Invalid flight time. Use formats like `2h`, `90m`, or `2.5h`.")
        return

    if hours < 0.25 or hours > 12:
        await interaction.followup.send("❌ Flight time must be between 15 minutes and 12 hours.")
        return

    ac = aircraft.upper().strip()
    speed_kts = AIRCRAFT_SPEEDS.get(ac, 450)
    target_nm = speed_kts * hours
    tolerance_nm = target_nm * 0.25  # ±25%
    min_nm = target_nm - tolerance_nm
    max_nm = target_nm + tolerance_nm

    # Fetch VATSIM live data
    data = await fetch_json(VATSIM_DATA_URL)
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return

    controllers = data.get("controllers", [])

    # Build set of airports with ATC coverage
    atc_airports = set()
    atc_map = {}
    for c in controllers:
        cs = c.get("callsign", "")
        parts = cs.split("_")
        if len(parts) >= 2:
            icao = parts[0].upper()
            atc_airports.add(icao)
            atc_map.setdefault(icao, []).append(cs)

    if len(atc_airports) < 2:
        await interaction.followup.send("❌ Not enough ATC coverage on VATSIM right now to suggest a route.")
        return

    # Fetch METARs to get airport coordinates
    atc_list = list(atc_airports)
    metar_data = await fetch_json(AWC_METAR_URL, params={
        "ids": ",".join(atc_list[:50]),
        "format": "json",
        "hours": 2,
    })

    if not metar_data or not isinstance(metar_data, list):
        await interaction.followup.send("❌ Could not fetch airport coordinate data.")
        return

    airports = {}
    for m in metar_data:
        icao_id = m.get("icaoId", "").upper()
        lat = m.get("lat")
        lon = m.get("lon")
        if icao_id and lat is not None and lon is not None:
            airports[icao_id] = {"lat": float(lat), "lon": float(lon)}

    if len(airports) < 2:
        await interaction.followup.send("❌ Not enough airport data available.")
        return

    airport_list = list(airports.keys())

    # If origin specified, validate/fetch it
    if origin:
        origin = origin.upper().strip()
        if origin not in airports:
            origin_metar = await fetch_json(AWC_METAR_URL, params={"ids": origin, "format": "json", "hours": 2})
            if origin_metar and isinstance(origin_metar, list) and origin_metar:
                m = origin_metar[0]
                lat = m.get("lat")
                lon = m.get("lon")
                if lat and lon:
                    airports[origin] = {"lat": float(lat), "lon": float(lon)}
                    airport_list.append(origin)
                else:
                    await interaction.followup.send(f"❌ Could not find coordinates for **{origin}**.")
                    return
            else:
                await interaction.followup.send(f"❌ Could not find airport **{origin}**.")
                return

    # Find matching pairs
    candidates = []
    origins_to_check = [origin] if origin else random.sample(airport_list, min(20, len(airport_list)))

    for dep in origins_to_check:
        dep_info = airports.get(dep)
        if not dep_info:
            continue
        for arr in airport_list:
            if arr == dep:
                continue
            arr_info = airports.get(arr)
            if not arr_info:
                continue
            dist = haversine_nm(dep_info["lat"], dep_info["lon"], arr_info["lat"], arr_info["lon"])
            if min_nm <= dist <= max_nm:
                dep_has_atc = dep in atc_airports
                arr_has_atc = arr in atc_airports
                score = (2 if dep_has_atc else 0) + (2 if arr_has_atc else 0)
                candidates.append({
                    "dep": dep,
                    "arr": arr,
                    "dist_nm": dist,
                    "flight_time_h": dist / speed_kts,
                    "dep_atc": atc_map.get(dep, []),
                    "arr_atc": atc_map.get(arr, []),
                    "score": score,
                })

    if not candidates:
        await interaction.followup.send(
            f"❌ No routes found within ~{target_nm:.0f} NM ({hours}h in a {ac}) with ATC coverage right now.\n"
            f"Try a different flight time or check back when more ATC is online."
        )
        return

    candidates.sort(key=lambda x: -x["score"])
    top = candidates[:3]

    embed = discord.Embed(
        title=f"🗺️ Route Suggestions — {ac} | ~{hours:.1f}h",
        description=(
            f"Routes with live VATSIM ATC coverage, within ±25% of your target flight time.\n"
            f"Click **Open in SimBrief** to plan the full route with airways and fuel."
        ),
        colour=discord.Colour.green(),
        timestamp=datetime.now(timezone.utc),
    )

    for i, r in enumerate(top, 1):
        dep_atc_str = ", ".join(r["dep_atc"]) if r["dep_atc"] else "No ATC"
        arr_atc_str = ", ".join(r["arr_atc"]) if r["arr_atc"] else "No ATC"
        flt_h = int(r["flight_time_h"])
        flt_m = int((r["flight_time_h"] % 1) * 60)
        sb_url = simbrief_url(r["dep"], r["arr"], ac)

        embed.add_field(
            name=f"Option {i}: {r['dep']} → {r['arr']}",
            value=(
                f"**Distance:** {r['dist_nm']:.0f} NM | **Est. time:** {flt_h}h {flt_m}m\n"
                f"**Dep ATC:** {dep_atc_str}\n"
                f"**Arr ATC:** {arr_atc_str}\n"
                f"[📋 Open in SimBrief]({sb_url})"
            ),
            inline=False,
        )

    embed.set_footer(text="ATC positions are live and may change. SimBrief handles actual routing & fuel.")
    await interaction.followup.send(embed=embed)


# --------------------------------------------------------------------------- #
# Help
# --------------------------------------------------------------------------- #

@bot.tree.command(name="help", description="Show all available commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="✈️ Aviation Bot — Commands",
        description="All slash commands. Zero cost, no API keys required.",
        colour=discord.Colour.gold(),
    )
    embed.add_field(
        name="🌤️ Weather (aviationweather.gov / NOAA)",
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
    embed.add_field(
        name="🗺️ Route Generator",
        value=(
            "`/route <aircraft> <time>` — Find routes with live ATC coverage\n"
            "`/route <aircraft> <time> <origin>` — Fix your departure airport\n"
            "Examples: `/route B738 2h` · `/route A320 90m EGLL`\n"
            "Generates a SimBrief link pre-filled with origin, destination & aircraft."
        ),
        inline=False,
    )
    embed.set_footer(text="Data: aviationweather.gov (NOAA) + data.vatsim.net — Zero cost, no API keys")
    await interaction.response.send_message(embed=embed)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌  DISCORD_TOKEN not set. Create a .env file with DISCORD_TOKEN=your_token_here")
        exit(1)
    bot.run(DISCORD_TOKEN)
