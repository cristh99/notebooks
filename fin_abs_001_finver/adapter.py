from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


UPSTREAM_COMMIT = "8aef2f48befdab5c57cc383a521711fe11c2df98"


@dataclass(frozen=True)
class AdaptationResult:
    ticker: str
    status: str
    fiscal_year: str | None
    statement: dict[str, Any] | None
    reason: str
    source_file: str

    def to_data(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "status": self.status,
            "fiscal_year": self.fiscal_year,
            "statement": self.statement,
            "reason": self.reason,
            "source_file": self.source_file,
        }


LABELS: dict[str, tuple[str, ...]] = {
    "assets": ("Total Assets",),
    "liabilities": ("Total Liabilities",),
    "equity": ("Total Stockholders Equity",),
    "liabilities_equity": ("Total Liabilities and Equity",),
    "cash": ("Cash and Cash Equivalents",),
    "receivables": ("Accounts Receivable",),
    "inventory": ("Inventory",),
    "current_assets": ("Total Current Assets",),
    "ppe": ("Property, Plant and Equipment (net)",),
    "current_liabilities": ("Total Current Liabilities",),
    "long_term_debt": ("Long-Term Debt", "Long-Term Debt (non-current)"),
    "retained_earnings": ("Retained Earnings (Accumulated Deficit)",),
    "revenue": ("Total Revenue", "Revenue from Contracts", "Net Sales Revenue"),
    "cogs": ("Cost of Goods Sold", "Cost of Revenue"),
    "gross_profit": ("Gross Profit",),
    "operating_expenses": ("Operating Expenses", "SG&A Expense"),
    "operating_income": ("Operating Income (Loss)",),
    "interest": ("Interest Expense",),
    "tax": ("Income Tax Expense",),
    "net_income": ("Net Income (Loss)",),
    "cfo": ("Cash from Operating Activities",),
    "cfi": ("Cash from Investing Activities",),
    "cff": ("Cash from Financing Activities",),
    "net_change_cash": ("Net Change in Cash", "Net Change in Cash (legacy)"),
    "da": ("Depreciation & Amortization",),
    "capex": ("Capital Expenditures",),
    "dividends": ("Dividends Paid", "Common Dividends Paid"),
    "debt_repayment": ("Repayments of Long-Term Debt",),
}

_REQUIRED_CURRENT = (
    "assets",
    "liabilities",
    "cash",
    "revenue",
    "operating_income",
    "net_income",
    "cfo",
)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _periods(statement: Mapping[str, Any], section: str, labels: Sequence[str]) -> Mapping[str, Any]:
    items = statement.get(section, {}).get("line_items", {})
    if not isinstance(items, Mapping):
        return {}
    for label in labels:
        item = items.get(label)
        if isinstance(item, Mapping):
            periods = item.get("periods")
            if isinstance(periods, Mapping):
                return periods
    return {}


def _value(
    statement: Mapping[str, Any],
    section: str,
    key: str,
    fiscal_year: str,
) -> float | None:
    periods = _periods(statement, section, LABELS[key])
    node = periods.get(fiscal_year)
    if not isinstance(node, Mapping):
        return None
    value = node.get("value")
    return float(value) if _is_number(value) else None


def _all_years(statement: Mapping[str, Any]) -> list[str]:
    years: set[str] = set()
    metadata_years = statement.get("metadata", {}).get("fiscal_years", [])
    if isinstance(metadata_years, list):
        years.update(str(value) for value in metadata_years if re.fullmatch(r"FY\d{4}", str(value)))
    for section in ("balance_sheet", "income_statement", "cash_flow_statement"):
        items = statement.get(section, {}).get("line_items", {})
        if not isinstance(items, Mapping):
            continue
        for item in items.values():
            if isinstance(item, Mapping) and isinstance(item.get("periods"), Mapping):
                years.update(str(value) for value in item["periods"] if re.fullmatch(r"FY\d{4}", str(value)))
    return sorted(years, key=lambda value: int(value[2:]), reverse=True)


