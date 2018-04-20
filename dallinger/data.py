"""Data-handling tools."""

from config import get_config

import csv
import errno
import logging
import os
import shutil
import subprocess
import tempfile
import warnings
from zipfile import ZipFile, ZIP_DEFLATED

import boto
from boto.s3.key import Key
import hashlib
import postgres_copy
import psycopg2

from dallinger.heroku.tools import HerokuApp
from dallinger import db
from dallinger import models

logger = logging.getLogger(__name__)

with warnings.catch_warnings():
    warnings.simplefilter(action='ignore', category=FutureWarning)
    try:
        import odo
        import pandas as pd
        import tablib
    except ImportError:
        logger.debug("Failed to import odo, pandas, or tablib.")


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


def find_experiment_export(app_id):
    """Attempt to find a zipped export of an experiment with the ID provided
    and return its path. Returns None if not found.

    Search order:
        1. local "data" subdirectory
        2. user S3 bucket
        3. Dallinger S3 bucket
    """

    # Check locally first
    cwd = os.getcwd()
    data_filename = '{}-data.zip'.format(app_id)
    path_to_data = os.path.join(cwd, "data", data_filename)
    if os.path.exists(path_to_data):
        try:
            Data(path_to_data)
        except IOError:
            from dallinger import logger
            logger.exception(
                "Error reading local data file {}, checking remote.".format(
                    path_to_data
                )
            )
        else:
            return path_to_data

    # Get remote file instead
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
        except boto.exception.S3ResponseError:
            pass
        else:
            return path_to_data


def load(app_id):
    """Load the data from wherever it is found."""
    path_to_data = find_experiment_export(app_id)
    if path_to_data is None:
        raise IOError("Dataset {} could not be found.".format(app_id))

    return Data(path_to_data)


def dump_database(id):
    """Dump the database to a temporary directory."""

    tmp_dir = tempfile.mkdtemp()
    current_dir = os.getcwd()
    os.chdir(tmp_dir)

    FNULL = open(os.devnull, 'w')
    heroku_app = HerokuApp(dallinger_uid=id, output=FNULL)
    heroku_app.backup_capture()
    heroku_app.backup_download()

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


def registration_key(id):
    return '{}.reg'.format(id)


def register(id, url=None):
    """Register a UUID key in the global S3 bucket."""
    k = Key(registration_s3_bucket())
    k.key = registration_key(id)
    k.set_contents_from_string(url or 'missing')
    reg_url = k.generate_url(expires_in=0, query_auth=False)
    return reg_url


def is_registered(id):
    """Check if a UUID is already registered"""
    # We can't use key.exists() unless the user has GET access,
    # exists() would scale much better though.
    key_names = set(k.key for k in list(registration_s3_bucket().list()))
    return registration_key(id) in key_names


def copy_heroku_to_local(id):
    """Copy a Heroku database locally."""
    heroku_app = HerokuApp(dallinger_uid=id)
    try:
        subprocess.call([
            "dropdb",
            heroku_app.name,
        ])
    except Exception:
        pass

    heroku_app.pg_pull()


def copy_local_to_csv(local_db, path, scrub_pii=False):
    """Copy a local database to a set of CSV files."""
    if "postgresql://" in local_db:
        conn = psycopg2.connect(dsn=local_db)
    else:
        conn = psycopg2.connect(database=local_db, user="dallinger")
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

    if local:
        local_db = db.db_url
    else:
        local_db = HerokuApp(id).name
        copy_heroku_to_local(id)

    # Create the data package if it doesn't already exist.
    subdata_path = os.path.join("data", id, "data")
    try:
        os.makedirs(subdata_path)

    except OSError as e:
        if e.errno != errno.EEXIST or not os.path.isdir(subdata_path):
            raise

    # Copy in the data.
    copy_local_to_csv(local_db, subdata_path, scrub_pii=scrub_pii)

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

    # Zip data
    src = os.path.join("data", id)
    dst = os.path.join("data", id + "-data.zip")
    archive_data(id, src, dst)

    cwd = os.getcwd()
    data_filename = '{}-data.zip'.format(id)
    path_to_data = os.path.join(cwd, "data", data_filename)

    # Backup data on S3 unless run locally
    if not local:
        k = Key(user_s3_bucket())
        k.key = data_filename
        k.set_contents_from_filename(path_to_data)
        url = k.generate_url(expires_in=0, query_auth=False)

        # Register experiment UUID with dallinger
        register(id, url)

    return path_to_data


def ingest_zip(path, engine=None):
    """Given a path to a zip file created with `export()`, recreate the
    database with the data stored in the included .csv files.
    """
    import_order = [
        "network",
        "participant",
        "node",
        "info",
        "notification",
        "question",
        "transformation",
        "vector",
        "transmission",
    ]
    with ZipFile(path, 'r') as archive:
        filenames = archive.namelist()
        for name in import_order:
            filename = [f for f in filenames if name in f][0]
            model_name = name.capitalize()
            model = getattr(models, model_name)
            file = archive.open(filename)
            ingest_to_model(file, model, engine)


def fix_autoincrement(table_name):
    """Auto-increment pointers are not updated when IDs are set explicitly,
    so we manually update the pointer so subsequent inserts work correctly.
    """
    db.engine.execute(
        "select setval('{0}_id_seq', max(id)) from {0}".format(table_name)
    )


def ingest_to_model(file, model, engine=None):
    """Load data from a CSV file handle into storage for a
    SQLAlchemy model class.
    """
    if engine is None:
        engine = db.engine
    reader = csv.reader(file)
    columns = tuple('\"{}\"'.format(n) for n in reader.next())
    postgres_copy.copy_from(
        file, model, engine, columns=columns, format='csv', HEADER=False
    )
    fix_autoincrement(model.__table__.name)


def archive_data(id, src, dst):
    print("Zipping up the package...")
    with ZipFile(dst, 'w', ZIP_DEFLATED, allowZip64=True) as zf:
        for root, dirs, files in os.walk(src):
            for file in files:
                filename = os.path.join(root, file)
                arcname = filename.replace(src, '').lstrip('/')
                zf.write(filename, arcname)
    shutil.rmtree(src)
    print("Done. Data available in {}-data.zip".format(id))


def user_s3_bucket(canonical_user_id=None):
    """Get the user's S3 bucket."""
    conn = _s3_connection()
    if not canonical_user_id:
        canonical_user_id = conn.get_canonical_user_id()

    s3_bucket_name = "dallinger-{}".format(
        hashlib.sha256(canonical_user_id).hexdigest()[0:8])

    config = get_config()
    location = config.get('aws_region')

    # us-east-1 is the default and should not be included as location
    if not location or location == u'us-east-1':
        location = boto.s3.connection.Location.DEFAULT

    if not conn.lookup(s3_bucket_name):
        bucket = conn.create_bucket(
            s3_bucket_name,
            location=location
        )
    else:
        bucket = conn.get_bucket(s3_bucket_name)

    return bucket


def dallinger_s3_bucket():
    """The public `dallinger` S3 bucket."""
    conn = _s3_connection(dallinger_region=True)
    return conn.get_bucket("dallinger")


def registration_s3_bucket():
    """The public write-only `dallinger-registration` S3 bucket."""
    conn = _s3_connection(dallinger_region=True)
    return conn.get_bucket("dallinger-registrations")


def _s3_connection(dallinger_region=False):
    """An S3 connection using the AWS keys in the config."""
    config = get_config()
    if not config.ready:
        config.load()

    region = 'us-east-1' if dallinger_region else config.get('aws_region')
    return boto.s3.connect_to_region(
        region,
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
