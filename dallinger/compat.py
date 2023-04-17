import six
from six import text_type as unicode

unicode  # for flake8

if six.PY3:
    import shutil

    def is_command(cmd):
        return bool(shutil.which(cmd))

    def open_for_csv(*args, **kw):
        kw["newline"] = ""
        return open(*args, **kw)

else:
    from webbrowser import _iscommand

    is_command = _iscommand
    open_for_csv = open
