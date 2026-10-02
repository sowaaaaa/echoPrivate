import asyncio
import logging
from typing import Any, Dict, Optional
import aiohttp

logger = logging.getLogger("shared.geo")

_IP_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_MAX_SIZE = 10000


def get_country_flag(country_code: Optional[str]) -> str:
    """Converts 2-letter ISO country code into emoji flag."""
    if not country_code or len(country_code) != 2:
        return "🌐"
    try:
        return "".join(chr(127397 + ord(c.upper())) for c in country_code)
    except Exception:
        return "🌐"


def get_client_ip(request: Any) -> str:
    """Extracts client real public IP address from aiohttp Request headers."""
    headers = getattr(request, "headers", {})
    # 1. Check X-Forwarded-For (Vercel / Cloudflare / Reverse Proxy)
    x_forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if x_forwarded:
        parts = [p.strip() for p in x_forwarded.split(",") if p.strip()]
        for p in parts:
            # Skip common local proxy addresses if possible
            if not p.startswith(("127.", "10.", "192.168.", "172.16.")):
                return p
        if parts:
            return parts[0]

    # 2. Check X-Real-IP
    x_real = headers.get("x-real-ip") or headers.get("X-Real-IP")
    if x_real and x_real.strip():
        return x_real.strip()

    # 3. Check CF-Connecting-IP
    cf_ip = headers.get("cf-connecting-ip") or headers.get("CF-Connecting-IP")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()

    # 4. Fallback to request.remote
    remote = getattr(request, "remote", None)
    if remote:
        return str(remote).strip()

    return "—"


def _clean_isp_name(isp: Optional[str], org: Optional[str], as_name: Optional[str]) -> str:
    """Formats a concise, recognizable provider/operator name."""
    candidates = [c for c in (isp, org, as_name) if c and c.strip()]
    if not candidates:
        return ""

    raw = " / ".join(candidates)
    raw_lower = raw.lower()

    # Common Ukrainian providers
    if "kyivstar" in raw_lower:
        return "Kyivstar"
    if "vodafone" in raw_lower or "vf ukraine" in raw_lower:
        return "Vodafone"
    if "lifecell" in raw_lower or "astelit" in raw_lower:
        return "Lifecell"
    if "ukrtelecom" in raw_lower:
        return "Ukrtelecom"
    if "triolan" in raw_lower:
        return "Triolan"
    if "volia" in raw_lower:
        return "Volia"
    if "lanet" in raw_lower:
        return "Lanet"

    # Common Russian providers
    if "rostelecom" in raw_lower or "ростелеком" in raw_lower:
        return "Ростелеком"
    if "mts" in raw_lower or "мтс" in raw_lower:
        return "МТС"
    if "megafon" in raw_lower or "мегафон" in raw_lower:
        return "МегаФон"
    if "beeline" in raw_lower or "vimpelcom" in raw_lower or "билайн" in raw_lower:
        return "Билайн"
    if "tele2" in raw_lower or "t2" in raw_lower:
        return "Tele2 / T2"
    if "yota" in raw_lower:
        return "Yota"
    if "dom.ru" in raw_lower or "er-telecom" in raw_lower:
        return "Дом.ру"

    # Common Kazakh providers
    if "kazakhtelecom" in raw_lower:
        return "Казахтелеком"
    if "kcell" in raw_lower:
        return "Kcell"

    # Return primary ISP cleaned of legal prefixes
    primary = isp or org or candidates[0]
    for prefix in ("PrJSC ", "PJSC ", "JSC ", "LLC ", "CJSC ", "AS", "Telecom ", "Communications "):
        if primary.startswith(prefix):
            primary = primary[len(prefix):]
    return primary.strip()[:30]


async def resolve_ip_info(ip: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Asynchronously resolves IP geolocation and ISP.
    Cached in memory to prevent repeated HTTP lookups.
    """
    if not ip or ip in ("—", "unknown", "127.0.0.1", "::1", "localhost"):
        vercel_country = headers.get("x-vercel-ip-country") if headers else None
        vercel_city = headers.get("x-vercel-ip-city") if headers else None
        flag = get_country_flag(vercel_country)
        return {
            "ip": ip or "—",
            "country": vercel_country or "",
            "country_code": vercel_country or "",
            "city": vercel_city or "",
            "flag": flag,
            "isp": "",
            "display": f"{flag} {vercel_country or ''} {vercel_city or ''}".strip(),
        }

    if ip in _IP_CACHE:
        return _IP_CACHE[ip]

    vercel_country = (headers.get("x-vercel-ip-country") or headers.get("X-Vercel-Ip-Country")) if headers else None
    vercel_city = (headers.get("x-vercel-ip-city") or headers.get("X-Vercel-Ip-City")) if headers else None

    res_data: Dict[str, Any] = {
        "ip": ip,
        "country": vercel_country or "",
        "country_code": vercel_country or "",
        "city": vercel_city or "",
        "flag": get_country_flag(vercel_country),
        "isp": "",
        "display": "",
    }

    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,city,isp,org,as,query"
        timeout = aiohttp.ClientTimeout(total=2.5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "success":
                        country = data.get("country") or vercel_country or ""
                        c_code = data.get("countryCode") or vercel_country or ""
                        city = data.get("city") or vercel_city or ""
                        flag = get_country_flag(c_code)
                        isp_clean = _clean_isp_name(data.get("isp"), data.get("org"), data.get("as"))

                        res_data["country"] = country
                        res_data["country_code"] = c_code
                        res_data["city"] = city
                        res_data["flag"] = flag
                        res_data["isp"] = isp_clean
    except Exception as e:
        logger.debug("IP lookup for %s failed: %s", ip, e)

    # Build display string
    loc_parts = []
    if res_data["flag"]:
        loc_parts.append(res_data["flag"])
    if res_data["country"]:
        loc_parts.append(res_data["country"])
    if res_data["city"]:
        loc_parts.append(res_data["city"])

    loc_str = " ".join(loc_parts).strip()
    if res_data["isp"]:
        res_data["display"] = f"{res_data['isp']} ({loc_str})" if loc_str else res_data["isp"]
    else:
        res_data["display"] = loc_str

    if len(_IP_CACHE) >= _CACHE_MAX_SIZE:
        _IP_CACHE.clear()
    _IP_CACHE[ip] = res_data
    return res_data