def _has_required(statement: Mapping[str, Any], fiscal_year: str, prior_year: str) -> bool:
    sections = {
        "assets": "balance_sheet",
        "liabilities": "balance_sheet",
        "cash": "balance_sheet",
        "revenue": "income_statement",
        "operating_income": "income_statement",
        "net_income": "income_statement",
        "cfo": "cash_flow_statement",
    }
    for key in _REQUIRED_CURRENT:
        if _value(statement, sections[key], key, fiscal_year) is None:
            return False
    for key in ("assets", "liabilities", "cash"):
        if _value(statement, "balance_sheet", key, prior_year) is None:
            return False
    return True


def select_year(statement: Mapping[str, Any]) -> tuple[str, str] | None:
    years = _all_years(statement)
    year_set = set(years)
    for fiscal_year in years:
        year = int(fiscal_year[2:])
        prior = f"FY{year - 1}"
        if prior in year_set and _has_required(statement, fiscal_year, prior):
            return fiscal_year, prior
    return None


def _non_negative(value: float, *, name: str) -> float:
    if value < -1e-6:
        raise ValueError(f"{name} became negative: {value}")
    return max(0.0, value)


def _safe_component(total: float, preferred: float | None) -> float:
    if preferred is None or preferred < 0 or preferred > total:
        return 0.0
    return float(preferred)


def _balance_year(statement: Mapping[str, Any], fy: str) -> tuple[dict[str, float], list[str]]:
    assets_value = _value(statement, "balance_sheet", "assets", fy)
    liabilities_value = _value(statement, "balance_sheet", "liabilities", fy)
    cash_value = _value(statement, "balance_sheet", "cash", fy)
    if assets_value is None or liabilities_value is None or cash_value is None:
        raise ValueError("required balance-sheet total missing")
    assets = float(assets_value)
    liabilities = float(liabilities_value)
    cash = float(cash_value)
    if min(assets, liabilities, cash) < 0 or cash > assets:
        raise ValueError("incoherent balance-sheet totals")

    derivations: list[str] = []
    reported_current_assets = _value(statement, "balance_sheet", "current_assets", fy)
    receivables_reported = _value(statement, "balance_sheet", "receivables", fy)
    inventory_reported = _value(statement, "balance_sheet", "inventory", fy)
    receivables_seed = max(0.0, float(receivables_reported or 0.0))
    inventory_seed = max(0.0, float(inventory_reported or 0.0))
    if reported_current_assets is None:
        current_assets = min(assets, cash + receivables_seed + inventory_seed)
        if current_assets < cash:
            current_assets = cash
        derivations.append("total_current_assets_from_visible_current_components")
    else:
        current_assets = float(reported_current_assets)
        if current_assets < cash or current_assets > assets:
            current_assets = cash
            derivations.append("total_current_assets_reset_to_cash_due_hierarchy_conflict")

    receivables = _safe_component(current_assets - cash, receivables_reported)
    inventory = _non_negative(current_assets - cash - receivables, name="current-assets residual")
    if abs(inventory - inventory_seed) > 1e-6:
        derivations.append("inventory_as_current_assets_residual")
    ppe_residual = _non_negative(assets - current_assets, name="non-current-assets residual")
    derivations.append("property_plant_equipment_as_noncurrent_assets_residual")

    reported_current_liabilities = _value(statement, "balance_sheet", "current_liabilities", fy)
    if reported_current_liabilities is None:
        current_liabilities = 0.0
        derivations.append("total_current_liabilities_missing_set_zero")
    else:
        current_liabilities = float(reported_current_liabilities)
        if current_liabilities < 0 or current_liabilities > liabilities:
            current_liabilities = 0.0
            derivations.append("total_current_liabilities_reset_zero_due_hierarchy_conflict")
    accounts_payable = 0.0
    short_term_debt = current_liabilities
    long_term_debt = _non_negative(liabilities - current_liabilities, name="non-current-liabilities residual")
    derivations.extend((
        "accounts_payable_unavailable_set_zero",
        "short_term_debt_as_current_liabilities_residual",
        "long_term_debt_as_noncurrent_liabilities_residual",
    ))
    equity = assets - liabilities
    if equity < -1e-6:
        raise ValueError("negative derived equity")

    return {
        "cash_and_equivalents": cash,
        "accounts_receivable": receivables,
        "inventory": inventory,
        "total_current_assets": current_assets,
        "property_plant_equipment": ppe_residual,
        "total_assets": assets,
        "accounts_payable": accounts_payable,
        "short_term_debt": short_term_debt,
        "total_current_liabilities": current_liabilities,
        "long_term_debt": long_term_debt,
        "total_liabilities": liabilities,
        "retained_earnings": 0.0,
        "total_equity": equity,
        "total_liabilities_and_equity": assets,
    }, derivations


