from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


POLICY_ID = "FIN-ABS-001A-CALIBRATED-RELATIONAL-VERIFIER-V1"
MIN_CHECKS = 14
RELATIVE_TOLERANCE = 0.001
ABSOLUTE_TOLERANCE = 2.0


@dataclass(frozen=True)
class Check:
    check_id: str
    observed: float
    expected: float
    residual: float
    tolerance: float
    passed: bool
    paths: tuple[str, ...]

    def to_data(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _nested(data: Mapping[str, Any], path: str) -> float | None:
    node: object = data
    for part in path.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return _number(node)


def _tolerance(observed: float, expected: float) -> float:
    scale = max(abs(observed), abs(expected), 1.0)
    return max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * scale)


def _make_check(
    check_id: str,
    observed_path: str,
    observed: float | None,
    expected: float | None,
    paths: Iterable[str],
) -> Check | None:
    if observed is None or expected is None:
        return None
    tolerance = _tolerance(observed, expected)
    residual = observed - expected
    all_paths = tuple(dict.fromkeys((observed_path, *paths)))
    return Check(
        check_id=check_id,
        observed=observed,
        expected=expected,
        residual=residual,
        tolerance=tolerance,
        passed=abs(residual) <= tolerance,
        paths=all_paths,
    )


def _sum_paths(statement: Mapping[str, Any], paths: Iterable[str]) -> float | None:
    values = [_nested(statement, path) for path in paths]
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def visible_checks(statement: Mapping[str, Any]) -> list[Check]:
    checks: list[Check] = []

    formulas = (
        (
            "IS_GROSS_PROFIT",
            "income_statement.gross_profit",
            (
                "income_statement.revenue",
                "income_statement.cost_of_goods_sold",
            ),
        ),
        (
            "IS_OPERATING_INCOME",
            "income_statement.operating_income",
            (
                "income_statement.gross_profit",
                "income_statement.operating_expenses",
                "income_statement.depreciation_amortization",
            ),
        ),
        (
            "IS_PRETAX_INCOME",
            "income_statement.income_before_tax",
            (
                "income_statement.operating_income",
                "income_statement.interest_expense",
            ),
        ),
        (
            "IS_NET_INCOME",
            "income_statement.net_income",
            (
                "income_statement.income_before_tax",
                "income_statement.income_tax_expense",
            ),
        ),
        (
            "CFS_OPERATING_CASH",
            "cash_flow_statement.cash_from_operations",
            (
                "cash_flow_statement.net_income",
                "cash_flow_statement.depreciation_amortization",
                "cash_flow_statement.changes_in_working_capital",
            ),
        ),
        (
            "CFS_INVESTING_CASH",
            "cash_flow_statement.cash_from_investing",
            ("cash_flow_statement.capital_expenditures",),
        ),
        (
            "CFS_FINANCING_CASH",
            "cash_flow_statement.cash_from_financing",
            (
                "cash_flow_statement.debt_repayment",
                "cash_flow_statement.dividends_paid",
            ),
        ),
        (
            "CFS_NET_CHANGE",
            "cash_flow_statement.net_change_in_cash",
            (
                "cash_flow_statement.cash_from_operations",
                "cash_flow_statement.cash_from_investing",
                "cash_flow_statement.cash_from_financing",
            ),
        ),
        (
            "CFS_ENDING_CASH",
            "cash_flow_statement.ending_cash",
            (
                "cash_flow_statement.beginning_cash",
                "cash_flow_statement.net_change_in_cash",
            ),
        ),
    )
    for check_id, observed_path, components in formulas:
        check = _make_check(
            check_id,
            observed_path,
            _nested(statement, observed_path),
            _sum_paths(statement, components),
            components,
        )
        if check is not None:
            checks.append(check)

    for period in ("current_year", "prior_year"):
        base = f"balance_sheet.{period}"
        balance_formulas = (
            (
                f"BS_{period.upper()}_CURRENT_ASSETS",
                f"{base}.total_current_assets",
                (
                    f"{base}.cash_and_equivalents",
                    f"{base}.accounts_receivable",
                    f"{base}.inventory",
                ),
            ),
            (
                f"BS_{period.upper()}_TOTAL_ASSETS",
                f"{base}.total_assets",
                (
                    f"{base}.total_current_assets",
                    f"{base}.property_plant_equipment",
                ),
            ),
            (
                f"BS_{period.upper()}_CURRENT_LIABILITIES",
                f"{base}.total_current_liabilities",
                (
                    f"{base}.accounts_payable",
                    f"{base}.short_term_debt",
                ),
            ),
            (
                f"BS_{period.upper()}_TOTAL_LIABILITIES",
                f"{base}.total_liabilities",
                (
                    f"{base}.total_current_liabilities",
                    f"{base}.long_term_debt",
                ),
            ),
            (
                f"BS_{period.upper()}_LIABILITIES_EQUITY",
                f"{base}.total_liabilities_and_equity",
                (
                    f"{base}.total_liabilities",
                    f"{base}.total_equity",
                ),
            ),
            (
                f"BS_{period.upper()}_ACCOUNTING_IDENTITY",
                f"{base}.total_assets",
                (f"{base}.total_liabilities_and_equity",),
            ),
        )
        for check_id, observed_path, components in balance_formulas:
            check = _make_check(
                check_id,
                observed_path,
                _nested(statement, observed_path),
                _sum_paths(statement, components),
                components,
            )
            if check is not None:
                checks.append(check)

    cross_equalities = (
        (
            "CROSS_NET_INCOME",
            "cash_flow_statement.net_income",
            "income_statement.net_income",
            False,
        ),
        (
            "CROSS_ENDING_CASH",
            "cash_flow_statement.ending_cash",
            "balance_sheet.current_year.cash_and_equivalents",
            False,
        ),
        (
            "CROSS_BEGINNING_CASH",
            "cash_flow_statement.beginning_cash",
            "balance_sheet.prior_year.cash_and_equivalents",
            False,
        ),
        (
            "CROSS_DEPRECIATION",
            "cash_flow_statement.depreciation_amortization",
            "income_statement.depreciation_amortization",
            True,
        ),
    )
    for check_id, observed_path, expected_path, absolute in cross_equalities:
        observed = _nested(statement, observed_path)
        expected = _nested(statement, expected_path)
        if absolute and observed is not None and expected is not None:
            observed = abs(observed)
            expected = abs(expected)
        check = _make_check(
            check_id,
            observed_path,
            observed,
            expected,
            (expected_path,),
        )
        if check is not None:
            checks.append(check)

    retained_paths = (
        "balance_sheet.prior_year.retained_earnings",
        "income_statement.net_income",
        "cash_flow_statement.dividends_paid",
    )
    retained_check = _make_check(
        "CROSS_RETAINED_EARNINGS",
        "balance_sheet.current_year.retained_earnings",
        _nested(statement, "balance_sheet.current_year.retained_earnings"),
        _sum_paths(statement, retained_paths),
        retained_paths,
    )
    if retained_check is not None:
        checks.append(retained_check)
    return checks


