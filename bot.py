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

AIRCRAFT_SPEEDS = {
    "B737": 450, "B738": 450, "B739": 450,
    "B744": 490, "B748": 490, "B772": 490, "B77W": 490, "B788": 490, "B789": 490,
    "A319": 450, "A320": 450, "A321": 450,
    "A332": 490, "A333": 490, "A343": 490, "A359": 490, "A35K": 490,
    "B190": 280, "DH8D": 280, "E175": 420, "E190": 430,
    "C172": 120, "C208": 180, "PC12": 270,
    "CRJ2": 430, "CRJ7": 430, "CRJ9": 430,
}

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
intents.message_content = True  # required for prefix commands
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

async def fetch_json(url: str, params: dict = None):
    headers = {"User-Agent": "AvBot/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json(content_type=None)
            return None


def haversine_nm(lat1, lon1, lat2, lon2) -> float:
    R = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def flight_category_from_metar(m: dict) -> str:
    cat = m.get("flightCategory") or m.get("flight_category", "")
    return cat.upper() if cat else "UNKNOWN"


def wind_str(m: dict) -> str:
    wdir = m.get("wdir", "")
    wspd = m.get("wspd", "")
    wgst = m.get("wgst", "")
    if not wspd:
        return "Calm"
    direction = "VRB" if str(wdir).upper() == "VRB" else f"{wdir}°"
    gust = f" G{wgst}kt" if wgst else ""
    return f"{direction} @ {wspd}kt{gust}"


def build_metar_embed(m: dict) -> discord.Embed:
    icao = m.get("icaoId", "????").upper()
    raw = m.get("rawOb", "N/A")
    cat = flight_category_from_metar(m)
    colour = FLIGHT_CAT_COLOURS.get(cat, discord.Colour.greyple())
    vis = m.get("visib", "N/A")
    temp = m.get("temp", "N/A")
    dewp = m.get("dewp", "N/A")
    altim = m.get("altim", "N/A")
    clouds = m.get("clouds", [])
    cloud_str = ", ".join(f"{c.get('cover','?')} {c.get('base','?')}ft" for c in clouds) if clouds else "Clear"
    altim_inhg = ""
    try:
        altim_inhg = f" ({float(altim) * 0.02953:.2f} inHg)"
    except (TypeError, ValueError):
        pass
    obs_time = m.get("obsTime", "")
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
    embed.add_field(name="Wind", value=wind_str(m), inline=True)
    embed.add_field(name="Visibility", value=f"{vis} SM", inline=True)
    embed.add_field(name="Sky", value=cloud_str, inline=True)
    embed.add_field(name="Temp / Dew", value=f"{temp}°C / {dewp}°C", inline=True)
    embed.add_field(name="Altimeter", value=f"{altim} hPa{altim_inhg}", inline=True)
    embed.add_field(name="Observed", value=obs_dt, inline=False)
    return embed


def rating_name(r: int) -> str:
    return {1:"OBS",2:"S1",3:"S2",4:"S3",5:"C1",7:"C3",8:"I1",10:"I3",11:"SUP",12:"ADM"}.get(r, str(r))


def format_traffic(pilots: list, side: str) -> str:
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
        lines.append(f"...and {len(pilots)-10} more")
    return "\n".join(lines)


def simbrief_url(dep: str, arr: str, ac: str) -> str:
    params = {"orig": dep, "dest": arr, "type": SIMBRIEF_TYPES.get(ac.upper(), ac.upper())}
    return f"https://www.simbrief.com/system/dispatch.system.php?{urlencode(params)}"


async def get_metar(icao: str):
    return await fetch_json(AWC_METAR_URL, params={"ids": icao, "format": "json", "hours": 2})


async def get_taf(icao: str):
    return await fetch_json(AWC_TAF_URL, params={"ids": icao, "format": "json"})


async def get_vatsim():
    return await fetch_json(VATSIM_DATA_URL)


async def build_route(ac: str, hours: float, origin: str = None):
    """Core route-finding logic. Returns (embed, error_str)."""
    speed_kts = AIRCRAFT_SPEEDS.get(ac, 450)
    target_nm = speed_kts * hours
    min_nm = target_nm * 0.75
    max_nm = target_nm * 1.25

    data = await get_vatsim()
    if not data:
        return None, "Could not reach VATSIM data feed."

    controllers = data.get("controllers", [])
    atc_airports = set()
    atc_map = {}
    for c in controllers:
        parts = c.get("callsign", "").split("_")
        if len(parts) >= 2:
            icao = parts[0].upper()
            atc_airports.add(icao)
            atc_map.setdefault(icao, []).append(c.get("callsign", ""))

    if len(atc_airports) < 2:
        return None, "Not enough ATC coverage on VATSIM right now."

    metar_data = await fetch_json(AWC_METAR_URL, params={
        "ids": ",".join(list(atc_airports)[:50]),
        "format": "json",
        "hours": 2,
    })
    if not metar_data or not isinstance(metar_data, list):
        return None, "Could not fetch airport coordinate data."

    airports = {}
    for m in metar_data:
        icao_id = m.get("icaoId", "").upper()
        lat, lon = m.get("lat"), m.get("lon")
        if icao_id and lat is not None and lon is not None:
            airports[icao_id] = {"lat": float(lat), "lon": float(lon)}

    if len(airports) < 2:
        return None, "Not enough airport data available."

    airport_list = list(airports.keys())

    if origin:
        origin = origin.upper()
        if origin not in airports:
            om = await get_metar(origin)
            if om and isinstance(om, list) and om:
                lat, lon = om[0].get("lat"), om[0].get("lon")
                if lat and lon:
                    airports[origin] = {"lat": float(lat), "lon": float(lon)}
                    airport_list.append(origin)
                else:
                    return None, f"Could not find coordinates for **{origin}**."
            else:
                return None, f"Could not find airport **{origin}**."

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
                score = (2 if dep in atc_airports else 0) + (2 if arr in atc_airports else 0)
                candidates.append({
                    "dep": dep, "arr": arr,
                    "dist_nm": dist,
                    "flight_time_h": dist / speed_kts,
                    "dep_atc": atc_map.get(dep, []),
                    "arr_atc": atc_map.get(arr, []),
                    "score": score,
                })

    if not candidates:
        return None, (
            f"No routes found within ~{target_nm:.0f} NM ({hours}h in a {ac}) with ATC coverage right now.\n"
            f"Try a different flight time or check back when more ATC is online."
        )

    candidates.sort(key=lambda x: -x["score"])
    top = candidates[:3]

    embed = discord.Embed(
        title=f"🗺️ Route Suggestions — {ac} | ~{hours:.1f}h",
        description="Routes with live VATSIM ATC coverage. Click SimBrief to plan the full route.",
        colour=discord.Colour.green(),
        timestamp=datetime.now(timezone.utc),
    )
    for i, r in enumerate(top, 1):
        flt_h = int(r["flight_time_h"])
        flt_m = int((r["flight_time_h"] % 1) * 60)
        dep_atc_str = ", ".join(r["dep_atc"]) if r["dep_atc"] else "No ATC"
        arr_atc_str = ", ".join(r["arr_atc"]) if r["arr_atc"] else "No ATC"
        embed.add_field(
            name=f"Option {i}: {r['dep']} → {r['arr']}",
            value=(
                f"**Distance:** {r['dist_nm']:.0f} NM | **Est. time:** {flt_h}h {flt_m}m\n"
                f"**Dep ATC:** {dep_atc_str}\n"
                f"**Arr ATC:** {arr_atc_str}\n"
                f"[📋 Open in SimBrief]({simbrief_url(r['dep'], r['arr'], ac)})"
            ),
            inline=False,
        )
    embed.set_footer(text="ATC positions are live and may change.")
    return embed, None


def parse_flight_time(ft: str):
    """Returns hours as float, or None on error."""
    ft = ft.lower().strip()
    try:
        if "h" in ft:
            return float(ft.replace("h", ""))
        elif "m" in ft:
            return float(ft.replace("m", "")) / 60
        else:
            return float(ft)
    except ValueError:
        return None


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
        data = await get_vatsim()
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
# METAR
# --------------------------------------------------------------------------- #

@bot.tree.command(name="metar", description="Latest METAR for an airport")
async def slash_metar(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_metar(icao.upper().strip())
    if not data or not isinstance(data, list) or not data:
        await interaction.followup.send(f"❌ No METAR found for **{icao.upper()}**.")
        return
    await interaction.followup.send(embed=build_metar_embed(data[0]))

@bot.command(name="metar")
async def prefix_metar(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!metar <ICAO>` e.g. `!metar KSFO`")
        return
    data = await get_metar(icao.upper().strip())
    if not data or not isinstance(data, list) or not data:
        await ctx.send(f"❌ No METAR found for **{icao.upper()}**.")
        return
    await ctx.send(embed=build_metar_embed(data[0]))


# --------------------------------------------------------------------------- #
# TAF
# --------------------------------------------------------------------------- #

@bot.tree.command(name="taf", description="Latest TAF for an airport")
async def slash_taf(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_taf(icao.upper().strip())
    if not data or not isinstance(data, list) or not data:
        await interaction.followup.send(f"❌ No TAF found for **{icao.upper()}**.")
        return
    taf = data[0]
    embed = discord.Embed(
        title=f"🌤️ TAF — {taf.get('icaoId', icao).upper()}",
        description=f"```{taf.get('rawTAF', 'N/A')}```",
        colour=discord.Colour.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    await interaction.followup.send(embed=embed)

@bot.command(name="taf")
async def prefix_taf(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!taf <ICAO>` e.g. `!taf EGLL`")
        return
    data = await get_taf(icao.upper().strip())
    if not data or not isinstance(data, list) or not data:
        await ctx.send(f"❌ No TAF found for **{icao.upper()}**.")
        return
    taf = data[0]
    embed = discord.Embed(
        title=f"🌤️ TAF — {taf.get('icaoId', icao).upper()}",
        description=f"```{taf.get('rawTAF', 'N/A')}```",
        colour=discord.Colour.blue(),
        timestamp=datetime.now(timezone.utc),
    )
    await ctx.send(embed=embed)


# --------------------------------------------------------------------------- #
# WX
# --------------------------------------------------------------------------- #

@bot.tree.command(name="wx", description="METAR + TAF together for an airport")
async def slash_wx(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    metar_data = await get_metar(icao)
    taf_data = await get_taf(icao)
    embeds = []
    if metar_data and isinstance(metar_data, list) and metar_data:
        embeds.append(build_metar_embed(metar_data[0]))
    else:
        embeds.append(discord.Embed(title=f"METAR — {icao}", description="No METAR available.", colour=discord.Colour.greyple()))
    if taf_data and isinstance(taf_data, list) and taf_data:
        embeds.append(discord.Embed(title=f"🌤️ TAF — {icao}", description=f"```{taf_data[0].get('rawTAF','N/A')}```", colour=discord.Colour.blue()))
    await interaction.followup.send(embeds=embeds)

@bot.command(name="wx")
async def prefix_wx(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!wx <ICAO>` e.g. `!wx CYVR`")
        return
    icao = icao.upper().strip()
    metar_data = await get_metar(icao)
    taf_data = await get_taf(icao)
    if metar_data and isinstance(metar_data, list) and metar_data:
        await ctx.send(embed=build_metar_embed(metar_data[0]))
    else:
        await ctx.send(f"No METAR available for **{icao}**.")
    if taf_data and isinstance(taf_data, list) and taf_data:
        embed = discord.Embed(title=f"🌤️ TAF — {icao}", description=f"```{taf_data[0].get('rawTAF','N/A')}```", colour=discord.Colour.blue())
        await ctx.send(embed=embed)


# --------------------------------------------------------------------------- #
# VATSIM Stats
# --------------------------------------------------------------------------- #

@bot.tree.command(name="vatsim_stats", description="Live VATSIM network statistics")
async def slash_vatsim_stats(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    embed = _build_stats_embed(data)
    await interaction.followup.send(embed=embed)

@bot.command(name="vatsim")
async def prefix_vatsim_stats(ctx):
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    await ctx.send(embed=_build_stats_embed(data))

def _build_stats_embed(data: dict) -> discord.Embed:
    pilots = data.get("pilots", [])
    controllers = data.get("controllers", [])
    prefiles = data.get("prefiles", [])
    updated = data.get("general", {}).get("update_timestamp", "N/A")
    embed = discord.Embed(title="🌐 VATSIM Live Network Stats", colour=discord.Colour.gold(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="✈️ Pilots", value=str(len(pilots)), inline=True)
    embed.add_field(name="🎙️ ATC", value=str(len(controllers)), inline=True)
    embed.add_field(name="📋 Prefiles", value=str(len(prefiles)), inline=True)
    embed.add_field(name="Last Updated", value=updated[:19].replace("T", " ") + "Z" if updated != "N/A" else "N/A", inline=False)
    return embed


# --------------------------------------------------------------------------- #
# Pilot lookup
# --------------------------------------------------------------------------- #

@bot.tree.command(name="pilot", description="Look up a VATSIM pilot by callsign")
async def slash_pilot(interaction: discord.Interaction, callsign: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_pilot_embed(data, callsign.upper().strip())
    if err:
        await interaction.followup.send(f"❌ {err}")
    else:
        await interaction.followup.send(embed=embed)

@bot.command(name="pilot")
async def prefix_pilot(ctx, callsign: str = None):
    if not callsign:
        await ctx.send("Usage: `!pilot <callsign>` e.g. `!pilot UAL123`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_pilot_embed(data, callsign.upper().strip())
    if err:
        await ctx.send(f"❌ {err}")
    else:
        await ctx.send(embed=embed)

def _build_pilot_embed(data: dict, callsign: str):
    pilot = next((p for p in data.get("pilots", []) if p.get("callsign", "").upper() == callsign), None)
    if not pilot:
        return None, f"No pilot found with callsign **{callsign}**."
    fp = pilot.get("flight_plan") or {}
    embed = discord.Embed(title=f"✈️ {callsign}", colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name="CID", value=str(pilot.get("cid", "N/A")), inline=True)
    embed.add_field(name="Name", value=pilot.get("name", "N/A"), inline=True)
    embed.add_field(name="Aircraft", value=fp.get("aircraft_faa", fp.get("aircraft", "N/A")), inline=True)
    embed.add_field(name="Departure", value=fp.get("departure", "N/A"), inline=True)
    embed.add_field(name="Arrival", value=fp.get("arrival", "N/A"), inline=True)
    embed.add_field(name="Cruise Alt", value=fp.get("altitude", "N/A"), inline=True)
    embed.add_field(name="Altitude", value=f"FL{int(pilot.get('altitude',0))//100}", inline=True)
    embed.add_field(name="Ground Speed", value=f"{pilot.get('groundspeed','N/A')} kt", inline=True)
    embed.add_field(name="Heading", value=f"{pilot.get('heading','N/A')}°", inline=True)
    embed.add_field(name="Route", value=fp.get("route", "N/A")[:1000] or "N/A", inline=False)
    embed.add_field(name="Remarks", value=fp.get("remarks", "N/A")[:500] or "N/A", inline=False)
    logon = pilot.get("logon_time", "")
    if logon:
        try:
            logon_dt = datetime.fromisoformat(logon.replace("Z", "+00:00"))
            mins = int((datetime.now(timezone.utc) - logon_dt).total_seconds() / 60)
            embed.add_field(name="Online For", value=f"{mins//60}h {mins%60}m", inline=True)
        except Exception:
            pass
    return embed, None


# --------------------------------------------------------------------------- #
# ATC
# --------------------------------------------------------------------------- #

@bot.tree.command(name="atc", description="Show active ATC at a facility e.g. KSFO or EGLL_APP")
async def slash_atc(interaction: discord.Interaction, station: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_atc_embed(data, station.upper().strip())
    if err:
        await interaction.followup.send(f"❌ {err}")
    else:
        await interaction.followup.send(embed=embed)

@bot.command(name="atc")
async def prefix_atc(ctx, station: str = None):
    if not station:
        await ctx.send("Usage: `!atc <station>` e.g. `!atc KSFO` or `!atc EGLL_APP`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_atc_embed(data, station.upper().strip())
    if err:
        await ctx.send(f"❌ {err}")
    else:
        await ctx.send(embed=embed)

def _build_atc_embed(data: dict, station: str):
    controllers = [c for c in data.get("controllers", []) if station in c.get("callsign", "").upper()]
    if not controllers:
        return None, f"No ATC online matching **{station}**."
    embed = discord.Embed(title=f"🎙️ ATC — {station}", colour=discord.Colour.orange(), timestamp=datetime.now(timezone.utc))
    for c in controllers[:10]:
        atis_raw = c.get("text_atis")
        atis = "\n".join(atis_raw) if isinstance(atis_raw, list) else (atis_raw or "")
        logon = c.get("logon_time", "")
        online_str = ""
        try:
            logon_dt = datetime.fromisoformat(logon.replace("Z", "+00:00"))
            mins = int((datetime.now(timezone.utc) - logon_dt).total_seconds() / 60)
            online_str = f" | {mins//60}h {mins%60}m"
        except Exception:
            pass
        value = f"**{c.get('name','?')}** ({rating_name(c.get('rating',0))}) — {c.get('frequency','?')} MHz{online_str}"
        if atis:
            value += f"\n```{atis[:400]}```"
        embed.add_field(name=c.get("callsign", "?"), value=value, inline=False)
    return embed, None


# --------------------------------------------------------------------------- #
# ATIS
# --------------------------------------------------------------------------- #

@bot.tree.command(name="atis", description="Show ATIS for a facility on VATSIM")
async def slash_atis(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_atis_embed(data, icao.upper().strip())
    if err:
        await interaction.followup.send(f"❌ {err}")
    else:
        await interaction.followup.send(embed=embed)

@bot.command(name="atis")
async def prefix_atis(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!atis <ICAO>` e.g. `!atis KLAX`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_atis_embed(data, icao.upper().strip())
    if err:
        await ctx.send(f"❌ {err}")
    else:
        await ctx.send(embed=embed)

def _build_atis_embed(data: dict, icao: str):
    stations = [
        c for c in data.get("atis", []) if icao in c.get("callsign", "").upper()
    ] + [
        c for c in data.get("controllers", [])
        if "ATIS" in c.get("callsign", "").upper() and icao in c.get("callsign", "").upper()
    ]
    if not stations:
        return None, f"No ATIS found for **{icao}** on VATSIM."
    embed = discord.Embed(title=f"📻 ATIS — {icao}", colour=discord.Colour.dark_blue(), timestamp=datetime.now(timezone.utc))
    for a in stations[:3]:
        raw = a.get("text_atis")
        text = "\n".join(raw) if isinstance(raw, list) else (raw or "No text available")
        embed.add_field(
            name=a.get("callsign", icao),
            value=f"**Freq:** {a.get('frequency','?')} MHz\n```{text[:600]}```",
            inline=False,
        )
    return embed, None


# --------------------------------------------------------------------------- #
# Traffic
# --------------------------------------------------------------------------- #

@bot.tree.command(name="traffic", description="Departures and arrivals at an airport on VATSIM")
async def slash_traffic(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    await interaction.followup.send(embed=_build_traffic_embed(data, icao.upper().strip()))

@bot.command(name="traffic")
async def prefix_traffic(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!traffic <ICAO>` e.g. `!traffic EGLL`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    await ctx.send(embed=_build_traffic_embed(data, icao.upper().strip()))

def _build_traffic_embed(data: dict, icao: str) -> discord.Embed:
    deps = [p for p in data.get("pilots", []) if (p.get("flight_plan") or {}).get("departure", "").upper() == icao]
    arrs = [p for p in data.get("pilots", []) if (p.get("flight_plan") or {}).get("arrival", "").upper() == icao]
    embed = discord.Embed(title=f"🛫 Traffic — {icao}", colour=discord.Colour.blurple(), timestamp=datetime.now(timezone.utc))
    embed.add_field(name=f"🛫 Departures ({len(deps)})", value=format_traffic(deps, "departure") or "None", inline=False)
    embed.add_field(name=f"🛬 Arrivals ({len(arrs)})", value=format_traffic(arrs, "arrival") or "None", inline=False)
    return embed


# --------------------------------------------------------------------------- #
# Find Pilot
# --------------------------------------------------------------------------- #

@bot.tree.command(name="find_pilot", description="Search VATSIM pilots by callsign or CID")
async def slash_find_pilot(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_find_pilot_embed(data, query.upper().strip())
    if err:
        await interaction.followup.send(f"❌ {err}")
    else:
        await interaction.followup.send(embed=embed)

@bot.command(name="find")
async def prefix_find_pilot(ctx, *, query: str = None):
    if not query:
        await ctx.send("Usage: `!find <callsign or CID>` e.g. `!find UAL` or `!find 1234567`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    embed, err = _build_find_pilot_embed(data, query.upper().strip())
    if err:
        await ctx.send(f"❌ {err}")
    else:
        await ctx.send(embed=embed)

def _build_find_pilot_embed(data: dict, q: str):
    matches = [
        p for p in data.get("pilots", [])
        if q in p.get("callsign", "").upper() or str(p.get("cid", "")) == q
    ][:8]
    if not matches:
        return None, f"No pilots found matching **{q}**."
    embed = discord.Embed(title=f"🔍 Pilot Search: {q}", colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
    for p in matches:
        fp = p.get("flight_plan") or {}
        alt = p.get("altitude", 0)
        embed.add_field(
            name=p.get("callsign", "?"),
            value=f"{p.get('name','?')} (CID {p.get('cid','?')})\n{fp.get('departure','?')}→{fp.get('arrival','?')} | FL{int(alt)//100} | {p.get('groundspeed',0)}kt",
            inline=True,
        )
    return embed, None


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

@bot.tree.command(name="route", description="Find a route with live ATC coverage. e.g. /route B738 2h  or  /route B738 2h KSFO")
async def slash_route(interaction: discord.Interaction, aircraft: str, flight_time: str, origin: str = None):
    await interaction.response.defer()
    hours = parse_flight_time(flight_time)
    if hours is None or hours < 0.25 or hours > 12:
        await interaction.followup.send("❌ Invalid flight time. Use formats like `2h`, `90m`, or `2.5h` (15min–12h).")
        return
    embed, err = await build_route(aircraft.upper().strip(), hours, origin)
    if err:
        await interaction.followup.send(f"❌ {err}")
    else:
        await interaction.followup.send(embed=embed)

@bot.command(name="route")
async def prefix_route(ctx, aircraft: str = None, flight_time: str = None, origin: str = None):
    if not aircraft or not flight_time:
        await ctx.send("Usage: `!route <aircraft> <time> [origin]`\nExamples: `!route B738 2h` · `!route A320 90m EGLL`")
        return
    hours = parse_flight_time(flight_time)
    if hours is None or hours < 0.25 or hours > 12:
        await ctx.send("❌ Invalid flight time. Use formats like `2h`, `90m`, or `2.5h` (15min–12h).")
        return
    async with ctx.typing():
        embed, err = await build_route(aircraft.upper().strip(), hours, origin)
    if err:
        await ctx.send(f"❌ {err}")
    else:
        await ctx.send(embed=embed)


# --------------------------------------------------------------------------- #
# Help
# --------------------------------------------------------------------------- #

@bot.tree.command(name="help", description="Show all commands")
async def slash_help(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_build_help_embed())

@bot.command(name="help")
async def prefix_help(ctx):
    await ctx.send(embed=_build_help_embed())

def _build_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✈️ Aviation Bot — Commands",
        description="Works with both `!prefix` and `/slash` commands.",
        colour=discord.Colour.gold(),
    )
    embed.add_field(
        name="🌤️ Weather",
        value=(
            "`!metar` `/metar` — Latest METAR\n"
            "`!taf` `/taf` — Latest TAF\n"
            "`!wx` `/wx` — METAR + TAF together"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛩️ VATSIM",
        value=(
            "`!vatsim` `/vatsim_stats` — Network totals\n"
            "`!pilot` `/pilot` — Pilot details by callsign\n"
            "`!find` `/find_pilot` — Search by callsign or CID\n"
            "`!atc` `/atc` — ATC at a facility\n"
            "`!atis` `/atis` — ATIS information\n"
            "`!traffic` `/traffic` — Departures & arrivals"
        ),
        inline=False,
    )
    embed.add_field(
        name="🗺️ Route Generator",
        value=(
            "`!route <aircraft> <time> [origin]`\n"
            "`/route <aircraft> <time> [origin]`\n"
            "Examples: `!route B738 2h` · `!route A320 90m EGLL`\n"
            "Finds routes with live ATC and generates a SimBrief link."
        ),
        inline=False,
    )
    return embed


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌  DISCORD_TOKEN not set.")
        exit(1)
    bot.run(DISCORD_TOKEN)