def adapt_statement(source: Mapping[str, Any], ticker: str, source_file: str) -> AdaptationResult:
    selected = select_year(source)
    if selected is None:
        return AdaptationResult(ticker, "EXCLUDED", None, None, "no complete consecutive-year slice", source_file)
    fiscal_year, prior_year = selected
    try:
        current_bs, current_derivations = _balance_year(source, fiscal_year)
        prior_bs, prior_derivations = _balance_year(source, prior_year)

        revenue_value = _value(source, "income_statement", "revenue", fiscal_year)
        operating_income_value = _value(source, "income_statement", "operating_income", fiscal_year)
        net_income_value = _value(source, "income_statement", "net_income", fiscal_year)
        cfo_value = _value(source, "cash_flow_statement", "cfo", fiscal_year)
        if None in (revenue_value, operating_income_value, net_income_value, cfo_value):
            raise ValueError("required operating statement value missing")
        revenue = float(revenue_value)
        operating_income = float(operating_income_value)
        net_income = float(net_income_value)
        cfo = float(cfo_value)
        if revenue == 0:
            raise ValueError("zero revenue")

        gross_profit = _value(source, "income_statement", "gross_profit", fiscal_year)
        raw_cogs = _value(source, "income_statement", "cogs", fiscal_year)
        if gross_profit is None:
            gross_profit = revenue if raw_cogs is None else revenue - abs(raw_cogs)
        gross_profit = float(gross_profit)

        da_raw = _value(source, "cash_flow_statement", "da", fiscal_year)
        da = abs(float(da_raw or 0.0))
        cogs = gross_profit - revenue
        da_income = -da
        operating_expenses = operating_income - gross_profit - da_income

        tax_raw = _value(source, "income_statement", "tax", fiscal_year)
        tax = -abs(float(tax_raw or 0.0))
        pretax = net_income - tax
        interest = pretax - operating_income

        beginning_cash = prior_bs["cash_and_equivalents"]
        ending_cash = current_bs["cash_and_equivalents"]
        net_change_cash = ending_cash - beginning_cash
        cfi_raw = _value(source, "cash_flow_statement", "cfi", fiscal_year)
        cff_raw = _value(source, "cash_flow_statement", "cff", fiscal_year)
        if cfi_raw is not None:
            cfi = float(cfi_raw)
        elif cff_raw is not None:
            cfi = net_change_cash - cfo - float(cff_raw)
        else:
            cfi = 0.0
        cff = net_change_cash - cfo - cfi
        dividends_raw = _value(source, "cash_flow_statement", "dividends", fiscal_year)
        dividends = -abs(float(dividends_raw or 0.0))
        debt_repayment = cff - dividends
        changes_wc = cfo - net_income - da

        prior_re_raw = _value(source, "balance_sheet", "retained_earnings", prior_year)
        prior_re = float(prior_re_raw or 0.0)
        prior_bs["retained_earnings"] = prior_re
        current_bs["retained_earnings"] = prior_re + net_income + dividends

        derivations = sorted(set(current_derivations + prior_derivations + [
            "cost_of_goods_sold_from_revenue_and_gross_profit",
            "operating_expenses_as_operating_income_residual",
            "income_before_tax_from_net_income_and_tax",
            "interest_expense_as_pretax_operating_income_residual",
            "changes_in_working_capital_as_CFO_residual",
            "cash_from_financing_as_cash_reconciliation_residual",
            "debt_repayment_as_financing_dividend_residual",
            "retained_earnings_as_prior_RE_net_income_dividend_bridge",
        ]))
        statement = {
            "company": source.get("metadata", {}).get("entity_name") or ticker,
            "ticker": ticker,
            "period": fiscal_year,
            "currency": "USD",
            "unit": "as-filed",
            "adapter": {
                "schema": "fin-abs-001a/finver-adapter/2",
                "upstream_commit": UPSTREAM_COMMIT,
                "source_file": source_file,
                "prior_period": prior_year,
                "derived_or_residualized_fields": derivations,
                "maximum_claim": "construct-validity slice over high-level reported totals",
            },
            "income_statement": {
                "revenue": revenue,
                "cost_of_goods_sold": cogs,
                "gross_profit": gross_profit,
                "operating_expenses": operating_expenses,
                "depreciation_amortization": da_income,
                "operating_income": operating_income,
                "interest_expense": interest,
                "income_before_tax": pretax,
                "income_tax_expense": tax,
                "net_income": net_income,
            },
            "balance_sheet": {"current_year": current_bs, "prior_year": prior_bs},
            "cash_flow_statement": {
                "net_income": net_income,
                "depreciation_amortization": da,
                "changes_in_working_capital": changes_wc,
                "cash_from_operations": cfo,
                "capital_expenditures": cfi,
                "cash_from_investing": cfi,
                "debt_repayment": debt_repayment,
                "dividends_paid": dividends,
                "cash_from_financing": cff,
                "net_change_in_cash": net_change_cash,
                "beginning_cash": beginning_cash,
                "ending_cash": ending_cash,
            },
        }
        return AdaptationResult(ticker, "ADAPTED", fiscal_year, statement, "ok", source_file)
    except (TypeError, ValueError) as exc:
        return AdaptationResult(ticker, "EXCLUDED", fiscal_year, None, f"{type(exc).__name__}: {exc}", source_file)


