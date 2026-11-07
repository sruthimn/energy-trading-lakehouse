"""Tests for the reference data generator."""

import pandas as pd
import pytest

from lakehouse.generator.reference import (
    COUNTRIES,
    NAME_STARTS,
    RATINGS,
    generate_books,
    generate_commodities,
    generate_counterparties,
    generate_reference,
    write_reference,
)


def test_same_seed_gives_identical_data():
    first = generate_reference(seed=7)
    second = generate_reference(seed=7)
    pd.testing.assert_frame_equal(first.counterparties, second.counterparties)
    pd.testing.assert_frame_equal(first.books, second.books)
    pd.testing.assert_frame_equal(first.commodities, second.commodities)


def test_different_seed_gives_different_counterparties():
    a = generate_counterparties(seed=1)
    b = generate_counterparties(seed=2)
    assert not a.equals(b)


def test_counterparty_ids_are_unique_and_follow_the_pattern():
    df = generate_counterparties(count=40)
    assert len(df) == 40
    assert df["counterparty_id"].is_unique
    assert df["counterparty_id"].str.fullmatch(r"CP-\d{5}").all()
    assert df["counterparty_id"].iloc[0] == "CP-00001"


def test_counterparty_names_are_unique():
    df = generate_counterparties(count=40)
    assert df["counterparty_name"].is_unique


def test_counterparty_values_are_valid():
    df = generate_counterparties(count=40)
    assert df["credit_rating"].isin([rating for rating, _ in RATINGS]).all()
    assert df["country_of_risk"].isin([code for code, _, _ in COUNTRIES]).all()
    assert (df["credit_limit_gbp"] > 0).all()
    assert df.notna().all().all()


def test_too_many_counterparties_is_rejected():
    with pytest.raises(ValueError):
        generate_counterparties(count=len(NAME_STARTS) + 1)


def test_book_ids_are_unique_and_match_their_desk():
    df = generate_books()
    assert df["book_id"].is_unique
    assert df["book_id"].str.fullmatch(r"BK-[A-Z]+-\d{2}").all()
    # The desk code is part of the book id, for example BK-UKPWR-01 -> UKPWR.
    assert (df["book_id"].str.split("-").str[1] == df["desk_code"]).all()


def test_every_desk_has_at_least_one_book():
    df = generate_books()
    assert set(df["desk_code"]) == {"UKPWR", "UKGAS", "EUGAS", "CRUDE", "CARB"}


def test_commodities_have_a_standard_unit_inside_their_native_units():
    df = generate_commodities()
    assert df["commodity_code"].is_unique
    for row in df.itertuples():
        assert row.standard_unit in row.native_units.split("|")


def test_every_commodity_group_has_a_standard_unit():
    df = generate_commodities()
    units = dict(zip(df["commodity_group"], df["standard_unit"], strict=False))
    assert units == {
        "POWER": "MWh",
        "GAS": "therm",
        "CRUDE": "bbl",
        "EMISSIONS": "tCO2e",
    }


def test_write_reference_creates_three_csv_files(tmp_path):
    paths = write_reference(generate_reference(), tmp_path / "ref")
    assert sorted(p.name for p in paths) == [
        "books.csv",
        "commodities.csv",
        "counterparties.csv",
    ]
    assert len(pd.read_csv(tmp_path / "ref" / "counterparties.csv")) == 40
