"""Checks that the work environment is set up correctly.

If these pass, Python, Java, Spark and Delta Lake are all working.
"""

import sys

import pytest

import lakehouse


def test_python_version_is_supported():
    assert sys.version_info >= (3, 11)


def test_package_is_importable():
    assert lakehouse.__version__ == "0.1.0"


@pytest.mark.spark
def test_delta_table_round_trip(spark, tmp_path):
    """Write a tiny Delta table and read it back."""
    path = str(tmp_path / "trades")
    rows = [("TRD-PWR-000001", 1, 50.0), ("TRD-PWR-000001", 2, 60.0)]
    df = spark.createDataFrame(rows, "trade_id string, trade_version int, volume double")

    df.write.format("delta").save(path)
    result = spark.read.format("delta").load(path)

    assert result.count() == 2
    assert {r.trade_version for r in result.collect()} == {1, 2}
