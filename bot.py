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

DISCORD_TOKEN     = os.getenv("DISCORD_TOKEN")

VATSIM_DATA_URL   = "https://data.vatsim.net/v3/vatsim-data.json"
VATSIM_EVENTS_URL = "https://my.vatsim.net/api/v1/events/all"
AWC_METAR_URL     = "https://aviationweather.gov/api/data/metar"
AWC_TAF_URL       = "https://aviationweather.gov/api/data/taf"
AWC_PIREP_URL     = "https://aviationweather.gov/api/data/pirep"
OF_ROUTES_URL     = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
OF_AIRPORTS_URL   = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
OF_AIRLINES_URL   = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"

# Typical aircraft types per route distance band (NM)
# Used to show realistic equipment on suggested routes
ROUTE_AIRCRAFT_TYPES = {
    "short":   (0,    500,  ["B738", "A320", "A319", "E190", "CRJ9", "DH8D", "A21N"]),
    "medium":  (500,  2000, ["B738", "A320", "A321", "B739", "A21N", "B752", "A20N"]),
    "long":    (2000, 4500, ["B788", "B789", "A333", "A332", "B772", "A339", "B77W"]),
    "ultralong":(4500, 99999,["B77W", "A359", "A35K", "B789", "B788", "A388", "B748"]),
}

# Per-airline typical fleet (IATA -> [aircraft types])
AIRLINE_FLEET = {
    "AA": ["B738", "B772", "B77W", "A319", "A320", "A321", "B787"],
    "UA": ["B738", "B739", "B772", "B77W", "B788", "B789", "A319", "A320"],
    "DL": ["B738", "B739", "B752", "B764", "B772", "A319", "A320", "A321"],
    "WN": ["B737", "B738"],
    "BA": ["B772", "B77W", "B788", "B789", "A319", "A320", "A321", "A388"],
    "LH": ["B744", "B748", "A319", "A320", "A321", "A333", "A343", "A346"],
    "AF": ["B772", "A318", "A319", "A320", "A321", "A332", "A333", "A388"],
    "KL": ["B772", "B773", "A330", "B738", "E190"],
    "EK": ["B77W", "A388", "B773", "A359"],
    "QR": ["B772", "B77W", "A320", "A321", "A333", "A359", "A35K", "A388"],
    "SQ": ["B772", "B77W", "B788", "B789", "A359", "A35K", "A388"],
    "QF": ["B738", "B744", "B788", "B789", "A330", "A380"],
    "AC": ["B738", "B788", "B789", "A319", "A320", "A321", "E190"],
    "TK": ["B738", "B772", "B77W", "A319", "A320", "A321", "A333"],
    "FR": ["B738"],
    "U2": ["A319", "A320", "A321"],
}

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

