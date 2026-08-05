from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import duckdb
except ImportError:  # Synthetic tests do not require DuckDB.
    duckdb = None


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", "" if value is None else str(value).lower())


def _space(value: Any) -> str:
    return re.sub(r"\s+", " ", "" if value is None else str(value)).strip()


@dataclass(frozen=True)
class Meta:
    symbol: str
    exchange: str
    country: str
    region: str
    currency: str
    aliases: tuple[str, ...] = ()


# Broad public mapping of major world-index symbols. Runtime data can use symbols
# with or without Yahoo's leading caret; matching is punctuation-insensitive.
_META: tuple[Meta, ...] = (
    Meta("^GSPC", "New York Stock Exchange", "United States", "North America", "USD", ("S&P 500", "SP500")),
    Meta("^DJI", "New York Stock Exchange", "United States", "North America", "USD", ("Dow Jones", "DJIA")),
    Meta("^IXIC", "NASDAQ", "United States", "North America", "USD", ("NASDAQ Composite",)),
    Meta("^RUT", "NASDAQ", "United States", "North America", "USD", ("Russell 2000",)),
    Meta("^VIX", "Chicago Board Options Exchange", "United States", "North America", "USD", ("CBOE Volatility Index",)),
    Meta("^GSPTSE", "Toronto Stock Exchange", "Canada", "North America", "CAD", ("S&P/TSX", "TSX")),
    Meta("^MXX", "Mexican Stock Exchange", "Mexico", "North America", "MXN", ("IPC Mexico",)),
    Meta("^BVSP", "B3 São Paulo Stock Exchange", "Brazil", "South America", "BRL", ("Bovespa", "Ibovespa")),
    Meta("^MERV", "Buenos Aires Stock Exchange", "Argentina", "South America", "ARS", ("MERVAL",)),
    Meta("^IPSA", "Santiago Stock Exchange", "Chile", "South America", "CLP", ("IPSA Chile",)),
    Meta("^FTSE", "London Stock Exchange", "United Kingdom", "Europe", "GBP", ("FTSE 100",)),
    Meta("^GDAXI", "Frankfurt Stock Exchange", "Germany", "Europe", "EUR", ("DAX", "DAX 40")),
    Meta("^FCHI", "Euronext Paris", "France", "Europe", "EUR", ("CAC 40",)),
    Meta("^STOXX50E", "Eurex", "Eurozone", "Europe", "EUR", ("Euro Stoxx 50",)),
    Meta("^N100", "Euronext", "Europe", "Europe", "EUR", ("Euronext 100",)),
    Meta("^BFX", "Euronext Brussels", "Belgium", "Europe", "EUR", ("BEL 20",)),
    Meta("^IBEX", "Madrid Stock Exchange", "Spain", "Europe", "EUR", ("IBEX 35",)),
    Meta("^AEX", "Euronext Amsterdam", "Netherlands", "Europe", "EUR", ("AEX",)),
    Meta("^SSMI", "SIX Swiss Exchange", "Switzerland", "Europe", "CHF", ("SMI",)),
    Meta("^ATX", "Vienna Stock Exchange", "Austria", "Europe", "EUR", ("ATX",)),
    Meta("^OMX", "Stockholm Stock Exchange", "Sweden", "Europe", "SEK", ("OMX Stockholm",)),
    Meta("^OMXH25", "Helsinki Stock Exchange", "Finland", "Europe", "EUR", ("OMX Helsinki 25",)),
    Meta("^OSEAX", "Oslo Stock Exchange", "Norway", "Europe", "NOK", ("Oslo All Share",)),
    Meta("^N225", "Tokyo Stock Exchange", "Japan", "Asia", "JPY", ("Nikkei 225", "Nikkei")),
    Meta("^TOPX", "Tokyo Stock Exchange", "Japan", "Asia", "JPY", ("TOPIX",)),
    Meta("^HSI", "Hong Kong Stock Exchange", "Hong Kong", "Asia", "HKD", ("Hang Seng",)),
    Meta("000001.SS", "Shanghai Stock Exchange", "China", "Asia", "CNY", ("Shanghai Composite", "SSEC")),
    Meta("399001.SZ", "Shenzhen Stock Exchange", "China", "Asia", "CNY", ("Shenzhen Component", "SZSE")),
    Meta("^KS11", "Korea Exchange", "South Korea", "Asia", "KRW", ("KOSPI",)),
    Meta("^KQ11", "Korea Exchange", "South Korea", "Asia", "KRW", ("KOSDAQ",)),
    Meta("^TWII", "Taiwan Stock Exchange", "Taiwan", "Asia", "TWD", ("Taiwan Weighted",)),
    Meta("^STI", "Singapore Exchange", "Singapore", "Asia", "SGD", ("Straits Times",)),
    Meta("^BSESN", "Bombay Stock Exchange", "India", "Asia", "INR", ("SENSEX",)),
    Meta("^NSEI", "National Stock Exchange of India", "India", "Asia", "INR", ("NIFTY 50", "NIFTY")),
    Meta("^JKSE", "Indonesia Stock Exchange", "Indonesia", "Asia", "IDR", ("Jakarta Composite",)),
    Meta("^KLSE", "Bursa Malaysia", "Malaysia", "Asia", "MYR", ("FTSE Bursa Malaysia KLCI", "KLCI")),
    Meta("^PSEI", "Philippine Stock Exchange", "Philippines", "Asia", "PHP", ("PSEi",)),
    Meta("^SET.BK", "Stock Exchange of Thailand", "Thailand", "Asia", "THB", ("SET Index",)),
    Meta("^TA125.TA", "Tel Aviv Stock Exchange", "Israel", "Asia", "ILS", ("TA-125",)),
    Meta("^AXJO", "Australian Securities Exchange", "Australia", "Oceania", "AUD", ("S&P/ASX 200", "ASX 200")),
    Meta("^NZ50", "New Zealand Exchange", "New Zealand", "Oceania", "NZD", ("S&P/NZX 50", "NZX 50")),
    Meta("^JN0U.JO", "Johannesburg Stock Exchange", "South Africa", "Africa", "ZAR", ("JSE All Share",)),
    Meta("^CASE30", "Egyptian Exchange", "Egypt", "Africa", "EGP", ("EGX 30",)),
)

