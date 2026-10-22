"""Explicit legacy-distance and configurable link-budget radio models.

This module is an engineering abstraction. It does not implement a full
3GPP/IMT-2030 channel, SINR, interference, or calibrated equipment model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path
import random
import tomllib
from typing import Protocol


SPEED_OF_LIGHT_M_S = 299_792_458.0


@dataclass(frozen=True)
class LinkAssessment:
    profile_id: str
    feasible: bool
    distance_km: float
    path_loss_db: float | None
    received_power_dbm: float | None
    margin_db: float | None
    failure_reason: str | None


class RadioLinkModel(Protocol):
    model_id: str

    def assess(
        self,
        profile_id: str,
        distance_km: float,
        max_distance_km: float,
        source_id: str,
        target_id: str,
        *,
        tolerance_km: float = 0.0,
    ) -> LinkAssessment: ...


@dataclass(frozen=True)
class LinkBudgetProfile:
    """One directional link-budget profile; values carry explicit units."""

    carrier_frequency_mhz: float
    tx_power_dbm: float
    tx_antenna_gain_dbi: float
    rx_antenna_gain_dbi: float
    other_losses_db: float
    reference_distance_m: float
    path_loss_exponent: float
    rx_sensitivity_dbm: float
    fade_margin_db: float
    shadowing_sigma_db: float = 0.0
    obstruction_loss_db: float = 0.0

    def validate(self) -> None:
        values = asdict(self)
        if not all(math.isfinite(float(value)) for value in values.values()):
            raise ValueError("link profile values must be finite")
        if self.carrier_frequency_mhz <= 0:
            raise ValueError("carrier_frequency_mhz must be positive")
        if self.reference_distance_m <= 0:
            raise ValueError("reference_distance_m must be positive")
        if self.path_loss_exponent <= 0:
            raise ValueError("path_loss_exponent must be positive")
        if min(self.other_losses_db, self.fade_margin_db, self.shadowing_sigma_db, self.obstruction_loss_db) < 0:
            raise ValueError("other loss, fade margin, shadowing sigma and obstruction loss must be non-negative")
        if not -200 <= self.rx_sensitivity_dbm <= 0:
            raise ValueError("rx_sensitivity_dbm must be within [-200, 0]")


@dataclass(frozen=True)
class LinkBudgetModelConfig:
    version: str
    base_access: LinkBudgetProfile
    uav_access: LinkBudgetProfile
    backhaul: LinkBudgetProfile
    shadowing_model: str = "static_per_link_per_run"

    def validate(self) -> None:
        if self.version != "link_budget_v1":
            raise ValueError("link-budget configuration version must be link_budget_v1")
        if self.shadowing_model != "static_per_link_per_run":
            raise ValueError("only static_per_link_per_run shadowing is implemented")
        for profile in (self.base_access, self.uav_access, self.backhaul):
            profile.validate()

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "shadowing_model": self.shadowing_model,
            "base_access": asdict(self.base_access),
            "uav_access": asdict(self.uav_access),
            "backhaul": asdict(self.backhaul),
        }


def load_link_budget_config(path: str | Path) -> LinkBudgetModelConfig:
    """Load and validate the independent Phase 14 link-budget TOML."""
    with Path(path).open("rb") as stream:
        raw = tomllib.load(stream)
    model = raw["model"]

    def profile(name: str) -> LinkBudgetProfile:
        values = raw[name]
        result = LinkBudgetProfile(
            carrier_frequency_mhz=float(values["carrier_frequency_mhz"]),
            tx_power_dbm=float(values["tx_power_dbm"]),
            tx_antenna_gain_dbi=float(values["tx_antenna_gain_dbi"]),
            rx_antenna_gain_dbi=float(values["rx_antenna_gain_dbi"]),
            other_losses_db=float(values["other_losses_db"]),
            reference_distance_m=float(values["reference_distance_m"]),
            path_loss_exponent=float(values["path_loss_exponent"]),
            rx_sensitivity_dbm=float(values["rx_sensitivity_dbm"]),
            fade_margin_db=float(values["fade_margin_db"]),
            shadowing_sigma_db=float(values.get("shadowing_sigma_db", 0.0)),
            obstruction_loss_db=float(values.get("obstruction_loss_db", 0.0)),
        )
        result.validate()
        return result

    result = LinkBudgetModelConfig(
        version=str(model["version"]),
        shadowing_model=str(model.get("shadowing_model", "static_per_link_per_run")),
        base_access=profile("base_access"),
        uav_access=profile("uav_access"),
        backhaul=profile("backhaul"),
    )
    result.validate()
    return result


def free_space_path_loss_db(carrier_frequency_mhz: float, distance_m: float) -> float:
    """Free-space path loss in dB, with frequency in MHz and distance in m."""
    if not math.isfinite(carrier_frequency_mhz) or carrier_frequency_mhz <= 0:
        raise ValueError("carrier_frequency_mhz must be finite and positive")
    if not math.isfinite(distance_m) or distance_m <= 0:
        raise ValueError("distance_m must be finite and positive")
    frequency_hz = carrier_frequency_mhz * 1_000_000.0
    return 20.0 * math.log10(4.0 * math.pi * frequency_hz * distance_m / SPEED_OF_LIGHT_M_S)


class LegacyDistanceModel:
    """Historical hard distance threshold; no radio-power computation."""

    model_id = "legacy_distance"

    def assess(
        self,
        profile_id: str,
        distance_km: float,
        max_distance_km: float,
        source_id: str,
        target_id: str,
        *,
        tolerance_km: float = 0.0,
    ) -> LinkAssessment:
        _validate_distance(distance_km, max_distance_km, tolerance_km)
        feasible = distance_km <= max_distance_km + tolerance_km
        return LinkAssessment(
            profile_id=profile_id,
            feasible=feasible,
            distance_km=distance_km,
            path_loss_db=None,
            received_power_dbm=None,
            margin_db=None,
            failure_reason=None if feasible else "distance_limit_exceeded",
        )


class LinkBudgetV1:
    """Log-distance link budget with deterministic, keyed static shadowing."""

    model_id = "link_budget_v1"

    def __init__(self, config: LinkBudgetModelConfig, seed: int):
        config.validate()
        if seed < 0:
            raise ValueError("seed must be non-negative")
        self.config = config
        self.seed = int(seed)
        self._profiles = {
            "base_access": config.base_access,
            "uav_access": config.uav_access,
            "backhaul": config.backhaul,
        }

    def _shadowing_db(self, profile_id: str, source_id: str, target_id: str, sigma_db: float) -> float:
        if sigma_db == 0:
            return 0.0
        key = f"{self.seed}\0{profile_id}\0{source_id}\0{target_id}".encode("utf-8")
        keyed_seed = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")
        return random.Random(keyed_seed).gauss(0.0, sigma_db)

    def path_loss_db(self, profile_id: str, distance_km: float, source_id: str, target_id: str) -> float:
        profile = self._profile(profile_id)
        if not math.isfinite(distance_km) or distance_km < 0:
            raise ValueError("distance_km must be finite and non-negative")
        distance_m = max(distance_km * 1000.0, profile.reference_distance_m)
        reference_loss_db = free_space_path_loss_db(
            profile.carrier_frequency_mhz, profile.reference_distance_m
        )
        distance_loss_db = 10.0 * profile.path_loss_exponent * math.log10(
            distance_m / profile.reference_distance_m
        )
        return (
            reference_loss_db
            + distance_loss_db
            + self._shadowing_db(profile_id, source_id, target_id, profile.shadowing_sigma_db)
            + profile.obstruction_loss_db
        )

    def assess(
        self,
        profile_id: str,
        distance_km: float,
        max_distance_km: float,
        source_id: str,
        target_id: str,
        *,
        tolerance_km: float = 0.0,
    ) -> LinkAssessment:
        _validate_distance(distance_km, max_distance_km, tolerance_km)
        profile = self._profile(profile_id)
        in_range = distance_km <= max_distance_km + tolerance_km
        path_loss = self.path_loss_db(profile_id, distance_km, source_id, target_id)
        received = (
            profile.tx_power_dbm
            + profile.tx_antenna_gain_dbi
            + profile.rx_antenna_gain_dbi
            - profile.other_losses_db
            - path_loss
        )
        margin = received - profile.rx_sensitivity_dbm - profile.fade_margin_db
        feasible = in_range and margin >= -1e-12
        reason = None
        if not in_range:
            reason = "distance_limit_exceeded"
        elif margin < -1e-12:
            reason = "received_power_below_sensitivity_with_fade_margin"
        return LinkAssessment(
            profile_id=profile_id,
            feasible=feasible,
            distance_km=distance_km,
            path_loss_db=path_loss,
            received_power_dbm=received,
            margin_db=margin,
            failure_reason=reason,
        )

    def _profile(self, profile_id: str) -> LinkBudgetProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as error:
            raise ValueError(f"unknown radio link profile: {profile_id}") from error


_LEGACY_DISTANCE_MODEL = LegacyDistanceModel()


def assess_link(
    model: RadioLinkModel | None,
    profile_id: str,
    distance_km: float,
    max_distance_km: float,
    source_id: str,
    target_id: str,
    *,
    tolerance_km: float = 0.0,
) -> LinkAssessment:
    """Use the explicit model when selected; default to historical distance logic."""
    selected = model if model is not None else _LEGACY_DISTANCE_MODEL
    return selected.assess(
        profile_id,
        distance_km,
        max_distance_km,
        source_id,
        target_id,
        tolerance_km=tolerance_km,
    )


def _validate_distance(distance_km: float, max_distance_km: float, tolerance_km: float) -> None:
    if not math.isfinite(distance_km) or distance_km < 0:
        raise ValueError("distance_km must be finite and non-negative")
    if not math.isfinite(max_distance_km) or max_distance_km <= 0:
        raise ValueError("max_distance_km must be finite and positive")
    if not math.isfinite(tolerance_km) or tolerance_km < 0:
        raise ValueError("tolerance_km must be finite and non-negative")
