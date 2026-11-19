"""Each language the integration is translated into, with the words in a name that say what an appliance is, and the
texts kept in code by language"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant

from custom_components.appliance_autonotify.const import (
    ACTION_TITLES,
    MAINTENANCE_ACTION_TITLES,
    MAINTENANCE_MESSAGES,
    MAINTENANCE_NAMES,
    STUCK_MESSAGES,
)
from custom_components.appliance_autonotify.words import async_load_words, name_type

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "appliance_autonotify" / "translations"
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob("*.json"))


@pytest.mark.parametrize(
    ("language", "name", "kind"),
    [
        ("de", "Waschmaschine Keller", "washer"),
        ("de", "Wäschetrockner", "dryer"),
        ("de", "Geschirrspüler Küche", "dishwasher"),
        ("nl", "Vaatwasser keuken", "dishwasher"),
        ("nl", "Wasmachine", "washer"),
        ("es", "Lavadora secadora", "washer_dryer"),
        ("es", "Lavavajillas", "dishwasher"),
        ("fr", "Lave-linge buanderie", "washer"),
        ("fr", "Sèche-linge", "dryer"),
        ("pl", "Pralka łazienka", "washer"),
        ("pl", "Zmywarka", "dishwasher"),
        ("zh-Hans", "厨房洗碗机", "dishwasher"),
        ("zh-Hans", "洗衣机", "washer"),
        ("hi", "वॉशिंग मशीन", "washer"),
        ("hi", "डिशवॉशर", "dishwasher"),
    ],
)
async def test_appliance_named_in_the_language_of_home_assistant(
    hass: HomeAssistant, language: str, name: str, kind: str
) -> None:
    hass.config.language = language
    await async_load_words(hass)
    assert name_type(hass, name) == kind
    # and in English, whatever the language
    assert name_type(hass, "Dishwasher") == "dishwasher"


def test_texts_in_code_for_every_language() -> None:
    """A table in code for each language with translations, by the language without its script or region, as looked
    up from Home Assistant's"""
    languages = {language.split("-")[0] for language in LANGUAGES}
    for table in (ACTION_TITLES, MAINTENANCE_ACTION_TITLES, MAINTENANCE_NAMES, MAINTENANCE_MESSAGES, STUCK_MESSAGES):
        assert set(table) == languages
        for texts in table.values():
            if isinstance(texts, dict):
                assert set(texts) == set(table["en"])


def test_maintenance_names_match_the_settings() -> None:
    for language in LANGUAGES:
        translations = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
        settings = translations["options"]["step"]["settings"]["sections"]["maintenance_items"]["data"]
        names = MAINTENANCE_NAMES[language.split("-")[0]]
        assert {key.removeprefix("maintenance_"): name for key, name in settings.items()} == names
