"""Tests for the data module."""

import os

import dallinger
from dallinger.config import get_config


class TestData(object):

    data_path = os.path.join(
        "tests",
        "datasets",
        "12eee6c6-f37f-4963-b684-da585acd77f1-data.zip"
    )

    config = get_config()

    def test_dataset_creation(self):
        """Load a dataset."""
        dallinger.data.Data(self.data_path)

    def test_conversions(self):
        data = dallinger.data.Data(self.data_path)
        assert data.networks.csv
        assert data.networks.dict
        assert data.networks.df.shape
        assert data.networks.html
        assert data.networks.latex
        assert data.networks.list
        assert data.networks.ods
        assert data.networks.tsv
        assert data.networks.xls
        assert data.networks.xlsx
        assert data.networks.yaml

    def test_dataframe_conversion(self):
        data = dallinger.data.Data(self.data_path)
        assert data.networks.df.shape == (1, 13)

    def test_csv_conversion(self):
        data = dallinger.data.Data(self.data_path)
        assert data.networks.csv[0:3] == "id,"

    def test_data_loading(self):
        data = dallinger.data.load("3b9c2aeb-0eb7-4432-803e-bc437e17b3bb")
        assert data
        assert data.csv
