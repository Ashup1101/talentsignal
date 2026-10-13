"""Tests for src/ml/features.py (salary-model inputs shared by training and the app)."""

from __future__ import annotations

import json

import pytest

from src.ml import features
from src.ml.features import UNKNOWN, FeatureSpec, Profile


def _profile(role: str = "data engineer", seniority: str = "senior", state: str | None = "NY",
             remote: bool = False, skills: tuple[str, ...] = ()) -> Profile:
    return Profile(role, seniority, state, remote, frozenset(skills))


def test_fit_spec_keeps_common_skills_and_adds_unknown() -> None:
    profiles = (
        [_profile(skills=("SQL", "Python")) for _ in range(features.MIN_SKILL_POSTINGS)]
        + [_profile(role="data analyst", seniority="junior", state=None, skills=("Excel",))]
    )

    spec = features.fit_spec(profiles)

    assert spec.roles == ("data analyst", "data engineer")
    assert spec.seniorities == ("junior", "senior", UNKNOWN)
    assert spec.states == ("NY", UNKNOWN)
    assert spec.skills == ("Python", "SQL")  # Excel: 1 posting < MIN_SKILL_POSTINGS


def test_build_features_one_hot_and_counts() -> None:
    spec = FeatureSpec(("data analyst", "data engineer"), ("senior", UNKNOWN), ("NY", UNKNOWN), ("Python", "SQL"))

    row = features.build_features([_profile(remote=True, skills=("SQL", "Rust"))], spec).iloc[0].to_dict()

    assert row == {
        "role=data analyst": 0.0, "role=data engineer": 1.0,
        "seniority=senior": 1.0, f"seniority={UNKNOWN}": 0.0,
        "state=NY": 1.0, f"state={UNKNOWN}": 0.0,
        "remote": 1.0,
        "skill=Python": 0.0, "skill=SQL": 1.0,
        "skill_count": 2.0,  # Rust isn't a feature but still counts
    }


def test_unseen_state_and_seniority_become_unknown() -> None:
    spec = FeatureSpec(("data engineer",), ("senior", UNKNOWN), ("NY", UNKNOWN), ())

    row = features.build_features([_profile(seniority="intern", state="FL")], spec).iloc[0]

    assert row[f"seniority={UNKNOWN}"] == 1.0 and row[f"state={UNKNOWN}"] == 1.0
    assert row["seniority=senior"] == 0.0 and row["state=NY"] == 0.0


def test_unknown_role_is_rejected() -> None:
    spec = FeatureSpec(("data engineer",), (UNKNOWN,), (UNKNOWN,), ())

    with pytest.raises(ValueError, match="Unknown role 'chef'"):
        features.build_features([_profile(role="chef")], spec)


def test_spec_round_trips_through_json() -> None:
    spec = FeatureSpec(("a",), ("senior", UNKNOWN), ("NY", UNKNOWN), ("SQL",))

    assert FeatureSpec.from_dict(json.loads(json.dumps(spec.to_dict()))) == spec