_META_BY_KEY: dict[str, Meta] = {}
for _meta in _META:
    for _alias in (_meta.symbol, _meta.exchange, _meta.country, _meta.currency, *_meta.aliases):
        _META_BY_KEY.setdefault(_key(_alias), _meta)

REGION_ALIASES = {
    "asia": "Asia",
    "asian": "Asia",
    "europe": "Europe",
    "european": "Europe",
    "northamerica": "North America",
    "northamerican": "North America",
    "southamerica": "South America",
    "southamerican": "South America",
    "latinamerica": "South America",
    "oceania": "Oceania",
    "africa": "Africa",
    "african": "Africa",
}
CURRENCY_NAMES = {
    "usd": "USD", "dollar": "USD", "dollars": "USD", "us dollar": "USD",
    "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "sterling": "GBP",
    "jpy": "JPY", "yen": "JPY",
    "cny": "CNY", "yuan": "CNY", "renminbi": "CNY", "rmb": "CNY",
    "hkd": "HKD", "hong kong dollar": "HKD",
    "krw": "KRW", "won": "KRW",
    "twd": "TWD", "taiwan dollar": "TWD",
    "inr": "INR", "rupee": "INR", "rupees": "INR",
    "aud": "AUD", "australian dollar": "AUD",
    "cad": "CAD", "canadian dollar": "CAD",
    "chf": "CHF", "swiss franc": "CHF",
    "brl": "BRL", "real": "BRL",
    "mxn": "MXN", "peso": "MXN", "pesos": "MXN",
    "sgd": "SGD", "singapore dollar": "SGD",
    "thb": "THB", "baht": "THB",
    "myr": "MYR", "ringgit": "MYR",
    "php": "PHP", "philippine peso": "PHP",
    "idr": "IDR", "rupiah": "IDR",
    "sek": "SEK", "swedish krona": "SEK",
    "nok": "NOK", "norwegian krone": "NOK",
    "nzd": "NZD", "new zealand dollar": "NZD",
}


