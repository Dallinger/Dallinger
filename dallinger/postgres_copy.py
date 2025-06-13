"""PostgreSQL COPY command utilities."""


def copy_from(file, model, engine, columns=None, format="csv", HEADER=True):
    """Copy data from a file into a table using PostgreSQL's COPY command."""
    table = model.__table__.name
    if columns:
        columns_str = ", ".join(columns)
        sql = f"COPY {table} ({columns_str}) FROM STDIN WITH {format}"
        if HEADER:
            sql += " HEADER"
    else:
        sql = f"COPY {table} FROM STDIN WITH {format}"
        if HEADER:
            sql += " HEADER"

    conn = engine.raw_connection()
    cur = conn.cursor()
    cur.copy_expert(sql, file)
    conn.commit()
    cur.close()
    conn.close()
