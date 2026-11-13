"""What's known of each integration an appliance can come through.

Integrations are taken to behave alike for the same type of appliance, so an appliance of an integration that isn't
known here is still found and watched by what its entities do. A profile is only for where an integration names
things its own way, or has more to it than others, and to say whether it's been tried on a real appliance yet."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

from .const import APPLIANCE_TYPES, KEY_TYPE_PREFIXES, ROLE_KEY_PREFIXES, ROLE_KEYS

# supported once it's been seen to work with a real appliance in a home, beta when written from its source alone
type Status = Literal["supported", "beta"]
STATUS_SUPPORTED: Final[Status] = "supported"
STATUS_BETA: Final[Status] = "beta"


@dataclass(frozen=True, eq=False)
class PlatformProfile:
    """An integration, by its domain, as the platform of its entities, None for any not known here"""

    platform: str | None
    status: Status = STATUS_SUPPORTED
    # what an entity does, by the translation key the integration gives it, ahead of the ones of every integration
    role_keys: Mapping[str, str] = field(default_factory=dict)
    role_key_prefixes: Mapping[str, str] = field(default_factory=dict)
    # the type of appliance, by how the integration names its programs, or else its entities
    program_types: Mapping[str, str] = field(default_factory=dict)
    key_types: Mapping[str, str] = field(default_factory=dict)
    # where to tell of how it went, for one in beta
    issue_url: str | None = None

    @property
    def beta(self) -> bool:
        return self.status == STATUS_BETA

    def role_key(self, translation_key: str | None) -> str | None:
        """What an entity does, as the translation key Home Connect gives an entity that does the same"""
        if translation_key is None:
            return None
        if translation_key in self.role_keys:
            return self.role_keys[translation_key]
        if role := _by_prefix(self.role_key_prefixes, translation_key):
            return role
        if translation_key in ROLE_KEYS:
            return ROLE_KEYS[translation_key]
        return _by_prefix(ROLE_KEY_PREFIXES, translation_key) or translation_key

    def appliance_type(self, programs: Iterable[str], translation_keys: Iterable[str]) -> str | None:
        """The type of appliance by its programs, or failing that, for an integration with several types, its
        entities, by this integration's names before those of every integration"""
        programs = list(programs)
        translation_keys = list(translation_keys)
        for prefixes, names in (
            (self.program_types, programs),
            (APPLIANCE_TYPES, programs),
            (self.key_types, translation_keys),
            (KEY_TYPE_PREFIXES, translation_keys),
        ):
            if kind := next((kind for prefix, kind in prefixes.items() if any(n.startswith(prefix) for n in names)), None):
                return kind
        return None


def _by_prefix(prefixes: Mapping[str, str], key: str) -> str | None:
    return next((role for prefix, role in prefixes.items() if key.startswith(prefix)), None)


GENERIC: Final[PlatformProfile] = PlatformProfile(None)

PROFILES: Final[dict[str, PlatformProfile]] = {
    profile.platform: profile
    for profile in (
        PlatformProfile("home_connect"),
        PlatformProfile("smartthings"),
        PlatformProfile("localthings"),
    )
    if profile.platform is not None
}


def profile_for(platform: str | None) -> PlatformProfile:
    """The profile of an integration, or the one for any integration not known here"""
    return PROFILES.get(platform or "", GENERIC)
