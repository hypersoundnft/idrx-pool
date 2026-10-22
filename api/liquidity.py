from http.server import BaseHTTPRequestHandler
import json
from datetime import datetime, timezone
from collections import defaultdict
from urllib.request import urlopen, Request
from urllib.error import URLError

STABLECOINS = {
    "USDC", "USDT", "USDT0", "frxUSD", "DAI", "USDS", "USDM",
    "FRAX", "crvUSD", "sUSD", "USDbC", "USDC.E", "PYUSD",
    "FDUSD", "USDD", "TUSD", "GUSD", "LUSD", "MIM", "alUSD",
    "USDP", "BUSD", "USDJ", "USDK", "USX", "USD+", "USR",
    "USDY", "USDz", "USDe", "sUSDe", "USDS", "USD0", "USD0++",
    "USD₮", "USD₮0",
}

GECKO_NETWORKS = ["kaia"]
GECKO_TOKENS = {"celo": "0x18bc5bcc660cf2b9ce3cd51a404afe1a0cbd3c22"}
DEX_MAP = {"kaia": "dgswap", "celo": "celodex"}

def is_stablecoin(symbol):
    return symbol.upper().strip() in STABLECOINS or "USD" in symbol.upper()

def is_idrx_pair(p):
    """Check if pair involves IDRX and a stablecoin in either direction."""
    base = p["baseToken"]
    quote = p["quoteToken"]
    base_is_idrx = base.upper() == "IDRX"
    quote_is_idrx = quote.upper() == "IDRX"
    base_is_stable = is_stablecoin(base)
    quote_is_stable = is_stablecoin(quote)
    return (base_is_idrx and quote_is_stable) or (quote_is_idrx and base_is_stable)

def safe_get(d, *keys, default=0):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, {})
        else:
            return default
    return d if d != {} else default

def fetch_dexscreener():
    url = "https://api.dexscreener.com/latest/dex/search/?q=IDRX"
    req = Request(url, headers={"User-Agent": "IDRX-Liquidity-Tracker/1.0"})
    with urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode()).get("pairs", [])

def fetch_gecko(network):
    url = f"https://api.geckoterminal.com/api/v2/search/pools?query=IDRX&network={network}"
    req = Request(url, headers={"User-Agent": "IDRX-Liquidity-Tracker/1.0"})
    with urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode()).get("data", [])

def fetch_gecko_token_pools(network, token_address):
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/tokens/{token_address}/pools"
    req = Request(url, headers={"User-Agent": "IDRX-Liquidity-Tracker/1.0"})
    with urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode()).get("data", [])

def process_dex_pairs(pairs):
    results = []
    for p in pairs:
        liq = p.get("liquidity", {}) or {}
        vol = p.get("volume", {}) or {}
        txn = p.get("txns", {}) or {}
        pc = p.get("priceChange", {}) or {}
        results.append({
            "chain": p.get("chainId", "unknown"),
            "dex": p.get("dexId", "unknown"),
            "pairAddress": p.get("pairAddress", ""),
            "url": p.get("url", ""),
            "baseToken": p.get("baseToken", {}).get("symbol", "?"),
            "quoteToken": p.get("quoteToken", {}).get("symbol", "?"),
            "baseTokenName": p.get("baseToken", {}).get("name", ""),
            "quoteTokenName": p.get("quoteToken", {}).get("name", ""),
            "labels": p.get("labels", []),
            "priceUsd": float(p.get("priceUsd", 0) or 0),
            "priceNative": float(p.get("priceNative", 0) or 0),
            "liquidityUsd": float(liq.get("usd", 0) or 0),
            "liquidityBase": float(liq.get("base", 0) or 0),
            "liquidityQuote": float(liq.get("quote", 0) or 0),
            "volume24h": float(vol.get("h24", 0) or 0),
            "volume6h": float(vol.get("h6", 0) or 0),
            "volume1h": float(vol.get("h1", 0) or 0),
            "txns24h_buys": int(safe_get(txn, "h24", "buys")),
            "txns24h_sells": int(safe_get(txn, "h24", "sells")),
            "priceChange1h": float(pc.get("h1", 0) or 0),
            "priceChange6h": float(pc.get("h6", 0) or 0),
            "priceChange24h": float(pc.get("h24", 0) or 0),
            "fdv": float(p.get("fdv", 0) or 0),
            "pairCreatedAt": p.get("pairCreatedAt"),
        })
    return results

