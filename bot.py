import os
import math
import random
import csv
import io
import discord
from discord.ext import commands, tasks
import aiohttp
from datetime import datetime, timezone
from dotenv import load_dotenv
from urllib.parse import urlencode

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

VATSIM_DATA_URL   = "https://data.vatsim.net/v3/vatsim-data.json"
AWC_METAR_URL     = "https://aviationweather.gov/api/data/metar"
AWC_TAF_URL       = "https://aviationweather.gov/api/data/taf"
OF_ROUTES_URL     = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
OF_AIRPORTS_URL   = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
OF_AIRLINES_URL   = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"

FLIGHT_CAT_COLOURS = {
    "VFR":  discord.Colour.green(),
    "MVFR": discord.Colour.blue(),
    "IFR":  discord.Colour.red(),
    "LIFR": discord.Colour.purple(),
}

AIRCRAFT_SPEEDS = {
    # Boeing narrowbody
    "B737": 450, "B738": 450, "B739": 450, "B736": 450, "B735": 430,
    # Boeing widebody
    "B744": 490, "B748": 490, "B742": 480,
    "B772": 490, "B77W": 490, "B77L": 490, "B773": 490,
    "B788": 490, "B789": 490, "B78X": 490,
    # Airbus narrowbody
    "A318": 440, "A319": 450, "A320": 450, "A321": 450,
    "A20N": 450, "A21N": 450,  # NEO variants
    # Airbus widebody
    "A332": 490, "A333": 490, "A338": 490, "A339": 490,
    "A343": 490, "A345": 490, "A346": 490,
    "A359": 490, "A35K": 490, "A350": 490,  # A350 family
    "A380": 490, "A388": 490,
    # Regional jets
    "B190": 280, "DH8D": 280, "DH8C": 260, "DH8B": 240, "DH8A": 220,
    "E170": 410, "E175": 420, "E190": 430, "E195": 430,
    "E7W":  430, "E75L": 420, "E75S": 420,
    "CRJ2": 430, "CRJ7": 430, "CRJ9": 430, "CRJX": 430,
    "AT72": 270, "AT76": 270, "AT45": 260,
    # GA / turboprop
    "C172": 120, "C208": 180, "PC12": 270, "TBM9": 300, "SR22": 180,
    "BE20": 260, "BE9L": 220,
    # Other
    "MD11": 490, "DC10": 480, "L101": 480,
    "SF34": 250, "JS41": 230,
}

# Friendly aliases (what users might type -> canonical key)
AIRCRAFT_ALIASES = {
    "A350":  "A359",
    "A35K":  "A35K",
    "A380":  "A388",
    "B737":  "B738",
    "B777":  "B77W",
    "B787":  "B789",
    "B747":  "B744",
    "A330":  "A333",
    "A320N": "A20N",
    "A321N": "A21N",
}

# Airline IATA → (ICAO callsign, full name, typical flight number range)
AIRLINE_INFO = {
    "AA": ("AAL", "American Airlines",   (1,    3000)),
    "UA": ("UAL", "United Airlines",     (1,    2500)),
    "DL": ("DAL", "Delta Air Lines",     (1,    2999)),
    "WN": ("SWA", "Southwest Airlines",  (1,    9999)),
    "B6": ("JBU", "JetBlue Airways",     (1,    2999)),
    "AS": ("ASA", "Alaska Airlines",     (1,    999)),
    "NK": ("NKS", "Spirit Airlines",     (1,    999)),
    "F9": ("FFT", "Frontier Airlines",   (1,    999)),
    "G4": ("AAY", "Allegiant Air",       (100,  999)),
    "HA": ("HAL", "Hawaiian Airlines",   (1,    699)),
    "BA": ("BAW", "British Airways",     (1,    2999)),
    "LH": ("DLH", "Lufthansa",           (1,    2999)),
    "AF": ("AFR", "Air France",          (1,    2999)),
    "KL": ("KLM", "KLM",                 (1,    999)),
    "EK": ("UAE", "Emirates",            (1,    999)),
    "QR": ("QTR", "Qatar Airways",       (1,    999)),
    "EY": ("ETD", "Etihad Airways",      (1,    999)),
    "SQ": ("SIA", "Singapore Airlines",  (1,    999)),
    "CX": ("CPA", "Cathay Pacific",      (1,    999)),
    "QF": ("QFA", "Qantas",              (1,    999)),
    "NZ": ("ANZ", "Air New Zealand",     (1,    999)),
    "AC": ("ACA", "Air Canada",          (1,    999)),
    "WS": ("WJA", "WestJet",             (1,    699)),
    "WG": ("SWG", "Sunwing Airlines",    (100,  999)),
    "TK": ("THY", "Turkish Airlines",    (1,    2999)),
    "FR": ("RYR", "Ryanair",             (1,    9999)),
    "U2": ("EZY", "easyJet",             (1,    9999)),
    "VY": ("VLG", "Vueling",             (1,    9999)),
    "IB": ("IBE", "Iberia",              (1,    999)),
    "AZ": ("ITY", "ITA Airways",         (1,    999)),
    "SK": ("SAS", "Scandinavian Airlines",(1,   999)),
    "AY": ("FIN", "Finnair",             (1,    999)),
    "LX": ("SWR", "Swiss",               (1,    999)),
    "OS": ("AUA", "Austrian Airlines",   (1,    999)),
    "SU": ("AFL", "Aeroflot",            (1,    999)),
    "CZ": ("CSN", "China Southern",      (1,    9999)),
    "CA": ("CCA", "Air China",           (1,    9999)),
    "MU": ("CES", "China Eastern",       (1,    9999)),
    "JL": ("JAL", "Japan Airlines",      (1,    999)),
    "NH": ("ANA", "All Nippon Airways",  (1,    999)),
    "KE": ("KAL", "Korean Air",          (1,    999)),
    "OZ": ("AAR", "Asiana Airlines",     (1,    999)),
    "AI": ("AIC", "Air India",           (1,    999)),
    "6E": ("IGO", "IndiGo",              (1,    9999)),
    "LA": ("LAN", "LATAM Airlines",      (1,    999)),
    "G3": ("GLO", "Gol Transportes",     (1,    9999)),
    "SA": ("SAA", "South African Airways",(1,   999)),
    "ET": ("ETH", "Ethiopian Airlines",  (1,    999)),
    "MS": ("MSR", "EgyptAir",            (1,    999)),
}