def predict(statement: Mapping[str, Any]) -> dict[str, Any]:
    checks = visible_checks(statement)
    failed = [check for check in checks if not check.passed]
    families = {
        check.check_id.split("_", 1)[0]
        for check in checks
    }
    enough = len(checks) >= MIN_CHECKS and {"IS", "BS", "CFS", "CROSS"}.issubset(families)
    if not enough:
        decision = "ABSTAIN"
    elif failed:
        decision = "ERROR"
    else:
        decision = "CLEAN"
    return {
        "policy_id": POLICY_ID,
        "decision": decision,
        "check_count": len(checks),
        "failed_count": len(failed),
        "failed_checks": [check.to_data() for check in failed],
        "all_checks": [check.to_data() for check in checks],
        "visible_paths": sorted({path for check in checks for path in check.paths}),
        "boundary": (
            "The verifier judges only visible declared arithmetic and cross-statement relationships. "
            "Missing or underdetermined relationships cause abstention rather than an invented error."
        ),
    }


def reporting_variant(statement: Mapping[str, Any], divisor: float = 1_000_000.0) -> dict[str, Any]:
    """Simulate statements reported in rounded millions.

    Metadata remains unchanged. Every visible financial number is divided by
    ``divisor`` and rounded to the nearest reporting unit.
    """
    result = copy.deepcopy(statement)

    def scale(node: object, path: tuple[str, ...] = ()) -> object:
        if isinstance(node, dict):
            return {key: scale(value, (*path, str(key))) for key, value in node.items()}
        if isinstance(node, list):
            return [scale(value, path) for value in node]
        if isinstance(node, (int, float)) and path and path[0] in {
            "income_statement",
            "balance_sheet",
            "cash_flow_statement",
        }:
            return round(float(node) / divisor)
        return node

    result = scale(result)  # type: ignore[assignment]
    if isinstance(result, dict):
        result["unit"] = "rounded millions"
        result["reporting_variant"] = {
            "divisor": divisor,
            "rounding": "nearest integer",
        }
    return result  # type: ignore[return-value]
