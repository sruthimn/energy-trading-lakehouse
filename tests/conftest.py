import pytest
from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    """A small local Spark session with Delta Lake switched on.

    Used by tests that need Spark. It starts once and is shared by all tests.
    """
    builder = (
        SparkSession.builder.master("local[2]")
        .appName("lakehouse-tests")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
    )
    session = configure_spark_with_delta_pip(builder).getOrCreate()
    yield session
    session.stop()