# in-memory route table: (src_icao, dst_icao) -> [airline_iata, ...]
_route_table: dict[tuple, list] = {}
# icao -> (lat, lon, name)
_airport_table: dict[str, tuple] = {}
# iata -> (icao_callsign, full_name)  — populated from airlines.dat at startup
_airline_db: dict[str, tuple] = {}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

async def load_openflights_data():
    """Download and parse OpenFlights airports, airlines + routes into memory."""
    global _route_table, _airport_table, _airline_db
    headers = {"User-Agent": "AvBot/1.0"}

    async with aiohttp.ClientSession(headers=headers) as session:

        # --- airlines ---
        try:
            async with session.get(OF_AIRLINES_URL, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    text = await r.text(encoding="utf-8", errors="replace")
                    # columns: id, name, alias, iata, icao, callsign, country, active
                    for row in csv.reader(io.StringIO(text)):
                        if len(row) < 6:
                            continue
                        iata   = row[3].strip().upper()
                        icao   = row[4].strip().upper()
                        name   = row[1].strip().strip('"')
                        active = row[7].strip() if len(row) > 7 else "Y"
                        if (iata and iata != r"\N" and len(iata) <= 3
                                and icao and icao != r"\N" and len(icao) == 3
                                and active == "Y"):
                            _airline_db[iata] = (icao, name)
                    # Overlay our curated table (has number ranges)
                    for iata, info in AIRLINE_INFO.items():
                        _airline_db[iata] = (info[0], info[1])
                    print(f"✅ Airlines loaded: {len(_airline_db)}")
        except Exception as e:
            print(f"⚠️  Airline load failed: {e}")
            # Fall back to static table only
            for iata, info in AIRLINE_INFO.items():
                _airline_db[iata] = (info[0], info[1])

        # --- airports ---
        try:
            async with session.get(OF_AIRPORTS_URL, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    text = await r.text(encoding="utf-8", errors="replace")
                    for row in csv.reader(io.StringIO(text)):
                        if len(row) < 8:
                            continue
                        # id, name, city, country, iata, icao, lat, lon
                        icao = row[5].strip().upper()
                        name = row[1].strip().strip('"')
                        try:
                            lat = float(row[6])
                            lon = float(row[7])
                            if icao and icao != r"\N" and len(icao) == 4:
                                _airport_table[icao] = (lat, lon, name)
                        except ValueError:
                            pass
                    print(f"✅ Airports loaded: {len(_airport_table)}")
        except Exception as e:
            print(f"⚠️  Airport load failed: {e}")

        # --- routes ---
        try:
            async with session.get(OF_ROUTES_URL, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    text = await r.text(encoding="utf-8", errors="replace")
                    count = 0
                    for row in csv.reader(io.StringIO(text)):
                        if len(row) < 5:
                            continue
                        # airline_iata, airline_id, src_icao, src_id, dst_icao, dst_id, ...
                        airline = row[0].strip().upper()
                        src     = row[2].strip().upper()
                        dst     = row[4].strip().upper()
                        if (not src or not dst or src == r"\N" or dst == r"\N"
                                or len(src) != 4 or len(dst) != 4):
                            continue
                        key = (src, dst)
                        _route_table.setdefault(key, [])
                        if airline and airline != r"\N" and airline not in _route_table[key]:
                            _route_table[key].append(airline)
                        count += 1
                    print(f"✅ Routes loaded: {len(_route_table)} unique pairs from {count} entries")
        except Exception as e:
            print(f"⚠️  Route load failed: {e}")


def get_real_flights(src: str, dst: str) -> list[dict]:
    """Return list of realistic flights for a route pair.
    Checks both directions since OpenFlights can be inconsistent."""
    # Try both src->dst and dst->src (routes are directional in OpenFlights)
    airlines = list(_route_table.get((src, dst), []))
    for a in _route_table.get((dst, src), []):
        if a not in airlines:
            airlines.append(a)

    results = []
    for iata in airlines[:4]:
        curated = AIRLINE_INFO.get(iata)
        if curated:
            icao_code, name, num_range = curated
            flt_num = random.randint(num_range[0], num_range[1])
        else:
            db_entry = _airline_db.get(iata)
            if db_entry:
                icao_code, name = db_entry
            else:
                icao_code = iata
                name = iata
            flt_num = random.randint(1, 999)
        results.append({
            "callsign": f"{icao_code}{flt_num}",
            "iata":     f"{iata}{flt_num}",
            "airline":  name,
        })
    return results


# --------------------------------------------------------------------------- #
# Helpers
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
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def flight_cat(m: dict) -> str:
    c = m.get("flightCategory") or m.get("flight_category", "")
    return c.upper() if c else "UNKNOWN"


def wind_str(m: dict) -> str:
    wdir, wspd, wgst = m.get("wdir",""), m.get("wspd",""), m.get("wgst","")
    if not wspd:
        return "Calm"
    d = "VRB" if str(wdir).upper() == "VRB" else f"{wdir}°"
    g = f" G{wgst}kt" if wgst else ""
    return f"{d} @ {wspd}kt{g}"


def build_metar_embed(m: dict) -> discord.Embed:
    icao   = m.get("icaoId","????").upper()
    raw    = m.get("rawOb","N/A")
    cat    = flight_cat(m)
    colour = FLIGHT_CAT_COLOURS.get(cat, discord.Colour.greyple())
    vis    = m.get("visib","N/A")
    temp   = m.get("temp","N/A")
    dewp   = m.get("dewp","N/A")
    altim  = m.get("altim","N/A")
    clouds = m.get("clouds",[])
    cloud_str = ", ".join(f"{c.get('cover','?')} {c.get('base','?')}ft" for c in clouds) if clouds else "Clear"
    inhg = ""
    try:
        inhg = f" ({float(altim)*0.02953:.2f} inHg)"
    except Exception:
        pass
    obs = m.get("obsTime","")
    try:
        obs_dt = datetime.fromtimestamp(int(obs), tz=timezone.utc).strftime("%Y-%m-%d %H:%MZ")
    except Exception:
        obs_dt = obs
    e = discord.Embed(title=f"✈️ METAR — {icao}", description=f"```{raw}```",
                      colour=colour, timestamp=datetime.now(timezone.utc))
    e.add_field(name="Flight Category", value=f"**{cat}**", inline=True)
    e.add_field(name="Wind",            value=wind_str(m),  inline=True)
    e.add_field(name="Visibility",      value=f"{vis} SM",  inline=True)
    e.add_field(name="Sky",             value=cloud_str,    inline=True)
    e.add_field(name="Temp / Dew",      value=f"{temp}°C / {dewp}°C", inline=True)
    e.add_field(name="Altimeter",       value=f"{altim} hPa{inhg}",   inline=True)
    e.add_field(name="Observed",        value=obs_dt,       inline=False)
    return e


def rating_name(r: int) -> str:
    return {1:"OBS",2:"S1",3:"S2",4:"S3",5:"C1",7:"C3",8:"I1",10:"I3",11:"SUP",12:"ADM"}.get(r,str(r))


def fmt_traffic(pilots: list, side: str) -> str:
    lines = []
    for p in pilots[:10]:
        cs = p.get("callsign","?")
        fp = p.get("flight_plan") or {}
        other = fp.get("arrival" if side=="departure" else "departure","?")
        ac  = fp.get("aircraft_faa", fp.get("aircraft","?"))
        alt = p.get("altitude",0)
        gs  = p.get("groundspeed",0)
        lines.append(f"`{cs}` {ac} → {other} | FL{int(alt)//100} {gs}kt")
    if len(pilots)>10:
        lines.append(f"...and {len(pilots)-10} more")
    return "\n".join(lines)


def simbrief_url(dep: str, arr: str, ac: str, airline_icao: str = "", flt_num: str = "") -> str:
    params = {"orig": dep, "dest": arr, "type": ac.upper()}
    if airline_icao:
        params["airline"] = airline_icao
    if flt_num:
        params["fltnum"] = flt_num
    return f"https://dispatch.simbrief.com/options/custom?{urlencode(params)}"


def parse_flight_time(ft: str):
    ft = ft.lower().strip()
    try:
        if "h" in ft:
            return float(ft.replace("h",""))
        elif "m" in ft:
            return float(ft.replace("m",""))/60
        else:
            return float(ft)
    except ValueError:
        return None


async def get_metar(icao): return await fetch_json(AWC_METAR_URL, {"ids":icao,"format":"json","hours":2})
async def get_taf(icao):   return await fetch_json(AWC_TAF_URL,   {"ids":icao,"format":"json"})
async def get_vatsim():    return await fetch_json(VATSIM_DATA_URL)


# --------------------------------------------------------------------------- #
# Route core logic
# --------------------------------------------------------------------------- #

async def build_route(ac: str, hours: float, origin: str = None):
    # Resolve aliases (e.g. A350 -> A359)
    ac = AIRCRAFT_ALIASES.get(ac, ac)
    speed      = AIRCRAFT_SPEEDS.get(ac, 450)
    target_nm  = speed * hours
    min_nm     = target_nm * 0.75
    max_nm     = target_nm * 1.25

    data = await get_vatsim()
    if not data:
        return None, "Could not reach VATSIM data feed."

    # Build ATC coverage map
    atc_airports, atc_map = set(), {}
    for c in data.get("controllers",[]):
        parts = c.get("callsign","").split("_")
        if len(parts) >= 2:
            icao = parts[0].upper()
            atc_airports.add(icao)
            atc_map.setdefault(icao,[]).append(c.get("callsign",""))

    if len(atc_airports) < 2:
        return None, "Not enough ATC coverage on VATSIM right now."

    # Use OpenFlights airport coords if available, else fall back to METAR
    airports = {}
    if _airport_table:
        for icao in atc_airports:
            if icao in _airport_table:
                lat, lon, name = _airport_table[icao]
                airports[icao] = {"lat": lat, "lon": lon, "name": name}
    
    # Fill gaps via METAR
    missing = [a for a in atc_airports if a not in airports]
    if missing:
        md = await fetch_json(AWC_METAR_URL, {"ids": ",".join(missing[:50]), "format":"json","hours":2})
        if md and isinstance(md, list):
            for m in md:
                icao_id = m.get("icaoId","").upper()
                lat, lon = m.get("lat"), m.get("lon")
                if icao_id and lat is not None and lon is not None:
                    airports[icao_id] = {"lat":float(lat),"lon":float(lon),"name":icao_id}

    if len(airports) < 2:
        return None, "Not enough airport data available."

    airport_list = list(airports.keys())

    # Handle fixed origin
    if origin:
        origin = origin.upper()
        if origin not in airports:
            if origin in _airport_table:
                lat, lon, name = _airport_table[origin]
                airports[origin] = {"lat":lat,"lon":lon,"name":name}
                airport_list.append(origin)
            else:
                om = await get_metar(origin)
                if om and isinstance(om,list) and om:
                    lat,lon = om[0].get("lat"), om[0].get("lon")
                    if lat and lon:
                        airports[origin]={"lat":float(lat),"lon":float(lon),"name":origin}
                        airport_list.append(origin)
                    else:
                        return None, f"Could not find coordinates for **{origin}**."
                else:
                    return None, f"Could not find airport **{origin}**."

    # Find candidate pairs
    candidates = []
    origins_to_check = [origin] if origin else random.sample(airport_list, min(25, len(airport_list)))

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
            dist = haversine_nm(dep_info["lat"],dep_info["lon"],arr_info["lat"],arr_info["lon"])
            if not (min_nm <= dist <= max_nm):
                continue
            real_flights = get_real_flights(dep, arr)
            dep_atc = atc_map.get(dep,[])
            arr_atc = atc_map.get(arr,[])
            score = (2 if dep in atc_airports else 0) + (2 if arr in atc_airports else 0) + (3 if real_flights else 0)
            candidates.append({
                "dep": dep, "arr": arr,
                "dep_name": airports[dep].get("name", dep),
                "arr_name": airports[arr].get("name", arr),
                "dist_nm": dist,
                "flight_time_h": dist/speed,
                "dep_atc": dep_atc,
                "arr_atc": arr_atc,
                "real_flights": real_flights,
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
        description="Routes with live VATSIM ATC coverage. Real-world airline routes shown where available.",
        colour=discord.Colour.green(),
        timestamp=datetime.now(timezone.utc),
    )

    for i, r in enumerate(top, 1):
        flt_h = int(r["flight_time_h"])
        flt_m = int((r["flight_time_h"] % 1) * 60)
        dep_atc_str = ", ".join(r["dep_atc"]) if r["dep_atc"] else "No ATC"
        arr_atc_str = ", ".join(r["arr_atc"]) if r["arr_atc"] else "No ATC"

        # Build SimBrief links — one generic + one per real flight
        lines = [
            f"**{r['dep']}** → **{r['arr']}** | {r['dist_nm']:.0f} NM | {flt_h}h {flt_m}m",
            f"🎙️ Dep ATC: {dep_atc_str}",
            f"🎙️ Arr ATC: {arr_atc_str}",
        ]

        if r["real_flights"]:
            lines.append("**Real-world flights on this route:**")
            for f in r["real_flights"]:
                icao_code = f["callsign"][:3] if len(f["callsign"]) > 3 else f["callsign"]
                fnum = f["callsign"][3:]
                sb = simbrief_url(r["dep"], r["arr"], ac, icao_code, fnum)
                lines.append(f"• {f['callsign']} ({f['airline']}) — [Plan in SimBrief]({sb})")
        else:
            sb = simbrief_url(r["dep"], r["arr"], ac)
            lines.append(f"⚠️ No real-world airline routes found for this pair")
            lines.append(f"[📋 Plan in SimBrief anyway]({sb})")

        embed.add_field(name=f"Option {i}", value="\n".join(lines), inline=False)

    embed.set_footer(text="ATC coverage is live. Route data: OpenFlights.")
    return embed, None


# --------------------------------------------------------------------------- #
# Bot events
# --------------------------------------------------------------------------- #

@bot.event
async def on_ready():
    print(f"✅ Bot online as {bot.user} ({bot.user.id})")
    await load_openflights_data()
    await bot.tree.sync()
    update_status.start()


@tasks.loop(minutes=5)
async def update_status():
    try:
        data = await get_vatsim()
        if data:
            pilots = len(data.get("pilots",[]))
            atc    = len(data.get("controllers",[]))
            await bot.change_presence(activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{pilots} pilots | {atc} ATC on VATSIM",
            ))
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# METAR
# --------------------------------------------------------------------------- #

@bot.tree.command(name="metar", description="Latest METAR for an airport")
async def slash_metar(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_metar(icao.upper().strip())
    if not data or not isinstance(data,list) or not data:
        await interaction.followup.send(f"❌ No METAR found for **{icao.upper()}**.")
        return
    await interaction.followup.send(embed=build_metar_embed(data[0]))

@bot.command(name="metar")
async def prefix_metar(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!metar <ICAO>`")
        return
    data = await get_metar(icao.upper().strip())
    if not data or not isinstance(data,list) or not data:
        await ctx.send(f"❌ No METAR found for **{icao.upper()}**.")
        return
    await ctx.send(embed=build_metar_embed(data[0]))


# --------------------------------------------------------------------------- #
# TAF
# --------------------------------------------------------------------------- #

def _taf_embed(taf: dict, icao: str) -> discord.Embed:
    return discord.Embed(
        title=f"🌤️ TAF — {taf.get('icaoId', icao).upper()}",
        description=f"```{taf.get('rawTAF','N/A')}```",
        colour=discord.Colour.blue(),
        timestamp=datetime.now(timezone.utc),
    )

@bot.tree.command(name="taf", description="Latest TAF for an airport")
async def slash_taf(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_taf(icao.upper().strip())
    if not data or not isinstance(data,list) or not data:
        await interaction.followup.send(f"❌ No TAF found for **{icao.upper()}**.")
        return
    await interaction.followup.send(embed=_taf_embed(data[0], icao))

@bot.command(name="taf")
async def prefix_taf(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!taf <ICAO>`")
        return
    data = await get_taf(icao.upper().strip())
    if not data or not isinstance(data,list) or not data:
        await ctx.send(f"❌ No TAF found for **{icao.upper()}**.")
        return
    await ctx.send(embed=_taf_embed(data[0], icao))


# --------------------------------------------------------------------------- #
# WX
# --------------------------------------------------------------------------- #

@bot.tree.command(name="wx", description="METAR + TAF together for an airport")
async def slash_wx(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    icao = icao.upper().strip()
    md = await get_metar(icao)
    td = await get_taf(icao)
    embeds = []
    if md and isinstance(md,list) and md:
        embeds.append(build_metar_embed(md[0]))
    else:
        embeds.append(discord.Embed(title=f"METAR — {icao}", description="No METAR available.", colour=discord.Colour.greyple()))
    if td and isinstance(td,list) and td:
        embeds.append(_taf_embed(td[0], icao))
    await interaction.followup.send(embeds=embeds)

@bot.command(name="wx")
async def prefix_wx(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!wx <ICAO>`")
        return
    icao = icao.upper().strip()
    md = await get_metar(icao)
    td = await get_taf(icao)
    if md and isinstance(md,list) and md:
        await ctx.send(embed=build_metar_embed(md[0]))
    else:
        await ctx.send(f"No METAR available for **{icao}**.")
    if td and isinstance(td,list) and td:
        await ctx.send(embed=_taf_embed(td[0], icao))


# --------------------------------------------------------------------------- #
# VATSIM Stats
# --------------------------------------------------------------------------- #

def _stats_embed(data: dict) -> discord.Embed:
    pilots      = data.get("pilots",[])
    controllers = data.get("controllers",[])
    prefiles    = data.get("prefiles",[])
    updated     = data.get("general",{}).get("update_timestamp","N/A")
    e = discord.Embed(title="🌐 VATSIM Live Network Stats", colour=discord.Colour.gold(), timestamp=datetime.now(timezone.utc))
    e.add_field(name="✈️ Pilots",    value=str(len(pilots)),      inline=True)
    e.add_field(name="🎙️ ATC",      value=str(len(controllers)), inline=True)
    e.add_field(name="📋 Prefiles", value=str(len(prefiles)),    inline=True)
    e.add_field(name="Last Updated", value=updated[:19].replace("T"," ")+"Z" if updated!="N/A" else "N/A", inline=False)
    return e

@bot.tree.command(name="vatsim_stats", description="Live VATSIM network statistics")
async def slash_vatsim_stats(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    await interaction.followup.send(embed=_stats_embed(data))

@bot.command(name="vatsim")
async def prefix_vatsim_stats(ctx):
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    await ctx.send(embed=_stats_embed(data))


# --------------------------------------------------------------------------- #
# Pilot
# --------------------------------------------------------------------------- #

def _pilot_embed(data: dict, callsign: str):
    pilot = next((p for p in data.get("pilots",[]) if p.get("callsign","").upper()==callsign), None)
    if not pilot:
        return None, f"No pilot found with callsign **{callsign}**."
    fp = pilot.get("flight_plan") or {}
    e = discord.Embed(title=f"✈️ {callsign}", colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
    e.add_field(name="CID",          value=str(pilot.get("cid","N/A")),                   inline=True)
    e.add_field(name="Name",         value=pilot.get("name","N/A"),                        inline=True)
    e.add_field(name="Aircraft",     value=fp.get("aircraft_faa",fp.get("aircraft","N/A")),inline=True)
    e.add_field(name="Departure",    value=fp.get("departure","N/A"),                      inline=True)
    e.add_field(name="Arrival",      value=fp.get("arrival","N/A"),                        inline=True)
    e.add_field(name="Cruise Alt",   value=fp.get("altitude","N/A"),                       inline=True)
    e.add_field(name="Altitude",     value=f"FL{int(pilot.get('altitude',0))//100}",       inline=True)
    e.add_field(name="Ground Speed", value=f"{pilot.get('groundspeed','N/A')} kt",         inline=True)
    e.add_field(name="Heading",      value=f"{pilot.get('heading','N/A')}°",               inline=True)
    e.add_field(name="Route",        value=fp.get("route","N/A")[:1000] or "N/A",          inline=False)
    e.add_field(name="Remarks",      value=fp.get("remarks","N/A")[:500] or "N/A",         inline=False)
    logon = pilot.get("logon_time","")
    if logon:
        try:
            ld = datetime.fromisoformat(logon.replace("Z","+00:00"))
            mins = int((datetime.now(timezone.utc)-ld).total_seconds()/60)
            e.add_field(name="Online For", value=f"{mins//60}h {mins%60}m", inline=True)
        except Exception:
            pass
    return e, None

@bot.tree.command(name="pilot", description="Look up a VATSIM pilot by callsign")
async def slash_pilot(interaction: discord.Interaction, callsign: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _pilot_embed(data, callsign.upper().strip())
    await (interaction.followup.send(f"❌ {err}") if err else interaction.followup.send(embed=e))

@bot.command(name="pilot")
async def prefix_pilot(ctx, callsign: str = None):
    if not callsign:
        await ctx.send("Usage: `!pilot <callsign>`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _pilot_embed(data, callsign.upper().strip())
    await (ctx.send(f"❌ {err}") if err else ctx.send(embed=e))


# --------------------------------------------------------------------------- #
# ATC
# --------------------------------------------------------------------------- #

def _atc_embed(data: dict, station: str):
    controllers = [c for c in data.get("controllers",[]) if station in c.get("callsign","").upper()]
    if not controllers:
        return None, f"No ATC online matching **{station}**."
    e = discord.Embed(title=f"🎙️ ATC — {station}", colour=discord.Colour.orange(), timestamp=datetime.now(timezone.utc))
    for c in controllers[:10]:
        atis_raw = c.get("text_atis")
        atis = "\n".join(atis_raw) if isinstance(atis_raw,list) else (atis_raw or "")
        logon = c.get("logon_time","")
        online_str = ""
        try:
            ld = datetime.fromisoformat(logon.replace("Z","+00:00"))
            mins = int((datetime.now(timezone.utc)-ld).total_seconds()/60)
            online_str = f" | {mins//60}h {mins%60}m"
        except Exception:
            pass
        val = f"**{c.get('name','?')}** ({rating_name(c.get('rating',0))}) — {c.get('frequency','?')} MHz{online_str}"
        if atis:
            val += f"\n```{atis[:400]}```"
        e.add_field(name=c.get("callsign","?"), value=val, inline=False)
    return e, None

@bot.tree.command(name="atc", description="Show active ATC at a facility e.g. KSFO or EGLL_APP")
async def slash_atc(interaction: discord.Interaction, station: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _atc_embed(data, station.upper().strip())
    await (interaction.followup.send(f"❌ {err}") if err else interaction.followup.send(embed=e))

@bot.command(name="atc")
async def prefix_atc(ctx, station: str = None):
    if not station:
        await ctx.send("Usage: `!atc <station>` e.g. `!atc KSFO`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _atc_embed(data, station.upper().strip())
    await (ctx.send(f"❌ {err}") if err else ctx.send(embed=e))


# --------------------------------------------------------------------------- #
# ATIS
# --------------------------------------------------------------------------- #

def _atis_embed(data: dict, icao: str):
    stations = [
        c for c in data.get("atis",[]) if icao in c.get("callsign","").upper()
    ] + [
        c for c in data.get("controllers",[])
        if "ATIS" in c.get("callsign","").upper() and icao in c.get("callsign","").upper()
    ]
    if not stations:
        return None, f"No ATIS found for **{icao}** on VATSIM."
    e = discord.Embed(title=f"📻 ATIS — {icao}", colour=discord.Colour.dark_blue(), timestamp=datetime.now(timezone.utc))
    for a in stations[:3]:
        raw = a.get("text_atis")
        text = "\n".join(raw) if isinstance(raw,list) else (raw or "No text available")
        e.add_field(name=a.get("callsign",icao), value=f"**Freq:** {a.get('frequency','?')} MHz\n```{text[:600]}```", inline=False)
    return e, None

@bot.tree.command(name="atis", description="Show ATIS for a facility on VATSIM")
async def slash_atis(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _atis_embed(data, icao.upper().strip())
    await (interaction.followup.send(f"❌ {err}") if err else interaction.followup.send(embed=e))

@bot.command(name="atis")
async def prefix_atis(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!atis <ICAO>`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _atis_embed(data, icao.upper().strip())
    await (ctx.send(f"❌ {err}") if err else ctx.send(embed=e))


# --------------------------------------------------------------------------- #
# Traffic
# --------------------------------------------------------------------------- #

def _traffic_embed(data: dict, icao: str) -> discord.Embed:
    deps = [p for p in data.get("pilots",[]) if (p.get("flight_plan") or {}).get("departure","").upper()==icao]
    arrs = [p for p in data.get("pilots",[]) if (p.get("flight_plan") or {}).get("arrival","").upper()==icao]
    e = discord.Embed(title=f"🛫 Traffic — {icao}", colour=discord.Colour.blurple(), timestamp=datetime.now(timezone.utc))
    e.add_field(name=f"🛫 Departures ({len(deps)})", value=fmt_traffic(deps,"departure") or "None", inline=False)
    e.add_field(name=f"🛬 Arrivals ({len(arrs)})",   value=fmt_traffic(arrs,"arrival")   or "None", inline=False)
    return e

@bot.tree.command(name="traffic", description="Departures and arrivals at an airport on VATSIM")
async def slash_traffic(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    await interaction.followup.send(embed=_traffic_embed(data, icao.upper().strip()))

@bot.command(name="traffic")
async def prefix_traffic(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!traffic <ICAO>`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    await ctx.send(embed=_traffic_embed(data, icao.upper().strip()))


# --------------------------------------------------------------------------- #
# Find Pilot
# --------------------------------------------------------------------------- #

def _find_embed(data: dict, q: str):
    matches = [
        p for p in data.get("pilots",[])
        if q in p.get("callsign","").upper() or str(p.get("cid",""))==q
    ][:8]
    if not matches:
        return None, f"No pilots found matching **{q}**."
    e = discord.Embed(title=f"🔍 Pilot Search: {q}", colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
    for p in matches:
        fp  = p.get("flight_plan") or {}
        alt = p.get("altitude",0)
        e.add_field(
            name=p.get("callsign","?"),
            value=f"{p.get('name','?')} (CID {p.get('cid','?')})\n{fp.get('departure','?')}→{fp.get('arrival','?')} | FL{int(alt)//100} | {p.get('groundspeed',0)}kt",
            inline=True,
        )
    return e, None

@bot.tree.command(name="find_pilot", description="Search VATSIM pilots by callsign or CID")
async def slash_find_pilot(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    data = await get_vatsim()
    if not data:
        await interaction.followup.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _find_embed(data, query.upper().strip())
    await (interaction.followup.send(f"❌ {err}") if err else interaction.followup.send(embed=e))

@bot.command(name="find")
async def prefix_find_pilot(ctx, *, query: str = None):
    if not query:
        await ctx.send("Usage: `!find <callsign or CID>`")
        return
    data = await get_vatsim()
    if not data:
        await ctx.send("❌ Could not reach VATSIM data feed.")
        return
    e, err = _find_embed(data, query.upper().strip())
    await (ctx.send(f"❌ {err}") if err else ctx.send(embed=e))


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

@bot.tree.command(name="route", description="Find a route with live ATC coverage e.g. /route B738 2h  or  /route B738 2h KSFO")
async def slash_route(interaction: discord.Interaction, aircraft: str, flight_time: str, origin: str = None):
    await interaction.response.defer()
    hours = parse_flight_time(flight_time)
    if hours is None or hours < 0.25 or hours > 12:
        await interaction.followup.send("❌ Invalid flight time. Use `2h`, `90m`, or `2.5h` (15min–12h).")
        return
    e, err = await build_route(aircraft.upper().strip(), hours, origin)
    await (interaction.followup.send(f"❌ {err}") if err else interaction.followup.send(embed=e))

@bot.command(name="route")
async def prefix_route(ctx, aircraft: str = None, flight_time: str = None, origin: str = None):
    if not aircraft or not flight_time:
        await ctx.send("Usage: `!route <aircraft> <time> [origin]`\nExamples: `!route B738 2h` · `!route A320 90m EGLL`")
        return
    hours = parse_flight_time(flight_time)
    if hours is None or hours < 0.25 or hours > 12:
        await ctx.send("❌ Invalid flight time. Use `2h`, `90m`, or `2.5h` (15min–12h).")
        return
    async with ctx.typing():
        e, err = await build_route(aircraft.upper().strip(), hours, origin)
    await (ctx.send(f"❌ {err}") if err else ctx.send(embed=e))


# --------------------------------------------------------------------------- #
# Help
# --------------------------------------------------------------------------- #

def _help_embed() -> discord.Embed:
    e = discord.Embed(title="✈️ Aviation Bot — Commands", description="Works with both `!prefix` and `/slash` commands.", colour=discord.Colour.gold())
    e.add_field(name="🌤️ Weather", value="`!metar` `/metar` — METAR\n`!taf` `/taf` — TAF\n`!wx` `/wx` — METAR + TAF", inline=False)
    e.add_field(name="🛩️ VATSIM", value=(
        "`!vatsim` `/vatsim_stats` — Network totals\n"
        "`!pilot` `/pilot` — Pilot by callsign\n"
        "`!find` `/find_pilot` — Search callsign or CID\n"
        "`!atc` `/atc` — ATC at a facility\n"
        "`!atis` `/atis` — ATIS\n"
        "`!traffic` `/traffic` — Departures & arrivals"
    ), inline=False)
    e.add_field(name="🗺️ Route Generator", value=(
        "`!route <aircraft> <time> [origin]`\n"
        "`/route <aircraft> <time> [origin]`\n"
        "Examples: `!route B738 2h` · `!route A320 90m EGLL`\n"
        "Shows real-world airline flights on the route + SimBrief link."
    ), inline=False)
    return e

@bot.tree.command(name="help", description="Show all commands")
async def slash_help(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_help_embed())

@bot.command(name="help")
async def prefix_help(ctx):
    await ctx.send(embed=_help_embed())


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌  DISCORD_TOKEN not set.")
        exit(1)
    bot.run(DISCORD_TOKEN)