# in-memory route table: (src_iata, dst_iata) -> [airline_iata, ...]
_route_table: dict[tuple, list] = {}
# icao -> (lat, lon, name, iata)
_airport_table: dict[str, tuple] = {}
# iata (3-letter) -> icao (4-letter)
_iata_to_icao: dict[str, str] = {}
# icao (4-letter) -> iata (3-letter)
_icao_to_iata: dict[str, str] = {}
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
    global _route_table, _airport_table, _airline_db, _iata_to_icao, _icao_to_iata
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
            for iata, info in AIRLINE_INFO.items():
                _airline_db[iata] = (info[0], info[1])

        # --- airports ---
        # columns: id, name, city, country, iata, icao, lat, lon, ...
        try:
            async with session.get(OF_AIRPORTS_URL, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    text = await r.text(encoding="utf-8", errors="replace")
                    for row in csv.reader(io.StringIO(text)):
                        if len(row) < 8:
                            continue
                        iata = row[4].strip().upper()
                        icao = row[5].strip().upper()
                        name = row[1].strip().strip('"')
                        try:
                            lat = float(row[6])
                            lon = float(row[7])
                        except ValueError:
                            continue
                        if icao and icao != r"\N" and len(icao) == 4:
                            _airport_table[icao] = (lat, lon, name, iata if iata and iata != r"\N" else "")
                        if (iata and iata != r"\N" and len(iata) == 3
                                and icao and icao != r"\N" and len(icao) == 4):
                            _iata_to_icao[iata] = icao
                            _icao_to_iata[icao] = iata
                    print(f"✅ Airports loaded: {len(_airport_table)}, IATA↔ICAO pairs: {len(_iata_to_icao)}")
        except Exception as e:
            print(f"⚠️  Airport load failed: {e}")

        # --- routes ---
        # routes.dat uses IATA codes for airports (3-letter), not ICAO
        # columns: airline_iata, airline_id, src_iata, src_id, dst_iata, dst_id, codeshare, stops, equip
        try:
            async with session.get(OF_ROUTES_URL, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status == 200:
                    text = await r.text(encoding="utf-8", errors="replace")
                    count = 0
                    for row in csv.reader(io.StringIO(text)):
                        if len(row) < 5:
                            continue
                        airline = row[0].strip().upper()
                        src     = row[2].strip().upper()  # IATA airport code
                        dst     = row[4].strip().upper()  # IATA airport code
                        # routes.dat mixes IATA (3-char) and ICAO (4-char) — normalise to IATA
                        if len(src) == 4:
                            src = _icao_to_iata.get(src, src)
                        if len(dst) == 4:
                            dst = _icao_to_iata.get(dst, dst)
                        if not src or not dst or src == r"\N" or dst == r"\N":
                            continue
                        key = (src, dst)
                        _route_table.setdefault(key, [])
                        if airline and airline != r"\N" and airline not in _route_table[key]:
                            _route_table[key].append(airline)
                        count += 1
                    print(f"✅ Routes loaded: {len(_route_table)} unique pairs from {count} entries")
        except Exception as e:
            print(f"⚠️  Route load failed: {e}")


def get_route_aircraft(dist_nm: float, airlines: list[str]) -> list[str]:
    """Return realistic aircraft types for a given distance and airline list."""
    # Get distance-band types
    for band, (lo, hi, types) in ROUTE_AIRCRAFT_TYPES.items():
        if lo <= dist_nm < hi:
            band_types = types
            break
    else:
        band_types = ["B738", "A320"]

    # If we have airline info, prefer their actual fleet for this distance
    fleet_types = []
    for iata in airlines[:2]:
        fleet = AIRLINE_FLEET.get(iata, [])
        for ac in fleet:
            spd = AIRCRAFT_SPEEDS.get(ac, 450)
            approx_range = spd * 16  # ~16h max
            if dist_nm <= approx_range and ac not in fleet_types:
                fleet_types.append(ac)

    result = fleet_types[:2] if fleet_types else band_types[:2]
    return result
    """Find pilots currently flying this exact route on VATSIM."""
    dep_iata = _icao_to_iata.get(dep, dep[:3] if len(dep) == 4 else dep)
    arr_iata = _icao_to_iata.get(arr, arr[:3] if len(arr) == 4 else arr)
    matches = []
    for p in pilots:
        fp = p.get("flight_plan") or {}
        p_dep = fp.get("departure", "").upper()
        p_arr = fp.get("arrival", "").upper()
        # Match on ICAO or IATA for both dep and arr
        dep_match = p_dep in (dep, dep_iata)
        arr_match = p_arr in (arr, arr_iata)
        if dep_match and arr_match:
            matches.append({
                "callsign": p.get("callsign", "?"),
                "alt":      p.get("altitude", 0),
                "gs":       p.get("groundspeed", 0),
                "aircraft": fp.get("aircraft_faa", fp.get("aircraft", "?")),
            })
    return matches[:3]  # cap at 3 live flights


def get_real_flights(src_icao: str, dst_icao: str) -> list[dict]:
    """Return real-world flights for a route pair using IATA route lookup."""
    # Convert ICAO -> IATA for route table lookup
    src_iata = _icao_to_iata.get(src_icao, src_icao[:3] if len(src_icao) == 4 else src_icao)
    dst_iata = _icao_to_iata.get(dst_icao, dst_icao[:3] if len(dst_icao) == 4 else dst_icao)

    airlines = list(_route_table.get((src_iata, dst_iata), []))
    for a in _route_table.get((dst_iata, src_iata), []):
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

    # Build ATC coverage map — VATSIM callsigns use 3 or 4-letter airport prefixes
    atc_airports, atc_map = set(), {}
    for c in data.get("controllers",[]):
        parts = c.get("callsign","").split("_")
        if len(parts) >= 2:
            prefix = parts[0].upper()
            # If 3-letter, try to resolve to ICAO via our map
            if len(prefix) == 3:
                icao = _iata_to_icao.get(prefix, prefix)
            else:
                icao = prefix
            atc_airports.add(icao)
            atc_map.setdefault(icao,[]).append(c.get("callsign",""))

    if len(atc_airports) < 2:
        return None, "Not enough ATC coverage on VATSIM right now."

    # Use OpenFlights airport coords if available, else fall back to METAR
    airports = {}
    if _airport_table:
        for icao in atc_airports:
            if icao in _airport_table:
                lat, lon, name, _ = _airport_table[icao]
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
                lat, lon, name, _ = _airport_table[origin]
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
    pilots = data.get("pilots", [])
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
            real_flights  = get_real_flights(dep, arr)
            live_flights  = get_live_vatsim_flights(pilots, dep, arr)
            typical_ac    = get_route_aircraft(dist, [f["iata"][:-4] if len(f["iata"]) > 4 else f["iata"] for f in real_flights])
            dep_atc = atc_map.get(dep,[])
            arr_atc = atc_map.get(arr,[])
            score = (
                (2 if dep in atc_airports else 0) +
                (2 if arr in atc_airports else 0) +
                (3 if real_flights else 0) +
                (5 if live_flights else 0)  # prioritise routes with live traffic
            )
            candidates.append({
                "dep": dep, "arr": arr,
                "dep_name": airports[dep].get("name", dep),
                "arr_name": airports[arr].get("name", arr),
                "dist_nm": dist,
                "flight_time_h": dist/speed,
                "dep_atc": dep_atc,
                "arr_atc": arr_atc,
                "real_flights": real_flights,
                "live_flights": live_flights,
                "typical_ac":   typical_ac,
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

        ac_str = " / ".join(r["typical_ac"]) if r["typical_ac"] else ac
        lines = [
            f"**{r['dep']}** → **{r['arr']}** | {r['dist_nm']:.0f} NM | {flt_h}h {flt_m}m",
            f"🛩️ Typical aircraft: {ac_str}",
            f"🎙️ Dep ATC: {dep_atc_str}",
            f"🎙️ Arr ATC: {arr_atc_str}",
        ]

        # Live VATSIM flights on this route right now
        if r["live_flights"]:
            lines.append("🟢 **Flying this route on VATSIM right now:**")
            for lf in r["live_flights"]:
                alt_str = f"FL{int(lf['alt'])//100}" if lf['alt'] else "?"
                lines.append(f"• **{lf['callsign']}** {lf['aircraft']} — {alt_str} @ {lf['gs']}kt")

        # Real-world airline routes with SimBrief links
        if r["real_flights"]:
            lines.append("✈️ **Real-world airlines on this route:**")
            lines.append("*Flight numbers are examples — [look up real numbers on Google](https://www.google.com/search?q=flight+number)*")
            for f in r["real_flights"]:
                icao_code = f["callsign"][:3] if len(f["callsign"]) > 3 else f["callsign"]
                fnum = f["callsign"][3:]
                sb = simbrief_url(r["dep"], r["arr"], ac, icao_code, fnum)
                google_q = f"{f['airline']} {r['dep']} {r['arr']} flight number".replace(" ", "+")
                google = f"https://www.google.com/search?q={google_q}"
                lines.append(f"• {f['airline']} — [SimBrief]({sb}) · [Find real flight #]({google})")
        else:
            sb = simbrief_url(r["dep"], r["arr"], ac)
            lines.append(f"[📋 Plan in SimBrief]({sb})")
            if not r["live_flights"]:
                lines.append("⚠️ No airline route data for this pair")

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
# NOTAMs
# --------------------------------------------------------------------------- #

@bot.tree.command(name="notam", description="Show active NOTAMs for an airport (US airports, requires FAA key)")
async def slash_notam(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    await _send_notams(interaction.followup.send, icao.upper().strip())

@bot.command(name="notam")
async def prefix_notam(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!notam <ICAO>` e.g. `!notam KLAX`")
        return
    await _send_notams(ctx.send, icao.upper().strip())

async def _send_notams(send_fn, icao: str):
    # Determine US vs international by prefix
    us_prefixes = ("K", "P")  # K = contiguous US, P = Pacific/Hawaii/Alaska
    is_us = icao.startswith(us_prefixes)

    if is_us:
        url = f"https://notams.aim.faa.gov/notamSearch/search?searchType=0&searchfacility={icao}"
    else:
        url = f"https://www.notams.faa.gov/dinsQueryWeb/queryRetrievalMapAction.do?reportType=Raw&retrieveLocId={icao}"

    # Also build a SkyVector link which shows NOTAMs on a map
    skyvector = f"https://skyvector.com/airport/{icao}"

    embed = discord.Embed(
        title=f"📋 NOTAMs — {icao}",
        description=f"Click below to view active NOTAMs for **{icao}**.",
        colour=discord.Colour.orange(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="🔗 Official NOTAM Search",
        value=f"[Open FAA NOTAM Search for {icao}]({url})",
        inline=False,
    )
    embed.add_field(
        name="🗺️ SkyVector",
        value=f"[View {icao} on SkyVector (charts + NOTAMs)]({skyvector})",
        inline=False,
    )
    embed.set_footer(text="FAA NOTAM Search — official source, always current")
    await send_fn(embed=embed)


# --------------------------------------------------------------------------- #
# VATSIM Events
# --------------------------------------------------------------------------- #

@bot.tree.command(name="events", description="Show upcoming VATSIM events")
async def slash_events(interaction: discord.Interaction):
    await interaction.response.defer()
    await _send_events(interaction.followup.send)

@bot.command(name="events")
async def prefix_events(ctx):
    await _send_events(ctx.send)

async def _send_events(send_fn):
    data = await fetch_json(VATSIM_EVENTS_URL)
    if not data:
        await send_fn("❌ Could not reach VATSIM Events API.")
        return
    events = data.get("data", [])
    if not events:
        await send_fn("No upcoming VATSIM events found.")
        return

    now = datetime.now(timezone.utc)
    upcoming = []
    for e in events:
        try:
            start = datetime.fromisoformat(e["start_time"].replace("Z", "+00:00"))
            end   = datetime.fromisoformat(e["end_time"].replace("Z", "+00:00"))
            if end > now:
                upcoming.append((start, e))
        except Exception:
            pass
    upcoming.sort(key=lambda x: x[0])

    embed = discord.Embed(title="📅 Upcoming VATSIM Events", colour=discord.Colour.blurple(), timestamp=now)
    for start, e in upcoming[:8]:
        name     = e.get("name", "Unnamed Event")
        link     = e.get("link", "")
        airports = [a.get("icao","") for a in e.get("airports", [])]
        routes   = e.get("routes", [])
        start_str = start.strftime("%b %d %H:%MZ")
        try:
            end_dt  = datetime.fromisoformat(e["end_time"].replace("Z", "+00:00"))
            end_str = end_dt.strftime("%b %d %H:%MZ")
        except Exception:
            end_str = "?"

        is_live = start <= now
        status  = "🟢 **LIVE NOW**" if is_live else f"🕐 {start_str} → {end_str}"
        val_parts = [status]
        if airports:
            val_parts.append(f"✈️ {', '.join(airports[:5])}")
        if routes:
            r0 = routes[0]
            val_parts.append(f"🗺️ {r0.get('departure','?')} → {r0.get('arrival','?')}")
        if link:
            val_parts.append(f"[More info]({link})")
        embed.add_field(name=name, value="\n".join(val_parts), inline=False)

    embed.set_footer(text="Source: my.vatsim.net")
    await send_fn(embed=embed)


# --------------------------------------------------------------------------- #
# PIREPs
# --------------------------------------------------------------------------- #

@bot.tree.command(name="pirep", description="Show recent PIREPs near an airport")
async def slash_pirep(interaction: discord.Interaction, icao: str):
    await interaction.response.defer()
    await _send_pireps(interaction.followup.send, icao.upper().strip())

@bot.command(name="pirep")
async def prefix_pirep(ctx, icao: str = None):
    if not icao:
        await ctx.send("Usage: `!pirep <ICAO>` e.g. `!pirep KLAX`")
        return
    await _send_pireps(ctx.send, icao.upper().strip())

async def _send_pireps(send_fn, icao: str):
    data = await fetch_json(AWC_PIREP_URL, {"id": icao, "format": "json", "age": 2, "distance": 100})
    if not data or not isinstance(data, list) or not data:
        await send_fn(f"No PIREPs found near **{icao}** in the last 2 hours.")
        return
    embed = discord.Embed(title=f"🛩️ PIREPs near {icao}", colour=discord.Colour.teal(), timestamp=datetime.now(timezone.utc))
    for p in data[:8]:
        raw      = p.get("rawOb", p.get("raw", "N/A"))
        obs_time = p.get("obsTime", "")
        ac_type  = p.get("acType", "")
        altitude = p.get("altitude", "")
        turb     = p.get("turbulenceCondition", "")
        ice      = p.get("icingCondition", "")
        sky      = p.get("skyCond", "")
        wx       = p.get("wxString", "")
        try:
            obs_dt = datetime.fromtimestamp(int(obs_time), tz=timezone.utc).strftime("%H:%MZ")
        except Exception:
            obs_dt = "?"
        parts = []
        if ac_type:  parts.append(f"**Aircraft:** {ac_type}")
        if altitude: parts.append(f"**Alt:** FL{str(altitude).zfill(3)}")
        if turb:     parts.append(f"**Turbulence:** {turb}")
        if ice:      parts.append(f"**Icing:** {ice}")
        if sky:      parts.append(f"**Sky:** {sky}")
        if wx:       parts.append(f"**WX:** {wx}")
        parts.append(f"```{raw[:200]}```")
        embed.add_field(name=f"PIREP @ {obs_dt}", value="\n".join(parts), inline=False)
    embed.set_footer(text="aviationweather.gov — within 100NM, last 2hrs")
    await send_fn(embed=embed)


# --------------------------------------------------------------------------- #
# Help
# --------------------------------------------------------------------------- #

def _help_embed() -> discord.Embed:
    e = discord.Embed(title="✈️ Aviation Bot — Commands", description="Works with both `!prefix` and `/slash` commands.", colour=discord.Colour.gold())
    e.add_field(name="🌤️ Weather", value=(
        "`!metar` `/metar` — METAR\n"
        "`!taf` `/taf` — TAF\n"
        "`!wx` `/wx` — METAR + TAF\n"
        "`!pirep` `/pirep` — PIREPs near airport"
    ), inline=False)
    e.add_field(name="🛩️ VATSIM", value=(
        "`!vatsim` `/vatsim_stats` — Network totals\n"
        "`!pilot` `/pilot` — Pilot by callsign\n"
        "`!find` `/find_pilot` — Search callsign or CID\n"
        "`!atc` `/atc` — ATC at a facility\n"
        "`!atis` `/atis` — ATIS\n"
        "`!traffic` `/traffic` — Departures & arrivals\n"
        "`!events` `/events` — Upcoming VATSIM events"
    ), inline=False)
    e.add_field(name="🗺️ Route Generator", value=(
        "`!route <aircraft> <time> [origin]`\n"
        "Examples: `!route B738 2h` · `!route A320 90m EGLL`\n"
        "Shows typical aircraft, live VATSIM traffic, real airlines + SimBrief."
    ), inline=False)
    e.add_field(name="📋 NOTAMs", value=(
        "`!notam` `/notam` — Active NOTAMs for an airport\n"
        "Requires free FAA API key (US airports only)."
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
