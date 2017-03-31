"""Data-handling tools."""

from config import get_config

import csv
import errno
import os
import shutil
import subprocess
import tempfile
from zipfile import ZipFile

import boto
from boto.s3.key import Key
import hashlib
import psycopg2

try:
    import odo
    import pandas as pd
    import tablib
except ImportError:
    pass

from dallinger import heroku


table_names = [
    "info",
    "network",
    "node",
    "notification",
    "participant",
    "question",
    "transformation",
    "transmission",
    "vector",
]


def load(id):
    """Load the data from wherever it is found."""
    data_filename = '{}-data.zip'.format(id)
    path_to_data = os.path.join(tempfile.mkdtemp(), data_filename)

    buckets = [
        user_s3_bucket(),
        dallinger_s3_bucket(),
    ]

    for bucket in buckets:
        k = Key(bucket)
        k.key = data_filename
        try:
            k.get_contents_to_filename(path_to_data)
            return Data(path_to_data)
        except boto.exception.S3ResponseError:
            pass

    raise IOError("Dataset {} could not be found.".format(id))


def dump_database(id):
    """Dump the database to a temporary directory."""

    tmp_dir = tempfile.mkdtemp()
    current_dir = os.getcwd()
    os.chdir(tmp_dir)

    FNULL = open(os.devnull, 'w')

    subprocess.call([
        "heroku",
        "pg:backups:capture",
        "--app", heroku.app_name(id)
    ], stdout=FNULL, stderr=FNULL)

    subprocess.call([
        "heroku",
        "pg:backups:download",
        "--app", heroku.app_name(id)
    ], stdout=FNULL, stderr=FNULL)

    for filename in os.listdir(tmp_dir):
        if filename.startswith("latest.dump"):
            os.rename(filename, "database.dump")

    os.chdir(current_dir)

    return os.path.join(tmp_dir, "database.dump")


def backup(id):
    """Backup the database to S3."""
    k = Key(user_s3_bucket())
    k.key = '{}.dump'.format(id)
    filename = dump_database(id)
    k.set_contents_from_filename(filename)
    url = k.generate_url(expires_in=0, query_auth=False)
    return url


def copy_heroku_to_local(id):
    """Copy a Heroku database locally."""

    try:
        subprocess.call([
            "dropdb",
            heroku.app_name(id),
        ])
    except Exception:
        pass

    subprocess.call([
        "heroku",
        "pg:pull",
        "DATABASE_URL",
        heroku.app_name(id),
        "--app", heroku.app_name(id),
    ])


def copy_local_to_csv(local_db, path, scrub_pii=False):
    """Copy a local database to a set of CSV files."""
    conn = psycopg2.connect(database=local_db, user="postgres")
    cur = conn.cursor()
    for table in table_names:
        csv_path = os.path.join(path, "{}.csv".format(table))
        with open(csv_path, "w") as f:
            sql = "COPY {} TO STDOUT WITH CSV HEADER".format(table)
            cur.copy_expert(sql, f)
    if scrub_pii:
        _scrub_participant_table(path)


def _scrub_participant_table(path_to_data):
    """Scrub PII from the given participant table."""
    path = os.path.join(path_to_data, "participant.csv")
    with open(path, 'rb') as input, open("{}.0".format(path), 'wb') as output:
        reader = csv.reader(input)
        writer = csv.writer(output)
        headers = next(reader)
        writer.writerow(headers)
        for i, row in enumerate(reader):
            row[headers.index("worker_id")] = row[headers.index("id")]
            row[headers.index("unique_id")] = "{}:{}".format(
                row[headers.index("id")],
                row[headers.index("assignment_id")]
            )
            writer.writerow(row)

        os.rename("{}.0".format(path), path)


