"""Tests for the data module."""

from collections import OrderedDict
import csv
from datetime import datetime
import io
import os
import requests
import tempfile
import uuid
import shutil

import pandas as pd
import psycopg2
import pytest

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

    def test_local_data_loading(self):
        local_data_id = "77777-77777-77777-77777"
        dallinger.data.export(local_data_id, local=True)
        data = dallinger.data.load(local_data_id)
        assert data
        assert data.networks.csv

    def test_export_of_nonexistent_database(self):
        nonexistent_local_db = str(uuid.uuid4())
        with pytest.raises(psycopg2.OperationalError):
            dallinger.data.copy_local_to_csv(nonexistent_local_db, "")

    def test_export_of_dallinger_database(self):
        export_dir = tempfile.mkdtemp()
        dallinger.data.copy_local_to_csv("dallinger", export_dir)
        assert os.path.isfile(os.path.join(export_dir, "network.csv"))

    def test_exported_database_includes_headers(self):
        export_dir = tempfile.mkdtemp()
        dallinger.data.copy_local_to_csv("dallinger", export_dir)
        network_table_path = os.path.join(export_dir, "network.csv")
        assert os.path.isfile(network_table_path)
        with open(network_table_path, 'rb') as f:
            reader = csv.reader(f, delimiter=',')
            header = next(reader)
            assert "creation_time" in header

    def test_export(self):
        dallinger.data.export("12345-12345-12345-12345", local=True)
        assert os.path.isfile("data/12345-12345-12345-12345-data.zip")
        shutil.rmtree('data')

    def test_export_directory_format(self):
        from zipfile import ZipFile
        path = dallinger.data.export("12345-12345-12345-12345", local=True)
        archive = ZipFile(path)
        assert 'data/info.csv' in archive.namelist()

    def test_export_compatible_with_data(self):
        path = dallinger.data.export("12345-12345-12345-12345", local=True)
        assert dallinger.data.Data(path)

    def test_register_id(self):
        new_uuid = "12345-12345-12345-12345"
        url = dallinger.data.register(new_uuid, 'http://original-url.com/value')

        # The registration creates a new file in the dallinger-registrations bucket
        assert url.startswith('https://dallinger-registrations.')
        assert new_uuid in url

        # These files should be inaccessible to make it impossible to use the bucket
        # as a file repository
        res = requests.get(url)
        assert res.status_code == 403

        # We should be able to check that the UUID is registered
        assert dallinger.data.is_registered(new_uuid) is True
        assert dallinger.data.is_registered('bogus-uuid-value') is False


class TestImport(object):

    @pytest.fixture
    def zip_path(self):
        return os.path.join(
            "tests",
            "datasets",
            "test_export.zip"
        )

    def test_ingest_to_model(self, db_session):
        data = u'''id,creation_time,property1,property2,property3,property4,property5,failed,time_of_death,type,max_size,full,role
1,2001-01-01 09:46:40.133536,,,,,,f,,fully-connected,4,f,experiment'''
        f = io.StringIO(initial_value=data)

        dallinger.data.ingest_to_model(f, dallinger.models.Network)

        networks = dallinger.models.Network.query.all()
        assert len(networks) == 1
        network = networks[0]
        assert network.type == 'fully-connected'
        assert network.creation_time == datetime(2001, 1, 1, 9, 46, 40, 133536)
        assert network.role == 'experiment'

    def test_ingest_to_model_allows_subsequent_insert(self, db_session):
        data = u'''id,creation_time,property1,property2,property3,property4,property5,failed,time_of_death,type,max_size,full,role
1,2001-01-01 09:46:40.133536,,,,,,f,,fully-connected,4,f,experiment'''
        f = io.StringIO(initial_value=data)

        dallinger.data.ingest_to_model(f, dallinger.models.Network)

        db_session.add(dallinger.models.Network())
        db_session.flush()
        db_session.commit()

        networks = dallinger.models.Network.query.all()
        assert networks[1].id == 2

    def test_ingest_zip_recreates_network(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)

        networks = dallinger.models.Network.query.all()
        assert len(networks) == 1
        assert networks[0].type == 'chain'

    def test_ingest_zip_recreates_participants(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)

        participants = dallinger.models.Participant.query.all()
        assert len(participants) == 4
        for p in participants:
            assert p.status == 'approved'

    def test_ingest_zip_recreates_nodes(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)
        assert len(dallinger.models.Node.query.all()) == 5

    def test_ingest_zip_recreates_infos(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)

        infos = dallinger.models.Info.query.all()
        assert len(infos) == 5
        for info in infos:
            assert info.contents.startswith(u'One night two young men')

    def test_ingest_zip_recreates_notifications(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)
        assert len(dallinger.models.Notification.query.all()) == 8

    def test_ingest_zip_recreates_questions(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)

        model = dallinger.models.Question
        p1_questions = model.query.filter_by(participant_id=1).all()
        for q in p1_questions:
            if q.response:
                assert q.response == u'5'

    def test_ingest_zip_recreates_vectors(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)
        assert len(dallinger.models.Vector.query.all()) == 4

    def test_ingest_zip_recreates_transmissions(self, db_session, zip_path):
        dallinger.data.ingest_zip(zip_path)
        assert len(dallinger.models.Transmission.query.all()) == 4
