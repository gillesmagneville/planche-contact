# -*- coding: utf-8 -*-
"""
Tests of Config.__post_init__() - backward-compatible synchronisation between
the historical "simple" settings (page_format, num_per_sheet) and the new
Profile (profile.layout.page_format/per_page), specification §2/§8.
"""
from pathlib import Path

from portfolio.config import Config
from portfolio.presentation import Profile, LayoutSettings


def test_default_profile_matches_default_legacy_fields():
    """With no explicit setting, the default Profile must already match
    Config's historical defaults (A4/12)."""
    config = Config(input_dir=Path("in"), output_dir=Path("out"))
    assert config.profile.layout.page_format == "A4"
    assert config.profile.layout.per_page == 12


def test_explicit_legacy_fields_sync_into_the_default_profile():
    """Actual current case (CLI/graphical interface, no Profile supplied):
    explicit page_format/num_per_sheet must be reflected in the internal
    Profile, otherwise the layout engine would compute a geometry
    inconsistent with what the user asked for."""
    config = Config(
        input_dir=Path("in"), output_dir=Path("out"),
        page_format="A3", num_per_sheet=24,
    )
    assert config.profile.layout.page_format == "A3"
    assert config.profile.layout.per_page == 24


def test_explicit_custom_profile_is_not_clobbered_by_default_legacy_fields():
    """An explicit Profile (e.g. --profile, a later step) whose
    format/number per sheet ALREADY differs from the LayoutSettings defaults
    must not be overwritten by Config's defaults (page_format="A4",
    num_per_sheet=12) when the caller has not explicitly changed them."""
    custom_profile = Profile(layout=LayoutSettings(page_format="A2", per_page=48))
    config = Config(input_dir=Path("in"), output_dir=Path("out"), profile=custom_profile)

    assert config.profile.layout.page_format == "A2"
    assert config.profile.layout.per_page == 48


def test_explicit_legacy_fields_do_not_override_an_already_customized_profile():
    """Clarification of the same behaviour: if the supplied Profile ALREADY
    has a format different from the LayoutSettings defaults, a legacy
    page_format left at its default value ("A4") must not take precedence
    over the more specific Profile (see Config.__post_init__ for the
    explicitly documented limit of this heuristic)."""
    custom_profile = Profile(layout=LayoutSettings(page_format="A2"))
    config = Config(
        input_dir=Path("in"), output_dir=Path("out"),
        page_format="A4",  # Config's default value, hence not "explicit" in the sense of this heuristic
        profile=custom_profile,
    )
    assert config.profile.layout.page_format == "A2"