def process_gecko_pool(pool, network):
    a = pool.get("attributes", {})
    vol = a.get("volume_usd", {}) or {}
    txn = a.get("transactions", {}) or {}
    pc = a.get("price_change_percentage", {}) or {}
    name = a.get("pool_name", a.get("name", "IDRX / USD₮"))
    parts = name.split("/")
    base_symbol = parts[0].strip() if parts else "IDRX"
    quote_part = parts[1].strip() if len(parts) > 1 else "USD₮"
    quote_symbol = quote_part.split()[0] if quote_part else "USD₮"
    fee_pct = ""
    remaining = quote_part[len(quote_symbol):].strip()
    if remaining:
        fee_pct = remaining.rstrip("%") + "%"
    dex_id = pool.get("relationships", {}).get("dex", {}).get("data", {}).get("id")
    return {
        "chain": network,
        "dex": dex_id or DEX_MAP.get(network, network),
        "pairAddress": a.get("address", ""),
        "url": f"https://www.geckoterminal.com/{network}/pools/{a.get('address', '')}",
        "baseToken": base_symbol,
        "quoteToken": quote_symbol,
        "baseTokenName": base_symbol,
        "quoteTokenName": quote_symbol,
        "labels": [fee_pct] if fee_pct else [],
        "priceUsd": float(a.get("base_token_price_usd", 0) or 0),
        "priceNative": float(a.get("base_token_price_native_currency", 0) or 0),
        "liquidityUsd": float(a.get("reserve_in_usd", 0) or 0),
        "liquidityBase": 0,
        "liquidityQuote": 0,
        "volume24h": float(vol.get("h24", 0) or 0),
        "volume6h": float(vol.get("h6", 0) or 0),
        "volume1h": float(vol.get("h1", 0) or 0),
        "txns24h_buys": int(float(txn.get("h24", {}).get("buys", 0) or 0)),
        "txns24h_sells": int(float(txn.get("h24", {}).get("sells", 0) or 0)),
        "priceChange1h": float(pc.get("h1", 0) or 0),
        "priceChange6h": float(pc.get("h6", 0) or 0),
        "priceChange24h": float(pc.get("h24", 0) or 0),
        "fdv": float(a.get("fdv_usd", 0) or 0),
        "pairCreatedAt": a.get("pool_created_at"),
    }

def fetch_gecko_ohlcv(network, address):
    """Fetch daily OHLCV for a GeckoTerminal pool to compute 7d/30d/3m volume."""
    url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools/{address}/ohlcv/day"
    req = Request(url, headers={"User-Agent": "IDRX-Liquidity-Tracker/1.0"})
    try:
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            ohlcv = data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
            vol_7d = sum(float(o[5]) for o in ohlcv[-7:]) if len(ohlcv) >= 7 else 0
            vol_30d = sum(float(o[5]) for o in ohlcv[-30:]) if len(ohlcv) >= 30 else 0
            vol_3m = sum(float(o[5]) for o in ohlcv[-90:]) if len(ohlcv) >= 90 else 0
            return (round(vol_7d, 2), round(vol_30d, 2), round(vol_3m, 2))
    except Exception:
        return (0, 0, 0)

def aggregate_by_chain(pairs):
    chains = defaultdict(lambda: {"chain": "", "totalLiquidity": 0, "totalVolume24h": 0, "totalVolume7d": 0, "totalVolume30d": 0, "totalVolume3m": 0, "poolCount": 0, "dexs": set()})
    for p in pairs:
        c = chains[p["chain"]]
        c["chain"] = p["chain"]
        c["totalLiquidity"] += p["liquidityUsd"]
        c["totalVolume24h"] += p["volume24h"]
        c["totalVolume7d"] += p.get("volume7d", p["volume24h"] * 7)
        c["totalVolume30d"] += p.get("volume30d", p["volume24h"] * 30)
        c["totalVolume3m"] += p.get("volume3m", p["volume24h"] * 90)
        c["poolCount"] += 1
        c["dexs"].add(p["dex"])
    return [{
        "chain": c["chain"], "totalLiquidity": round(c["totalLiquidity"], 2),
        "totalVolume24h": round(c["totalVolume24h"], 2),
        "totalVolume7d": round(c["totalVolume7d"], 2),
        "totalVolume30d": round(c["totalVolume30d"], 2),
        "totalVolume3m": round(c["totalVolume3m"], 2),
        "poolCount": c["poolCount"],
        "dexs": sorted(c["dexs"]),
    } for c in sorted(chains.values(), key=lambda x: -x["totalLiquidity"])]

def get_data():
    enriched = process_dex_pairs(fetch_dexscreener())
    for network in GECKO_NETWORKS:
        for pool in fetch_gecko(network):
            p = process_gecko_pool(pool, network)
            # Enrich with OHLCV-based volumes for longer timeframes
            addr = p["pairAddress"]
            v7, v30, v90 = fetch_gecko_ohlcv(network, addr)
            if v7 > 0:
                p["volume7d"] = v7
                p["volume30d"] = v30
                p["volume3m"] = v90
            enriched.append(p)
    for network, token_address in GECKO_TOKENS.items():
        for pool in fetch_gecko_token_pools(network, token_address):
            p = process_gecko_pool(pool, network)
            addr = p["pairAddress"]
            v7, v30, v90 = fetch_gecko_ohlcv(network, addr)
            if v7 > 0:
                p["volume7d"] = v7
                p["volume30d"] = v30
                p["volume3m"] = v90
            enriched.append(p)
    stable = [p for p in enriched if is_idrx_pair(p)]
    significant = [p for p in stable if p["liquidityUsd"] >= 1]
    chains = aggregate_by_chain(stable)
    return {
        "meta": {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "totalPairs": len(stable),
            "significantPairs": len(significant),
        },
        "totals": {
            "totalLiquidity": round(sum(p["liquidityUsd"] for p in stable), 2),
            "totalVolume24h": round(sum(p["volume24h"] for p in stable), 2),
            "totalVolume7d": round(sum(p.get("volume7d", p["volume24h"] * 7) for p in stable), 2),
            "totalVolume30d": round(sum(p.get("volume30d", p["volume24h"] * 30) for p in stable), 2),
            "totalVolume3m": round(sum(p.get("volume3m", p["volume24h"] * 90) for p in stable), 2),
            "chainCount": len(chains),
        },
        "chains": chains,
        "pools": sorted(stable, key=lambda p: -p["liquidityUsd"]),
    }

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            data = get_data()
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "public, max-age=120, s-maxage=120")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            err = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err)))
            self.end_headers()
            self.wfile.write(err)
