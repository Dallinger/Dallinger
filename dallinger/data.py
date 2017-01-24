"""Data-handling tools."""

from config import get_config

import errno
import os
import shutil
import subprocess
import tempfile
from zipfile import ZipFile

import boto
from boto.s3.key import Key
import hashlib
import odo
import pandas as pd
import tablib

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


def dump_database(id):
    """Dump the database to a temporary directory."""

    tmp_dir = tempfile.mkdtemp()
    current_dir = os.getcwd()
    os.chdir(tmp_dir)

    FNULL = open(os.devnull, 'w')

    subprocess.call([
        "heroku",
        "pg:backups:capture",
        "--app",
        heroku.app_name(id)
    ], stdout=FNULL, stderr=FNULL)

    subprocess.call([
        "heroku",
        "pg:backups:download",
        "--app",
        heroku.app_name(id)
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


def export(id, local=False):
    """Export data from an experiment."""

    print("Preparing to export the data...")

    subdata_path = os.path.join("data", id, "data")

    # Create the data package if it doesn't already exist.
    try:
        os.makedirs(subdata_path)

    except OSError as e:
        if e.errno != errno.EEXIST or not os.path.isdir(subdata_path):
            raise

    # Copy the experiment code into a code/ subdirectory
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

    if not local:
        # Export the logs
        subprocess.check_call(
            "heroku logs " +
            "-n 10000 > " + os.path.join("data", id, "server_logs.md") +
            " --app " + heroku.app_name(id),
            shell=True)

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
        "--app",
        heroku.app_name(id),
    ])

    for table in table_names:
        subprocess.check_call(
            "psql -d " + heroku.app_name(id) +
            " --command=\"\\copy " + table + " to \'" +
            os.path.join(subdata_path, table) + ".csv\' csv header\"",
            shell=True)

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


def user_s3_bucket():
    """Get the user's S3 bucket."""
    config = get_config()
    if not config.ready:
        config.load_config()

    conn = boto.connect_s3(
        config.get('aws_access_key_id'),
        config.get('aws_secret_access_key'),
    )

    s3_bucket_name = "dallinger-{}".format(
        hashlib.sha256(conn.get_canonical_user_id()).hexdigest()[0:8])

    if not conn.lookup(s3_bucket_name):
        bucket = conn.create_bucket(
            s3_bucket_name,
            location=boto.s3.connection.Location.DEFAULT
        )
    else:
        bucket = conn.get_bucket(s3_bucket_name)

    return bucket


class Data(object):
    """Dallinger data object."""
    def __init__(self, URL):
        super(Data, self).__init__()

        self.source = URL

        if self.source.endswith(".zip"):

            input_zip = ZipFile(URL)
            tmp_dir = tempfile.mkdtemp()
            input_zip.extractall(tmp_dir)

            for tab in table_names:
                setattr(
                    self,
                    "{}s".format(tab),
                    Table(os.path.join(tmp_dir, "data", "{}.csv").format(tab)),
                )


class Table(object):
    """Dallinger data-table object."""
    def __init__(self, path):
        super(Table, self).__init__()

        self.odo_resource = odo.resource(path)
        self.tablib_dataset = tablib.Dataset().load(open(path).read())

    @property
    def csv(self):
        """Comma-separated values."""
        return self.tablib_dataset.csv

    @property
    def dict(self):
        """A Python dictionary."""
        return self.tablib_dataset.dict

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