@dataclass
class Plan:
    metric: str = "intraday_volatility"
    reduction: str = "mean"
    group_by: str = "index"
    direction: str | None = "max"
    start_date: str | None = None
    end_date: str | None = None
    region: str | None = None
    country: str | None = None
    currency: str | None = None
    exchange: str | None = None
    symbols: list[str] = field(default_factory=list)
    top_k: int = 1
    distinct_indices: bool = False
    include_value: bool = False


def _extract_year_window(text: str) -> tuple[str | None, str | None]:
    # Explicit date ranges first.
    match = re.search(r"\b(?:between|from)\s+(20\d{2})\s+(?:and|to|through|-)\s+(20\d{2})\b", text)
    if match:
        start, end = sorted((int(match.group(1)), int(match.group(2))))
        return f"{start:04d}-01-01", f"{end:04d}-12-31"
    match = re.search(r"\b(?:during|in|for)\s+(20\d{2})\b", text)
    if match and not re.search(r"\b(?:since|after|before|until|through)\s+" + re.escape(match.group(1)), text):
        year = int(match.group(1))
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    start = None
    end = None
    match = re.search(r"\b(?:since|from|starting(?:\s+in)?|on or after)\s+(20\d{2})\b", text)
    if match:
        start = f"{int(match.group(1)):04d}-01-01"
    match = re.search(r"\bafter\s+(20\d{2})\b", text)
    if match:
        start = f"{int(match.group(1)) + 1:04d}-01-01"
    match = re.search(r"\b(?:before|through|until|up to)\s+(20\d{2})\b", text)
    if match:
        year = int(match.group(1))
        if "before" in match.group(0):
            year -= 1
        end = f"{year:04d}-12-31"
    return start, end


def _find_metadata_filter(text: str) -> tuple[str | None, str | None, str | None, str | None, list[str]]:
    compact = _key(text)
    region = next((canonical for alias, canonical in REGION_ALIASES.items() if alias in compact), None)

    currency = None
    # Treat currencies as filters only when the query explicitly refers to the
    # trading/denomination currency. Phrases such as "closing price in USD"
    # describe the metric unit (CloseUSD), not a currency filter.
    for alias, canonical in sorted(CURRENCY_NAMES.items(), key=lambda item: -len(item[0])):
        patterns = (
            rf"\btraded\s+in\s+{re.escape(alias)}\b",
            rf"\bdenominated\s+in\s+{re.escape(alias)}\b",
            rf"\busing\s+{re.escape(alias)}\b",
            rf"\b{re.escape(alias)}[-\s]+denominated\b",
            rf"\bcurrency\s+(?:is|of)\s+{re.escape(alias)}\b",
        )
        if any(re.search(pattern, text) for pattern in patterns):
            currency = canonical
            break

    country = None
    exchange = None
    symbols: list[str] = []
    for meta in _META:
        if any(re.search(rf"\b{re.escape(alias.lower())}\b", text) for alias in (meta.country, meta.exchange, *meta.aliases) if len(alias) > 2):
            if meta.country.lower() in text:
                country = meta.country
            if meta.exchange.lower() in text:
                exchange = meta.exchange
            if any(alias.lower() in text for alias in (meta.symbol, *meta.aliases)):
                symbols.append(meta.symbol)
        # Symbols with punctuation are easier to compare after normalization.
        if _key(meta.symbol) in compact and len(_key(meta.symbol)) >= 3:
            symbols.append(meta.symbol)

    # Country adjectives and common short names.
    adjective_map = {
        "japanese": "Japan", "japan": "Japan", "chinese": "China", "china": "China",
        "indian": "India", "india": "India", "american": "United States", "united states": "United States",
        "canadian": "Canada", "canada": "Canada", "british": "United Kingdom", "united kingdom": "United Kingdom",
        "german": "Germany", "germany": "Germany", "french": "France", "france": "France",
        "australian": "Australia", "australia": "Australia", "brazilian": "Brazil", "brazil": "Brazil",
        "korean": "South Korea", "south korea": "South Korea", "taiwanese": "Taiwan", "taiwan": "Taiwan",
        "singaporean": "Singapore", "singapore": "Singapore", "mexican": "Mexico", "mexico": "Mexico",
    }
    for alias, canonical in adjective_map.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            country = canonical
            break
    return region, country, currency, exchange, sorted(set(symbols))