def export(id, local=False, scrub_pii=False):
    """Export data from an experiment."""

    print("Preparing to export the data...")

    copy_heroku_to_local(id)

    # Create the data package if it doesn't already exist.
    subdata_path = os.path.join("data", id, "data")
    try:
        os.makedirs(subdata_path)

    except OSError as e:
        if e.errno != errno.EEXIST or not os.path.isdir(subdata_path):
            raise

    # Copy in the data.
    copy_local_to_csv(heroku.app_name(id), subdata_path, scrub_pii=scrub_pii)

    # Copy the experiment code into a code/ subdirectory.
    try:
        shutil.copyfile(
            os.path.join("snapshots", id + "-code.zip"),
            os.path.join("data", id, id + "-code.zip")
        )

    except Exception:
        pass

    # Copy in the DATA readme.
    # open(os.path.join(id, "README.txt"), "a").close()

    # Save the experiment id.
    with open(os.path.join("data", id, "experiment_id.md"), "a+") as file:
        file.write(id)

    print("Zipping up the package...")
    shutil.make_archive(
        os.path.join("data", id + "-data"),
        "zip",
        os.path.join("data", id)
    )

    shutil.rmtree(os.path.join("data", id))

    print("Done. Data available in {}-data.zip".format(id))

    cwd = os.getcwd()
    data_filename = '{}-data.zip'.format(id)
    path_to_data = os.path.join(cwd, "data", data_filename)

    # Backup data on S3.
    k = Key(user_s3_bucket())
    k.key = data_filename
    k.set_contents_from_filename(path_to_data)

    return path_to_data


def user_s3_bucket(canonical_user_id=None):
    """Get the user's S3 bucket."""
    conn = _s3_connection()
    if not canonical_user_id:
        canonical_user_id = conn.get_canonical_user_id()

    s3_bucket_name = "dallinger-{}".format(
        hashlib.sha256(canonical_user_id).hexdigest()[0:8])

    if not conn.lookup(s3_bucket_name):
        bucket = conn.create_bucket(
            s3_bucket_name,
            location=boto.s3.connection.Location.DEFAULT
        )
    else:
        bucket = conn.get_bucket(s3_bucket_name)

    return bucket


def dallinger_s3_bucket():
    """The public `dallinger` S3 bucket."""
    conn = _s3_connection()
    return conn.get_bucket("dallinger")


def _s3_connection():
    """An S3 connection using the AWS keys in the config."""
    config = get_config()
    if not config.ready:
        config.load()

    return boto.s3.connect_to_region(
        config.get('aws_region'),
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key'),
    )


class Data(object):
    """Dallinger data object."""
    def __init__(self, URL):

        self.source = URL

        if self.source.endswith(".zip"):

            input_zip = ZipFile(URL)
            tmp_dir = tempfile.mkdtemp()
            input_zip.extractall(tmp_dir)

            for tab in table_names:
                setattr(
                    self,
                    "{}s".format(tab),
                    Table(os.path.join(tmp_dir, "data", "{}.csv".format(tab))),
                )


class Table(object):
    """Dallinger data-table object."""
    def __init__(self, path):

        self.odo_resource = odo.resource(path)
        self.tablib_dataset = tablib.Dataset().load(open(path).read(), "csv")

    @property
    def csv(self):
        """Comma-separated values."""
        return self.tablib_dataset.csv

    @property
    def dict(self):
        """A Python dictionary."""
        return self.tablib_dataset.dict[0]

    @property
    def df(self):
        """A pandas DataFrame."""
        return odo.odo(self.odo_resource, pd.DataFrame)

    @property
    def html(self):
        """An HTML table."""
        return self.tablib_dataset.html

    @property
    def latex(self):
        """A LaTeX table."""
        return self.tablib_dataset.latex

    @property
    def list(self):
        """A Python list."""
        return odo.odo(self.odo_resource, list)

    @property
    def ods(self):
        """An OpenDocument Spreadsheet."""
        return self.tablib_dataset.ods

    @property
    def tsv(self):
        """Tab-separated values."""
        return self.tablib_dataset.tsv

    @property
    def xls(self):
        """Legacy Excel spreadsheet format."""
        return self.tablib_dataset.xls

    @property
    def xlsx(self):
        """Modern Excel spreadsheet format."""
        return self.tablib_dataset.xlsx

    @property
    def yaml(self):
        """YAML."""
        return self.tablib_dataset.yaml
