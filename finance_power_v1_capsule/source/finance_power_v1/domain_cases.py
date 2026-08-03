from __future__ import annotations

from fractions import Fraction

from logic_power_v10 import ActiveDiscoveryProblem

from .finite_decision import (
    EvidenceAcquisition,
    FinancialWorld,
    compile_financial_decision,
)


def _uniform_worlds(
    rows: tuple[tuple[str, bool, dict[str, str]], ...]
) -> tuple[FinancialWorld, ...]:
    prior = Fraction(1, len(rows))
    return tuple(
        FinancialWorld(
            world_id=world_id,
            decision=decision,
            prior=prior,
            attributes=attributes,
        )
        for world_id, decision, attributes in rows
    )


def make_credit_underwriting_problem(
    *, complete: bool = True
) -> ActiveDiscoveryProblem:
    worlds = _uniform_worlds(
        (
            (
                "clean__strong__low",
                True,
                {
                    "identity": "clean",
                    "cashflow": "strong",
                    "leverage": "low",
                },
            ),
            (
                "clean__strong__high",
                False,
                {
                    "identity": "clean",
                    "cashflow": "strong",
                    "leverage": "high",
                },
            ),
            (
                "clean__weak__low",
                False,
                {
                    "identity": "clean",
                    "cashflow": "weak",
                    "leverage": "low",
                },
            ),
            (
                "fraud__strong__low",
                False,
                {
                    "identity": "fraud",
                    "cashflow": "strong",
                    "leverage": "low",
                },
            ),
        )
    )
    evidence = [
        EvidenceAcquisition("identity_check", Fraction(1), ("identity",)),
        EvidenceAcquisition("cashflow_scan", Fraction(2), ("cashflow",)),
        EvidenceAcquisition("leverage_pull", Fraction(2), ("leverage",)),
        EvidenceAcquisition(
            "full_underwriting",
            Fraction(6),
            ("identity", "cashflow", "leverage"),
        ),
    ]
    if not complete:
        evidence = [
            item for item in evidence
            if "identity" not in item.fields
        ]
    return compile_financial_decision(worlds, evidence)


def make_liquidity_intervention_problem(
    *, complete: bool = True
) -> ActiveDiscoveryProblem:
    worlds = _uniform_worlds(
        (
            (
                "temporary__adequate",
                True,
                {"run": "temporary", "collateral": "adequate"},
            ),
            (
                "temporary__deficient",
                False,
                {"run": "temporary", "collateral": "deficient"},
            ),
            (
                "solvency__adequate",
                False,
                {"run": "solvency", "collateral": "adequate"},
            ),
            (
                "solvency__deficient",
                False,
                {"run": "solvency", "collateral": "deficient"},
            ),
        )
    )
    evidence = [
        EvidenceAcquisition("liquidity_forensics", Fraction(2), ("run",)),
        EvidenceAcquisition("collateral_audit", Fraction(1), ("collateral",)),
        EvidenceAcquisition(
            "joint_stress_test",
            Fraction(4),
            ("run", "collateral"),
        ),
    ]
    if not complete:
        evidence = [
            item for item in evidence
            if "run" not in item.fields
        ]
    return compile_financial_decision(worlds, evidence)


def make_insurance_reserve_problem(
    *, complete: bool = True
) -> ActiveDiscoveryProblem:
    worlds = _uniform_worlds(
        (
            (
                "light__accurate__low",
                False,
                {
                    "severity": "light",
                    "reporting": "accurate",
                    "inflation": "low",
                },
            ),
            (
                "severe__accurate__low",
                True,
                {
                    "severity": "severe",
                    "reporting": "accurate",
                    "inflation": "low",
                },
            ),
            (
                "light__delayed__low",
                True,
                {
                    "severity": "light",
                    "reporting": "delayed",
                    "inflation": "low",
                },
            ),
            (
                "light__accurate__high",
                True,
                {
                    "severity": "light",
                    "reporting": "accurate",
                    "inflation": "high",
                },
            ),
        )
    )
    evidence = [
        EvidenceAcquisition("severity_review", Fraction(2), ("severity",)),
        EvidenceAcquisition("reporting_lag_scan", Fraction(1), ("reporting",)),
        EvidenceAcquisition("inflation_stress", Fraction(1), ("inflation",)),
        EvidenceAcquisition(
            "full_actuarial_review",
            Fraction(5),
            ("severity", "reporting", "inflation"),
        ),
    ]
    if not complete:
        evidence = [
            item for item in evidence
            if "inflation" not in item.fields
        ]
    return compile_financial_decision(worlds, evidence)


def make_portfolio_hedge_problem(
    *, complete: bool = True
) -> ActiveDiscoveryProblem:
    worlds = _uniform_worlds(
        (
            (
                "low_beta__calm",
                False,
                {"beta": "low", "volatility": "calm"},
            ),
            (
                "low_beta__shock",
                True,
                {"beta": "low", "volatility": "shock"},
            ),
            (
                "high_beta__calm",
                True,
                {"beta": "high", "volatility": "calm"},
            ),
            (
                "high_beta__shock",
                True,
                {"beta": "high", "volatility": "shock"},
            ),
        )
    )
    evidence = [
        EvidenceAcquisition("factor_exposure", Fraction(1), ("beta",)),
        EvidenceAcquisition("volatility_regime", Fraction(2), ("volatility",)),
        EvidenceAcquisition(
            "joint_risk_model",
            Fraction(4),
            ("beta", "volatility"),
        ),
    ]
    if not complete:
        evidence = [
            item for item in evidence
            if "volatility" not in item.fields
        ]
    return compile_financial_decision(worlds, evidence)


def all_domain_cases(
) -> dict[str, tuple[ActiveDiscoveryProblem, ActiveDiscoveryProblem]]:
    """Exact and impossible instances for every generic finance domain."""
    return {
        "credit_underwriting": (
            make_credit_underwriting_problem(),
            make_credit_underwriting_problem(complete=False),
        ),
        "insurance_reserve": (
            make_insurance_reserve_problem(),
            make_insurance_reserve_problem(complete=False),
        ),
        "liquidity_intervention": (
            make_liquidity_intervention_problem(),
            make_liquidity_intervention_problem(complete=False),
        ),
        "portfolio_hedge": (
            make_portfolio_hedge_problem(),
            make_portfolio_hedge_problem(complete=False),
        ),
    }