def plan_query(query: str) -> Plan:
    text = _space(query).lower()
    start_date, end_date = _extract_year_window(text)
    region, country, currency, exchange, symbols = _find_metadata_filter(text)

    # Metric semantics.
    if "intraday" in text and any(word in text for word in ("volatility", "fluctuation", "range")):
        metric, reduction = "intraday_volatility", "mean"
    elif any(phrase in text for phrase in ("up-to-down ratio", "up to down ratio", "ratio of up days to down days")):
        metric, reduction = "up_down_ratio", "ratio"
    elif any(phrase in text for phrase in ("difference between up days and down days", "more up days than down days", "net up days")):
        metric, reduction = "up_minus_down", "difference"
    elif any(phrase in text for phrase in ("percentage of up days", "proportion of up days", "share of up days", "up-day rate", "up day rate")):
        metric, reduction = "up_ratio", "ratio"
    elif any(phrase in text for phrase in ("percentage of down days", "proportion of down days", "share of down days", "down-day rate", "down day rate")):
        metric, reduction = "down_ratio", "ratio"
    elif re.search(r"\bup days?\b", text) or "closed higher than" in text:
        metric, reduction = "up_days", "count"
    elif re.search(r"\bdown days?\b", text) or "closed lower than" in text:
        metric, reduction = "down_days", "count"
    elif any(phrase in text for phrase in ("cumulative return", "total return", "overall return", "price growth")):
        metric, reduction = "cumulative_return", "compound"
    elif any(phrase in text for phrase in ("average daily return", "mean daily return", "average return")):
        metric, reduction = "daily_return", "mean"
    elif "maximum drawdown" in text or "max drawdown" in text:
        metric, reduction = "max_drawdown", "min"
    elif "volatility" in text or "standard deviation" in text:
        metric, reduction = "return_volatility", "std"
    elif "closeusd" in _key(text) or "closing price in usd" in text or "usd closing price" in text:
        metric, reduction = "close_usd", "mean"
    elif "adjusted close" in text or "adjusted closing" in text:
        metric, reduction = "adj_close", "mean"
    elif "closing price" in text or "average close" in text or "mean close" in text:
        metric, reduction = "close", "mean"
    elif "opening price" in text or "average open" in text or "mean open" in text:
        metric, reduction = "open", "mean"
    elif "highest daily high" in text or "maximum high" in text:
        metric, reduction = "high", "max"
    elif "lowest daily low" in text or "minimum low" in text:
        metric, reduction = "low", "min"
    elif any(phrase in text for phrase in ("number of trading days", "count of trading days", "trading days")):
        metric, reduction = "trading_days", "count"
    else:
        metric, reduction = "intraday_volatility", "mean"

    # A metric may request a non-default reduction.
    if any(word in text for word in ("average", "mean")) and metric in {"open", "high", "low", "close", "adj_close", "close_usd"}:
        reduction = "mean"
    elif any(word in text for word in ("median",)):
        reduction = "median"
    elif any(word in text for word in ("total", "sum")) and metric in {"open", "high", "low", "close", "adj_close", "close_usd"}:
        reduction = "sum"

    # Grouping target.
    if re.search(r"\bwhich currency\b|\bwhat currency\b", text):
        group_by = "currency"
    elif re.search(r"\bwhich (?:stock )?exchange\b|\bwhat (?:stock )?exchange\b", text):
        group_by = "exchange"
    elif re.search(r"\bwhich country\b|\bwhat country\b", text):
        group_by = "country"
    elif re.search(r"\bwhich region\b|\bwhat region\b", text):
        group_by = "region"
    else:
        group_by = "index"

    # Direction and top-k.
    if any(phrase in text for phrase in ("lowest", "least", "smallest", "minimum", "fewest", "worst")):
        direction = "min"
    elif any(phrase in text for phrase in ("highest", "most", "largest", "maximum", "greatest", "best")):
        direction = "max"
    else:
        direction = None if (symbols or "how many" in text or "what is" in text or "calculate" in text) else "max"

    top_k = 1
    match = re.search(r"\btop\s+(\d+)\b", text)
    if match:
        top_k = max(1, int(match.group(1)))
    elif "top three" in text:
        top_k = 3
    elif "top five" in text:
        top_k = 5

    distinct_indices = bool(re.search(r"\bhow many (?:distinct |different )?(?:stock )?indices\b", text))
    include_value = any(word in text for word in ("value", "rate", "ratio", "percentage", "average", "count", "number", "how many"))

    return Plan(
        metric=metric,
        reduction=reduction,
        group_by=group_by,
        direction=direction,
        start_date=start_date,
        end_date=end_date,
        region=region,
        country=country,
        currency=currency,
        exchange=exchange,
        symbols=symbols,
        top_k=top_k,
        distinct_indices=distinct_indices,
        include_value=include_value,
    )


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    text = _space(value)
    for candidate in (text[:10], text):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def metadata_for(symbol: str) -> Meta:
    key = _key(symbol)
    if key in _META_BY_KEY:
        return _META_BY_KEY[key]
    # Strip common Yahoo prefixes/suffix punctuation.
    for meta in _META:
        if key == _key(meta.symbol):
            return meta
    return Meta(symbol=_space(symbol), exchange="Unknown", country="Unknown", region="Unknown", currency="Unknown")


