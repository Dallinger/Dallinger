"""Tests for the data module."""

import os

import dallinger


class TestData(object):

    data_path = os.path.join(
        "tests",
        "datasets",
        "12eee6c6-f37f-4963-b684-da585acd77f1-data.zip"
    )

    def test_dataset_loading(self):
        """Load a dataset."""
        dallinger.data.Data(self.data_path)

    def test_dataframe_conversion(self):
        data = dallinger.data.Data(self.data_path)
        assert data.networks.df.shape == (1, 13)
