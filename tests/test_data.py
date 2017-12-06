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
from zipfile import ZipFile

import pandas as pd
import psycopg2
import pytest

import dallinger
from dallinger.config import get_config
from dallinger.utils import generate_random_id


@pytest.fixture
def zip_path():
    return os.path.join(
        "tests",
        "datasets",
        "test_export.zip"
    )


class TestData(object):

    @pytest.fixture
    def cleanup(self):
        yield
        shutil.rmtree('data')

    @pytest.fixture
    def export(self, cleanup):
        path = dallinger.data.export("12345-12345-12345-12345", local=True)
        return path

    data_path = os.path.join(
        "tests",
        "datasets",
        "12eee6c6-f37f-4963-b684-da585acd77f1-data.zip"
    )

    config = get_config()

    bartlett_export = os.path.join(
        "tests",
        "datasets",
        "bartlett_bots.zip"
    )

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

    def test_export(self, export):
        assert os.path.isfile("data/12345-12345-12345-12345-data.zip")

    def test_export_directory_format(self, export):
        archive = ZipFile(export)
        assert 'data/info.csv' in archive.namelist()

    def test_export_compatible_with_data(self, export):
        assert dallinger.data.Data(export)

    def test_scrub_pii(self):
        path_to_data = os.path.join("tests", "datasets", "pii")
        dallinger.data._scrub_participant_table(path_to_data)
        with open(os.path.join(path_to_data, "participant.csv"), 'rb') as f:
            reader = csv.reader(f, delimiter=',')
            next(reader)  # Skip the header
            for row in reader:
                assert "PII" not in row

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

    def test_scrub_pii_preserves_participants(self, db_session, zip_path, cleanup):
        dallinger.data.ingest_zip(zip_path)
        assert len(dallinger.models.Participant.query.all()) == 4
        path = dallinger.data.export('test_export', local=True, scrub_pii=True)
        p_file = ZipFile(path).open('data/participant.csv')
        assert len(p_file.readlines()) == 5  # 4 Participants + header row

    def test_copy_local_to_csv_includes_participant_data(self, db_session):
        dallinger.data.ingest_zip(self.bartlett_export)
        export_dir = tempfile.mkdtemp()
        dallinger.data.copy_local_to_csv("dallinger", export_dir, scrub_pii=False)
        participant_table_path = os.path.join(export_dir, "participant.csv")
        assert os.path.isfile(participant_table_path)
        with open(participant_table_path, 'rb') as f:
            reader = csv.reader(f, delimiter=',')
            header = next(reader)
            row1 = next(reader)
            assert row1[header.index("worker_id")] == "SM6DMD"

    def test_copy_local_to_csv_includes_scrubbed_participant_data(self, db_session):
        dallinger.data.ingest_zip(self.bartlett_export)
        export_dir = tempfile.mkdtemp()
        dallinger.data.copy_local_to_csv("dallinger", export_dir, scrub_pii=True)
        participant_table_path = os.path.join(export_dir, "participant.csv")
        assert os.path.isfile(participant_table_path)
        with open(participant_table_path, 'rb') as f:
            reader = csv.reader(f, delimiter=',')
            header = next(reader)
            row1 = next(reader)
            assert row1[header.index("worker_id")] == "1"


class TestImport(object):

    @pytest.fixture
    def network_file(self):
        data = u'''id,creation_time,property1,property2,property3,property4,property5,failed,time_of_death,type,max_size,full,role
1,2001-01-01 09:46:40.133536,,,,,,f,,fully-connected,4,f,experiment'''
        f = io.StringIO(initial_value=data)
        return f

    @pytest.fixture
    def missing_column_required(self):
        """Test participant table without worker_id column"""
        data = u'''id,creation_time,property1,property2,property3,property4,property5,failed,time_of_death,type,worker_id,\
assignment_id,unique_id,hit_id,mode,end_time,base_pay,bonus,status
1,2001-01-01 09:46:40.133536,,,,,,f,,participant,,8,8:36V4Q8R5ZLTJWMX0SFF0G6R67PCQMI,\
3EHVO81VN5E60KEEQ146ZGFI3FH1H6,live,2017-03-30 20:06:44.618385,,,returned'''
        f = io.StringIO(initial_value=data)
        return f

    @pytest.fixture
    def missing_column_not_required(self):
        """Test participant table without fingerprint_hash column"""
        data = u'''id,creation_time,property1,property2,property3,property4,property5,failed,time_of_death,type,worker_id,\
assignment_id,unique_id,hit_id,mode,end_time,base_pay,bonus,status
1,2001-01-01 09:46:40.133536,,,,,,f,,participant,8,36V4Q8R5ZLTJWMX0SFF0G6R67PCQMI,8:36V4Q8R5ZLTJWM\
X0SFF0G6R67PCQMI,3EHVO81VN5E60KEEQ146ZGFI3FH1H6,live,2017-03-30 20:06:44.618385,,,returned'''
        f = io.StringIO(initial_value=data)
        return f

    def test_ingest_to_model(self, db_session, network_file):
        dallinger.data.ingest_to_model(network_file, dallinger.models.Network)

        networks = dallinger.models.Network.query.all()
        assert len(networks) == 1
        network = networks[0]
        assert network.type == 'fully-connected'
        assert network.creation_time == datetime(2001, 1, 1, 9, 46, 40, 133536)
        assert network.role == 'experiment'

    def test_ingest_to_model_allows_subsequent_insert(self, db_session, network_file):
        dallinger.data.ingest_to_model(network_file, dallinger.models.Network)

        db_session.add(dallinger.models.Network())
        db_session.flush()
        db_session.commit()

        networks = dallinger.models.Network.query.all()
        assert networks[1].id == 2

    def test_missing_column_required(self, db_session, missing_column_required):
        with pytest.raises(psycopg2.IntegrityError):
            dallinger.data.ingest_to_model(missing_column_required, dallinger.models.Participant)

    def test_missing_column_not_required(self, db_session, missing_column_not_required):
        dallinger.data.ingest_to_model(missing_column_not_required, dallinger.models.Participant)

        participant = dallinger.models.Participant.query.all()
        assert len(participant) == 1
        participant = participant[0]
        assert participant.creation_time == datetime(2001, 1, 1, 9, 46, 40, 133536)

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
