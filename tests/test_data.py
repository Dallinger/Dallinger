"""Tests for the data module."""

from collections import OrderedDict
import os

import pandas as pd

import dallinger
from dallinger.config import get_config
from dallinger.utils import generate_random_id


class TestData(object):

    data_path = os.path.join(
        "tests",
        "datasets",
        "12eee6c6-f37f-4963-b684-da585acd77f1-data.zip"
    )

    config = get_config()

    def test_connection_to_s3(self):
        conn = dallinger.data._s3_connection()
        assert conn

    def test_user_s3_bucket_first_time(self):
        conn = dallinger.data._s3_connection()
        bucket = dallinger.data.user_s3_bucket(
            canonical_user_id=generate_random_id(),
        )
        assert bucket
        conn.delete_bucket(bucket)

    def test_user_s3_bucket_thrice(self):
        conn = dallinger.data._s3_connection()
        id = generate_random_id()
        for i in range(3):
            bucket = dallinger.data.user_s3_bucket(
                canonical_user_id=id,
            )
            assert bucket
        conn.delete_bucket(bucket)

    def test_user_s3_bucket_no_id_provided(self):
        bucket = dallinger.data.user_s3_bucket()
        assert bucket

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

    def test_tsv_conversion(self):
        data = dallinger.data.Data(self.data_path)
        assert data.networks.tsv[0:3] == "id\t"

    def test_list_conversion(self):
        data = dallinger.data.Data(self.data_path)
        assert type(data.networks.list) is list

    def test_dict_conversion(self):
        data = dallinger.data.Data(self.data_path)
        assert type(data.networks.dict) is OrderedDict

    def test_df_conversion(self):
        data = dallinger.data.Data(self.data_path)
        assert type(data.networks.df) is pd.DataFrame

    def test_data_loading(self):
        data = dallinger.data.load("3b9c2aeb-0eb7-4432-803e-bc437e17b3bb")
        assert data
        assert data.networks.csv