def adapt_directory(processed_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[AdaptationResult] = []
    for path in sorted(processed_dir.glob("*.json")):
        try:
            source = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            results.append(AdaptationResult(path.stem, "EXCLUDED", None, None, f"read-error: {exc}", str(path)))
            continue
        result = adapt_statement(source, path.stem, str(path))
        results.append(result)
        if result.statement is not None:
            target = output_dir / f"{path.stem}.json"
            target.write_text(json.dumps(result.statement, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "schema": "fin-abs-001a/adapter-manifest/2",
        "upstream_commit": UPSTREAM_COMMIT,
        "processed_dir": str(processed_dir),
        "output_dir": str(output_dir),
        "files_seen": len(results),
        "adapted": sum(item.status == "ADAPTED" for item in results),
        "excluded": sum(item.status != "ADAPTED" for item in results),
        "results": [item.to_data() | {"statement": None} for item in results],
        "boundary": (
            "The adapter preserves reported high-level totals but uses explicit residual buckets and zero placeholders where the upstream SEC map lacks a simplified component. "
            "It is an external construct-validity slice, not a claim that residual labels are audited line-item identities or that sector-specific statement formats are equivalent."
        ),
    }
    (output_dir / "adapter_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def audit_upstream_schema(processed_dir: Path) -> dict[str, Any]:
    files = sorted(processed_dir.glob("*.json"))
    sampled = 0
    compatible = 0
    incompatible_examples: list[str] = []
    for path in files[:10]:
        sampled += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            incompatible_examples.append(f"{path.name}: unreadable")
            continue
        expected = (
            isinstance(data, Mapping)
            and "company" in data
            and isinstance(data.get("income_statement"), Mapping)
            and "revenue" in data.get("income_statement", {})
            and isinstance(data.get("balance_sheet", {}).get("current_year"), Mapping)
        )
        if expected:
            compatible += 1
        else:
            incompatible_examples.append(f"{path.name}: parsed-XBRL-line-items schema")
    return {
        "schema": "fin-abs-001a/upstream-schema-audit/1",
        "upstream_commit": UPSTREAM_COMMIT,
        "files": len(files),
        "sampled": sampled,
        "dataset_builder_compatible": compatible,
        "pipeline_status": "PASS" if sampled and compatible == sampled else "SCHEMA_MISMATCH",
        "incompatible_examples": incompatible_examples,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("processed_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    audit = audit_upstream_schema(args.processed_dir)
    if args.audit_output:
        args.audit_output.parent.mkdir(parents=True, exist_ok=True)
        args.audit_output.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = adapt_directory(args.processed_dir, args.output_dir)
    print(json.dumps({"audit": audit["pipeline_status"], "adapted": manifest["adapted"], "excluded": manifest["excluded"]}, sort_keys=True))
    return 0 if manifest["adapted"] >= 10 else 2


if __name__ == "__main__":
    raise SystemExit(main())