def load_domain(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if duckdb is None:
        raise RuntimeError("duckdb is required to load official data")
    dataset = root / "query_stockindex" / "query_dataset"
    info_path = dataset / "indexInfo_query.db"
    trade_path = dataset / "indextrade_query.db"

    info_conn = sqlite3.connect(info_path)
    try:
        info_table = info_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name LIMIT 1"
        ).fetchone()[0]
        columns = [row[1] for row in info_conn.execute(f'PRAGMA table_info("{info_table}")')]
        info_rows = [dict(zip(columns, row)) for row in info_conn.execute(f'SELECT * FROM "{info_table}"')]
    finally:
        info_conn.close()

    trade_conn = duckdb.connect(str(trade_path), read_only=True)
    try:
        trade_table = trade_conn.execute("SHOW TABLES").fetchone()[0]
        result = trade_conn.execute(f'SELECT * FROM "{trade_table}"')
        trade_columns = [item[0] for item in result.description]
        trade_rows = [dict(zip(trade_columns, row)) for row in result.fetchall()]
    finally:
        trade_conn.close()
    return info_rows, trade_rows


def enrich_rows(info_rows: Sequence[Mapping[str, Any]], trade_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    # Runtime metadata refresh: known exchange/currency spellings from the small
    # metadata DB replace public-map display labels, without relying on row order.
    exchange_rows = []
    for row in info_rows:
        values = {_key(k): v for k, v in row.items()}
        exchange_rows.append((_space(values.get("exchange")), _space(values.get("currency"))))

    enriched: list[dict[str, Any]] = []
    for raw in trade_rows:
        lookup = {_key(k): v for k, v in raw.items()}
        symbol = _space(lookup.get("index") or lookup.get("symbol") or lookup.get("ticker"))
        meta = metadata_for(symbol)
        exchange = meta.exchange
        currency = meta.currency
        # Match actual metadata rows by normalized exchange name.
        for actual_exchange, actual_currency in exchange_rows:
            if actual_exchange and (
                _key(actual_exchange) == _key(meta.exchange)
                or _key(actual_exchange) in _key(meta.exchange)
                or _key(meta.exchange) in _key(actual_exchange)
            ):
                exchange = actual_exchange
                currency = actual_currency or currency
                break
        enriched.append({
            "index": symbol,
            "date": _parse_date(lookup.get("date")),
            "open": _float(lookup.get("open")),
            "high": _float(lookup.get("high")),
            "low": _float(lookup.get("low")),
            "close": _float(lookup.get("close")),
            "adj_close": _float(lookup.get("adjclose") or lookup.get("adjustedclose")),
            "close_usd": _float(lookup.get("closeusd")),
            "exchange": exchange,
            "country": meta.country,
            "region": meta.region,
            "currency": currency,
        })
    return enriched


def _matches(plan: Plan, row: Mapping[str, Any]) -> bool:
    if row.get("date") is None:
        return False
    if plan.start_date and row["date"] < date.fromisoformat(plan.start_date):
        return False
    if plan.end_date and row["date"] > date.fromisoformat(plan.end_date):
        return False
    if plan.region and _key(row.get("region")) != _key(plan.region):
        return False
    if plan.country and _key(row.get("country")) != _key(plan.country):
        return False
    if plan.currency and _key(row.get("currency")) != _key(plan.currency):
        return False
    if plan.exchange and _key(row.get("exchange")) != _key(plan.exchange):
        return False
    if plan.symbols and _key(row.get("index")) not in {_key(symbol) for symbol in plan.symbols}:
        return False
    return True


def _series_metric(plan: Plan, rows: Sequence[Mapping[str, Any]]) -> float | None:
    ordered = sorted(rows, key=lambda row: row["date"])
    if not ordered:
        return None

    def valid(field: str) -> list[float]:
        return [float(row[field]) for row in ordered if row.get(field) is not None and math.isfinite(float(row[field]))]

    if plan.metric == "intraday_volatility":
        values = [
            (float(row["high"]) - float(row["low"])) / abs(float(row["open"]))
            for row in ordered
            if all(row.get(field) is not None for field in ("open", "high", "low")) and float(row["open"]) != 0
        ]
    elif plan.metric == "up_days":
        return float(sum(1 for row in ordered if row.get("open") is not None and row.get("close") is not None and row["close"] > row["open"]))
    elif plan.metric == "down_days":
        return float(sum(1 for row in ordered if row.get("open") is not None and row.get("close") is not None and row["close"] < row["open"]))
    elif plan.metric == "up_minus_down":
        up = sum(1 for row in ordered if row.get("open") is not None and row.get("close") is not None and row["close"] > row["open"])
        down = sum(1 for row in ordered if row.get("open") is not None and row.get("close") is not None and row["close"] < row["open"])
        return float(up - down)
    elif plan.metric in {"up_ratio", "down_ratio", "up_down_ratio"}:
        comparable = [row for row in ordered if row.get("open") is not None and row.get("close") is not None]
        if not comparable:
            return None
        up = sum(1 for row in comparable if row["close"] > row["open"])
        down = sum(1 for row in comparable if row["close"] < row["open"])
        if plan.metric == "up_ratio":
            return up / len(comparable)
        if plan.metric == "down_ratio":
            return down / len(comparable)
        return up / down if down else math.inf
    elif plan.metric == "daily_return":
        values = [
            (float(row["close"]) - float(row["open"])) / abs(float(row["open"]))
            for row in ordered
            if row.get("open") not in (None, 0) and row.get("close") is not None
        ]
    elif plan.metric in {"cumulative_return", "return_volatility", "max_drawdown"}:
        closes = [(row["date"], float(row["adj_close"] if row.get("adj_close") is not None else row["close"]))
                  for row in ordered if row.get("close") is not None or row.get("adj_close") is not None]
        if len(closes) < 2:
            return None
        if plan.metric == "cumulative_return":
            first, last = closes[0][1], closes[-1][1]
            return last / first - 1.0 if first else None
        returns = [closes[i][1] / closes[i - 1][1] - 1.0 for i in range(1, len(closes)) if closes[i - 1][1] != 0]
        if plan.metric == "return_volatility":
            return statistics.pstdev(returns) if returns else None
        peak = closes[0][1]
        worst = 0.0
        for _, close in closes:
            peak = max(peak, close)
            if peak:
                worst = min(worst, close / peak - 1.0)
        return worst
    elif plan.metric == "trading_days":
        return float(len({row["date"] for row in ordered}))
    else:
        field = {
            "open": "open", "high": "high", "low": "low", "close": "close",
            "adj_close": "adj_close", "close_usd": "close_usd",
        }[plan.metric]
        values = valid(field)

    if not values:
        return None
    if plan.reduction == "sum":
        return float(sum(values))
    if plan.reduction == "median":
        return float(statistics.median(values))
    if plan.reduction == "max":
        return float(max(values))
    if plan.reduction == "min":
        return float(min(values))
    if plan.reduction == "std":
        return float(statistics.pstdev(values))
    return float(sum(values) / len(values))


def evaluate(plan: Plan, rows: Sequence[Mapping[str, Any]]) -> Any:
    filtered = [row for row in rows if _matches(plan, row)]
    if plan.distinct_indices:
        return len({_space(row.get("index")) for row in filtered})

    group_field = {
        "index": "index", "exchange": "exchange", "country": "country",
        "region": "region", "currency": "currency",
    }[plan.group_by]
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in filtered:
        label = _space(row.get(group_field)) or "Unknown"
        groups.setdefault(label, []).append(row)

    scored = [(label, _series_metric(plan, group_rows)) for label, group_rows in groups.items()]
    scored = [(label, value) for label, value in scored if value is not None and math.isfinite(value)]
    if not scored:
        return None

    if plan.direction is None and len(scored) == 1:
        return scored[0][1]
    reverse = plan.direction != "min"
    scored.sort(key=lambda item: ((-item[1] if reverse else item[1]), _key(item[0])))
    selected = scored[: plan.top_k]
    return selected[0] if plan.top_k == 1 else selected


def render_answer(answer: Any, plan: Plan | None = None) -> str:
    if answer is None:
        return ""
    if isinstance(answer, int):
        return str(answer)
    if isinstance(answer, float):
        if math.isinf(answer):
            return "Infinity"
        return f"{answer:.12g}"
    if isinstance(answer, tuple) and len(answer) == 2:
        label, value = answer
        return f"{label}\n{label}: {value:.12g}"
    if isinstance(answer, list):
        return "\n".join(f"{label}: {value:.12g}" for label, value in answer)
    return _space(answer)


def solve(query: str, info_rows: Sequence[Mapping[str, Any]], trade_rows: Sequence[Mapping[str, Any]]) -> tuple[Plan, Any, str]:
    plan = plan_query(query)
    rows = enrich_rows(info_rows, trade_rows)
    answer = evaluate(plan, rows)
    return plan, answer, render_answer(answer, plan)


def read_query(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, str) else str(payload.get("query") or payload.get("question") or payload)


def write_outputs(output_dir: Path, query_id: str, query: str, plan: Plan, answer: Any) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{query_id}.txt").write_text(render_answer(answer, plan) + "\n", encoding="utf-8")
    (output_dir / f"{query_id}.json").write_text(
        json.dumps({"query": query, "plan": asdict(plan), "answer": answer}, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
