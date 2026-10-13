"""Salary-model features that a resume (plus the user's choices) can provide (Phase 5.2).

The SAME build_features() turns training postings (salary_model.py) and, in
Phase 6, a resume + the user's picks (resume_features.py) into model inputs, so
training and serving can't drift apart. Features: target role, seniority, state,
remote, each common skill yes/no, and skill_count. Nothing a resume can't give
(employer, publisher, topic).

Kept free of PyTorch: the salary model must never share a process with it (OpenMP
clash, see CLAUDE.md 5.6).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

UNKNOWN = "unknown"
# A skill becomes a feature once this many training postings mention it; rarer
# skills can't be learned from ~270 salaried postings.
MIN_SKILL_POSTINGS = 10


@dataclass(frozen=True)
class Profile:
    """One posting (training) or one resume + the user's choices (serving)."""

    role: str
    seniority: str
    state: str | None
    remote: bool
    skills: frozenset[str]  # every dictionary skill found, common or not


@dataclass(frozen=True)
class FeatureSpec:
    """The categories and skills the model was trained with, in column order."""

    roles: tuple[str, ...]
    seniorities: tuple[str, ...]
    states: tuple[str, ...]
    skills: tuple[str, ...]

    @property
    def names(self) -> list[str]:
        """Feature column names, in the order build_features produces them."""
        return (
            [f"role={r}" for r in self.roles]
            + [f"seniority={s}" for s in self.seniorities]
            + [f"state={s}" for s in self.states]
            + ["remote"]
            + [f"skill={s}" for s in self.skills]
            + ["skill_count"]
        )

    def to_dict(self) -> dict[str, list[str]]:
        """JSON-ready form (exported next to the model for the app)."""
        return {
            "roles": list(self.roles),
            "seniorities": list(self.seniorities),
            "states": list(self.states),
            "skills": list(self.skills),
        }

    @classmethod
    def from_dict(cls, data: dict[str, list[str]]) -> FeatureSpec:
        """Rebuild a spec from to_dict() output (e.g. read back from S3).

        Args:
            data: Output of to_dict (possibly via JSON).

        Returns:
            The FeatureSpec.
        """
        return cls(
            tuple(data["roles"]), tuple(data["seniorities"]), tuple(data["states"]), tuple(data["skills"])
        )


def fit_spec(profiles: Sequence[Profile]) -> FeatureSpec:
    """Choose the feature columns from training profiles.

    Args:
        profiles: Training postings.

    Returns:
        Categories seen in training (plus 'unknown' for seniority and state, so
        unseen values have somewhere to go) and the skills mentioned by at least
        MIN_SKILL_POSTINGS profiles.
    """
    skill_counts = Counter(skill for p in profiles for skill in p.skills)
    return FeatureSpec(
        roles=tuple(sorted({p.role for p in profiles})),
        seniorities=tuple(sorted({p.seniority for p in profiles} | {UNKNOWN})),
        states=tuple(sorted({p.state or UNKNOWN for p in profiles} | {UNKNOWN})),
        skills=tuple(sorted(s for s, n in skill_counts.items() if n >= MIN_SKILL_POSTINGS)),
    )


def build_features(profiles: Sequence[Profile], spec: FeatureSpec) -> pd.DataFrame:
    """Turn profiles into the model's input table.

    A seniority or state the model never saw counts as 'unknown' (e.g. a resume
    user in Florida when training only had five states).

    Args:
        profiles: Postings or resumes.
        spec: Columns chosen at training time (fit_spec).

    Returns:
        One row per profile, columns spec.names, float32 values.

    Raises:
        ValueError: If a profile's role isn't one the model was trained on.
    """
    rows = []
    for p in profiles:
        if p.role not in spec.roles:
            raise ValueError(f"Unknown role {p.role!r}; the model knows {list(spec.roles)}")
        seniority = p.seniority if p.seniority in spec.seniorities else UNKNOWN
        state = p.state if p.state in spec.states else UNKNOWN
        rows.append(
            [float(r == p.role) for r in spec.roles]
            + [float(s == seniority) for s in spec.seniorities]
            + [float(s == state) for s in spec.states]
            + [float(p.remote)]
            + [float(s in p.skills) for s in spec.skills]
            + [float(len(p.skills))]
        )
    return pd.DataFrame(rows, columns=spec.names, dtype="float32")

