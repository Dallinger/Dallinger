"""Data-handling tools."""

import csv
import errno
import hashlib
import io
import logging
import os
import shutil
import subprocess
import tempfile
import warnings
from zipfile import ZIP_DEFLATED, ZipFile

import boto3
import botocore
import postgres_copy
import psycopg2
import six

from dallinger import db, models
from dallinger.compat import open_for_csv
from dallinger.heroku.tools import HerokuApp

from .config import get_config

logger = logging.getLogger(__name__)

with warnings.catch_warnings():
    warnings.simplefilter(action="ignore", category=FutureWarning)
    try:
        import tablib
    except ImportError:
        logger.debug("Failed to import tablib.")


class S3BucketUnavailable(Exception):
    """No Amazon S3 bucket could be found based on the user's
    configuration.
    """


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
    data_filename = "{}-data.zip".format(app_id)
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

    config = get_config()
    if not config.ready:
        config.load()

    if not aws_access_keys_present(config):
        print("✘ AWS credentials not present, skipping download from S3.")
        return

    buckets = [user_s3_bucket(), dallinger_s3_bucket()]

    for bucket in buckets:
        if bucket is None:
            continue
        try:
            bucket.download_file(data_filename, path_to_data)
        except botocore.exceptions.ClientError:
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

    FNULL = open(os.devnull, "w")
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
    filename = dump_database(id)
    key = "{}.dump".format(id)

    bucket = user_s3_bucket()
    bucket.upload_file(filename, key)
    return _generate_s3_url(bucket, key)


def registration_key(id):
    return "{}.reg".format(id)


def register(id, url=None):
    """Register a UUID key in the global S3 bucket."""
    bucket = registration_s3_bucket()
    if bucket is None:
        return
    key = registration_key(id)
    obj = bucket.Object(key)
    obj.put(Body=url or "missing")
    return _generate_s3_url(bucket, key)


def is_registered(id):
    """Check if a UUID is already registered"""
    bucket = registration_s3_bucket()
    if bucket is None:
        return False
    key = registration_key(id)
    found_keys = set(obj.key for obj in bucket.objects.filter(Prefix=key))
    return key in found_keys


def copy_heroku_to_local(id):
    """Copy a Heroku database locally."""
    heroku_app = HerokuApp(dallinger_uid=id)
    try:
        subprocess.call(["dropdb", heroku_app.name])
    except Exception:
        pass

    heroku_app.pg_pull()


def copy_db_to_csv(dsn, path, scrub_pii=False):
    """Copy a local database to a set of CSV files."""
    if "postgresql://" in dsn or "postgres://" in dsn:
        conn = psycopg2.connect(dsn=dsn)
    else:
        conn = psycopg2.connect(database=dsn, user="dallinger")
    cur = conn.cursor()
    for table in table_names:
        csv_path = os.path.join(path, "{}.csv".format(table))
        with open(csv_path, "w") as f:
            sql = "COPY {} TO STDOUT WITH CSV HEADER".format(table)
            cur.copy_expert(sql, f)
    conn.close()
    if scrub_pii:
        _scrub_participant_table(path)


# Backwards compatibility for imports
copy_local_to_csv = copy_db_to_csv


def _scrub_participant_table(path_to_data):
    """Scrub PII from the given participant table."""
    path = os.path.join(path_to_data, "participant.csv")
    with open_for_csv(path, "r") as input, open("{}.0".format(path), "w") as output:
        reader = csv.reader(input)
        writer = csv.writer(output)
        headers = next(reader)
        writer.writerow(headers)
        for i, row in enumerate(reader):
            row[headers.index("worker_id")] = row[headers.index("id")]
            row[headers.index("unique_id")] = "{}:{}".format(
                row[headers.index("id")], row[headers.index("assignment_id")]
            )
            if "client_ip_address" in headers:
                row[headers.index("client_ip_address")] = ""
            writer.writerow(row)

        os.rename("{}.0".format(path), path)


def export(id, local=False, scrub_pii=False):
    """Export data from an experiment."""

    print("Preparing to export the data...")

    if local:
        db_uri = db.db_url
    else:
        db_uri = HerokuApp(id).db_uri
    return export_db_uri(id, db_uri=db_uri, local=local, scrub_pii=scrub_pii)


