"""PostgreSQL COPY command utilities."""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import class_mapper


def copy_from(source, dest, engine_or_conn, columns=(), **flags):
    """Import a table from a file. For flags, see the PostgreSQL documentation
    at http://www.postgresql.org/docs/9.5/static/sql-copy.html.

    Examples: ::
        with open('/path/to/file.tsv') as fp:
            copy_from(fp, MyTable, conn)

        with open('/path/to/file.csv') as fp:
            copy_from(fp, MyModel, engine, format='csv')

    :param source: Source file pointer, in read mode
    :param dest: SQLAlchemy model or table
    :param engine_or_conn: SQLAlchemy engine, connection, or raw_connection
    :param columns: Optional tuple of columns
    :param **flags: Options passed through to COPY

    If an existing connection is passed to `engine_or_conn`, it is the caller's
    responsibility to commit and close.

    The `columns` flag can be set to a tuple of strings to specify the column
    order. Passing `header` alone will not handle out of order columns, it simply tells
    postgres to ignore the first line of `source`.
    """
    tbl = dest.__table__ if is_model(dest) else dest
    conn, autoclose = raw_connection_from(engine_or_conn)
    cursor = conn.cursor()
    relation = ".".join('"{}"'.format(part) for part in (tbl.schema, tbl.name) if part)
    formatted_columns = "({})".format(",".join(columns)) if columns else ""
    formatted_flags = "({})".format(format_flags(flags)) if flags else ""
    copy = "COPY {} {} FROM STDIN {}".format(
        relation,
        formatted_columns,
        formatted_flags,
    )
    cursor.copy_expert(copy, source)
    if autoclose:
        conn.commit()
        conn.close()


def format_flags(flags):
    return ", ".join(
        "{} {}".format(key.upper(), format_flag(value)) for key, value in flags.items()
    )


def format_flag(value):
    return str(value).upper() if isinstance(value, bool) else repr(value)


def raw_connection_from(engine_or_conn):
    """Extract a raw_connection and determine if it should be automatically closed.

    Only connections opened by this package will be closed automatically.
    """
    if hasattr(engine_or_conn, "cursor"):
        return engine_or_conn, False
    if hasattr(engine_or_conn, "connection"):
        return engine_or_conn.connection, False
    return engine_or_conn.raw_connection(), True


def is_model(class_):
    try:
        class_mapper(class_)
        return True
    except SQLAlchemyError:
        return False
