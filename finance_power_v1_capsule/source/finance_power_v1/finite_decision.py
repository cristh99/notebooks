from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence

from logic_power_v10 import ActiveDiscoveryProblem, Experiment


@dataclass(frozen=True)
class FinancialWorld:
    """A finite financial state carrying a binary decision property."""

    world_id: str
    decision: bool
    prior: Fraction
    attributes: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.world_id:
            raise ValueError("world_id must be non-empty")
        if self.prior <= 0:
            raise ValueError("prior must be positive")
        if not self.attributes:
            raise ValueError("attributes must be non-empty")
        if any(not key for key in self.attributes):
            raise ValueError("attribute names must be non-empty")


@dataclass(frozen=True)
class EvidenceAcquisition:
    """An admissible observation defined over declared world attributes."""

    name: str
    cost: Fraction
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("evidence name must be non-empty")
        if self.cost <= 0:
            raise ValueError("evidence cost must be positive")
        if not self.fields:
            raise ValueError("at least one evidence field is required")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("evidence fields must be unique")

    def observe(self, world: FinancialWorld) -> str:
        missing = set(self.fields) - set(world.attributes)
        if missing:
            raise ValueError(
                f"world {world.world_id} lacks fields {sorted(missing)}"
            )
        return "|".join(world.attributes[field] for field in self.fields)


def compile_financial_decision(
    worlds: Sequence[FinancialWorld],
    evidence: Sequence[EvidenceAcquisition],
) -> ActiveDiscoveryProblem:
    """Compile a generic finite financial decision into Logic Power v10."""
    world_ids = [world.world_id for world in worlds]
    if not world_ids:
        raise ValueError("at least one financial world is required")
    if len(set(world_ids)) != len(world_ids):
        raise ValueError("world identifiers must be unique")

    evidence_names = [item.name for item in evidence]
    if len(set(evidence_names)) != len(evidence_names):
        raise ValueError("evidence names must be unique")

    return ActiveDiscoveryProblem(
        hypotheses=tuple(world_ids),
        property_values={
            world.world_id: world.decision
            for world in worlds
        },
        experiments=tuple(
            Experiment(
                name=item.name,
                cost=item.cost,
                observations={
                    world.world_id: item.observe(world)
                    for world in worlds
                },
            )
            for item in evidence
        ),
        prior={
            world.world_id: world.prior
            for world in worlds
        },
    )