def export_db_uri(id, db_uri, local, scrub_pii):
    # Create the data package if it doesn't already exist.
    subdata_path = os.path.join("data", id, "data")
    try:
        os.makedirs(subdata_path)

    except OSError as e:
        if e.errno != errno.EEXIST or not os.path.isdir(subdata_path):
            raise

    # Copy in the data.
    copy_db_to_csv(db_uri, subdata_path, scrub_pii=scrub_pii)

    # Copy the experiment code into a code/ subdirectory.
    try:
        shutil.copyfile(
            os.path.join("snapshots", id + "-code.zip"),
            os.path.join("data", id, id + "-code.zip"),
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
    data_filename = "{}-data.zip".format(id)
    path_to_data = os.path.join(cwd, "data", data_filename)

    # Backup data on S3 unless run locally
    if not local:
        config = get_config()
        if not config.ready:
            config.load()

        if not aws_access_keys_present(config):
            print("✘ AWS credentials not present, skipping export to S3.")
            return

        bucket = user_s3_bucket()
        bucket.upload_file(path_to_data, data_filename)
        registration_url = _generate_s3_url(bucket, data_filename)
        s3_console_url = (
            f"https://s3.console.aws.amazon.com/s3/object/{bucket.name}"
            f"?region={config.aws_region}&prefix={data_filename}"
        )
        # Register experiment UUID with dallinger
        register(id, registration_url)
        print(
            "A copy of your export was saved also to Amazon S3:\n"
            f" - bucket name: {bucket.name}\n"
            f" - S3 console URL: {s3_console_url}"
        )

    return path_to_data


def aws_access_keys_present(config):
    """Verifies that AWS access keys are set"""
    if (
        config.get("aws_access_key_id") == "YourAccessKeyId"
        or config.get("aws_secret_access_key") == "YourSecretAccessKey"
        or not config.get("aws_access_key_id")
        or not config.get("aws_secret_access_key")
    ):
        return False

    return True


def bootstrap_db_from_zip(zip_path, engine):
    """Given a path to a zip archive created with `export()`, first empty the
    database, then recreate it based on the data stored in the included .csv
    files.
    """
    db.init_db(drop_all=True, bind=engine)
    ingest_zip(zip_path, engine=engine)


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
    with ZipFile(path, "r") as archive:
        filenames = archive.namelist()
        for name in import_order:
            filename = [f for f in filenames if name in f][0]
            model_name = name.capitalize()
            model = getattr(models, model_name)
            file = archive.open(filename)
            if six.PY3:
                file = io.TextIOWrapper(file, encoding="utf8", newline="")
            ingest_to_model(file, model, engine)


def fix_autoincrement(engine, table_name):
    """Auto-increment pointers are not updated when IDs are set explicitly,
    so we manually update the pointer so subsequent inserts work correctly.
    """
    engine.execute("select setval('{0}_id_seq', max(id)) from {0}".format(table_name))


def ingest_to_model(file, model, engine=None):
    """Load data from a CSV file handle into storage for a
    SQLAlchemy model class.
    """
    if engine is None:
        engine = db.engine
    reader = csv.reader(file)
    columns = tuple('"{}"'.format(n) for n in next(reader))
    postgres_copy.copy_from(
        file, model, engine, columns=columns, format="csv", HEADER=False
    )
    fix_autoincrement(engine, model.__table__.name)


def archive_data(id, src, dst):
    print("Zipping up the package...")
    with ZipFile(dst, "w", ZIP_DEFLATED, allowZip64=True) as zf:
        for root, dirs, files in os.walk(src):
            for file in files:
                filename = os.path.join(root, file)
                arcname = filename.replace(src, "").lstrip("/")
                zf.write(filename, arcname)
    shutil.rmtree(src)
    print(f"Done. Local export available in {dst}")


def _get_canonical_aws_user_id(s3):
    return s3.meta.client.list_buckets()["Owner"]["ID"]


def _get_or_create_s3_bucket(s3, name):
    """Get an S3 bucket resource after making sure it exists"""
    exists = True
    try:
        s3.meta.client.head_bucket(Bucket=name)
    except botocore.exceptions.ClientError as e:
        error_code = int(e.response["Error"]["Code"])
        if error_code == 404:
            exists = False
        else:
            raise

    if not exists:
        s3.create_bucket(Bucket=name)

    return s3.Bucket(name)


def _generate_s3_url(bucket, key):
    return "https://{}.s3.amazonaws.com/{}".format(bucket.name, key)


def user_s3_bucket(canonical_user_id=None):
    """Get the user's S3 bucket."""
    s3 = _s3_resource()
    if not canonical_user_id:
        canonical_user_id = _get_canonical_aws_user_id(s3)

    s3_bucket_name = "dallinger-{}".format(
        hashlib.sha256(canonical_user_id.encode("utf8")).hexdigest()[0:8]
    )

    return _get_or_create_s3_bucket(s3, s3_bucket_name)


def dallinger_s3_bucket():
    """The public `dallinger` S3 bucket."""
    s3 = _s3_resource(dallinger_region=True)
    return s3.Bucket("dallinger")


def registration_s3_bucket():
    """The public write-only `dallinger-registration` S3 bucket."""
    config = get_config()
    if not config.ready:
        config.load()

    if config.get("enable_global_experiment_registry", False):
        s3 = _s3_resource(dallinger_region=True)
        return s3.Bucket("dallinger-registrations")


def _s3_resource(dallinger_region=False):
    """A boto3 S3 resource using the AWS keys in the config."""
    config = get_config()
    if not config.ready:
        config.load()

    region = "us-east-1" if dallinger_region else config.get("aws_region")
    return boto3.resource(
        "s3",
        region_name=region,
        aws_access_key_id=config.get("aws_access_key_id"),
        aws_secret_access_key=config.get("aws_secret_access_key"),
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
        return self.tablib_dataset.df

    @property
    def html(self):
        """An HTML table."""
        return self.tablib_dataset.html

    @property
    def latex(self):
        """A LaTeX table."""
        return self.tablib_dataset.latex

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
