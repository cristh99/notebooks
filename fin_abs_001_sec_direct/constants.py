from __future__ import annotations

import os

SCHEMA = "fin-abs-001b/sec-direct-breadth/1"
POLICY_ID = "FIN-ABS-001B-SEC-DIRECT-RELATIONAL-VERIFIER-V1"
SEC_BASE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "cristh99 finance-research 87334928+cristh99@users.noreply.github.com",
)
ABSOLUTE_SCORE_BEFORE = 423
ABSOLUTE_SCORE_PASS_DELTA = 8
RELATIVE_TOLERANCE = 0.001
ABSOLUTE_TOLERANCE = 2.0
MIN_RELATIONS_FOR_DECISION = 1
FETCH_RETRIES = 4
REQUEST_INTERVAL_SECONDS = 0.12
PERMUTATION_SEED = "FIN-ABS-001B-PERMUTATION-V1"

# Frozen before data inspection: the same 50-company universe used by the
# public FinVerBench acquisition script.
UNIVERSE: tuple[dict[str, str], ...] = (
    {"ticker": "AAPL", "cik": "0000320193", "name": "Apple Inc."},
    {"ticker": "MSFT", "cik": "0000789019", "name": "Microsoft Corporation"},
    {"ticker": "AMZN", "cik": "0001018724", "name": "Amazon.com Inc."},
    {"ticker": "GOOGL", "cik": "0001652044", "name": "Alphabet Inc."},
    {"ticker": "META", "cik": "0001326801", "name": "Meta Platforms Inc."},
    {"ticker": "BRK.B", "cik": "0001067983", "name": "Berkshire Hathaway Inc."},
    {"ticker": "JNJ", "cik": "0000200406", "name": "Johnson & Johnson"},
    {"ticker": "V", "cik": "0001403161", "name": "Visa Inc."},
    {"ticker": "JPM", "cik": "0000019617", "name": "JPMorgan Chase & Co."},
    {"ticker": "PG", "cik": "0000080424", "name": "Procter & Gamble Company"},
    {"ticker": "UNH", "cik": "0000731766", "name": "UnitedHealth Group Inc."},
    {"ticker": "HD", "cik": "0000354950", "name": "The Home Depot Inc."},
    {"ticker": "MA", "cik": "0001141391", "name": "Mastercard Inc."},
    {"ticker": "NVDA", "cik": "0001045810", "name": "NVIDIA Corporation"},
    {"ticker": "DIS", "cik": "0001744489", "name": "The Walt Disney Company"},
    {"ticker": "BAC", "cik": "0000070858", "name": "Bank of America Corporation"},
    {"ticker": "XOM", "cik": "0000034088", "name": "Exxon Mobil Corporation"},
    {"ticker": "PFE", "cik": "0000078003", "name": "Pfizer Inc."},
    {"ticker": "CSCO", "cik": "0000858877", "name": "Cisco Systems Inc."},
    {"ticker": "KO", "cik": "0000021344", "name": "The Coca-Cola Company"},
    {"ticker": "PEP", "cik": "0000077476", "name": "PepsiCo Inc."},
    {"ticker": "TMO", "cik": "0000097745", "name": "Thermo Fisher Scientific Inc."},
    {"ticker": "COST", "cik": "0000909832", "name": "Costco Wholesale Corporation"},
    {"ticker": "ABT", "cik": "0000001800", "name": "Abbott Laboratories"},
    {"ticker": "CRM", "cik": "0001108524", "name": "Salesforce Inc."},
    {"ticker": "AVGO", "cik": "0001649338", "name": "Broadcom Inc."},
    {"ticker": "NKE", "cik": "0000320187", "name": "NIKE Inc."},
    {"ticker": "MRK", "cik": "0000310158", "name": "Merck & Co. Inc."},
    {"ticker": "WMT", "cik": "0000104169", "name": "Walmart Inc."},
    {"ticker": "CVX", "cik": "0000093410", "name": "Chevron Corporation"},
    {"ticker": "LLY", "cik": "0000059478", "name": "Eli Lilly and Company"},
    {"ticker": "ADBE", "cik": "0000796343", "name": "Adobe Inc."},
    {"ticker": "ORCL", "cik": "0001341439", "name": "Oracle Corporation"},
    {"ticker": "CMCSA", "cik": "0001166691", "name": "Comcast Corporation"},
    {"ticker": "ACN", "cik": "0001281761", "name": "Accenture plc"},
    {"ticker": "INTC", "cik": "0000050863", "name": "Intel Corporation"},
    {"ticker": "VZ", "cik": "0000732712", "name": "Verizon Communications Inc."},
    {"ticker": "T", "cik": "0000732717", "name": "AT&T Inc."},
    {"ticker": "MCD", "cik": "0000063908", "name": "McDonald's Corporation"},
    {"ticker": "TXN", "cik": "0000097476", "name": "Texas Instruments Inc."},
    {"ticker": "HON", "cik": "0000773840", "name": "Honeywell International Inc."},
    {"ticker": "NEE", "cik": "0000753308", "name": "NextEra Energy Inc."},
    {"ticker": "UPS", "cik": "0001090727", "name": "United Parcel Service Inc."},
    {"ticker": "PM", "cik": "0001413329", "name": "Philip Morris International Inc."},
    {"ticker": "LOW", "cik": "0000060667", "name": "Lowe's Companies Inc."},
    {"ticker": "GS", "cik": "0000886982", "name": "The Goldman Sachs Group Inc."},
    {"ticker": "CAT", "cik": "0000018230", "name": "Caterpillar Inc."},
    {"ticker": "BA", "cik": "0000012927", "name": "The Boeing Company"},
    {"ticker": "AMGN", "cik": "0000318154", "name": "Amgen Inc."},
    {"ticker": "GE", "cik": "0000040554", "name": "General Electric Company"},
)

INSTANT_CONCEPTS: dict[str, tuple[str, ...]] = {
    "assets": ("Assets",),
    "liabilities_and_equity": ("LiabilitiesAndStockholdersEquity",),
    "liabilities": ("Liabilities",),
    "equity": (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ),
    "cash": (
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "CashAndCashEquivalentsAtCarryingValue",
    ),
}

DURATION_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": (
        "CostOfRevenue",
        "CostOfGoodsAndServicesSold",
        "CostOfGoodsSold",
    ),
    "gross_profit": ("GrossProfit",),
    "cfo": ("NetCashProvidedByUsedInOperatingActivities",),
    "cfi": ("NetCashProvidedByUsedInInvestingActivities",),
    "cff": ("NetCashProvidedByUsedInFinancingActivities",),
    "net_change_cash": (
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
    ),
    "fx_effect": (
        "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "EffectOfExchangeRateOnCashAndCashEquivalents",
    ),
}
