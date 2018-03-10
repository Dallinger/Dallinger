from six import text_type as unicode
import six

if six.PY3:
    import shutil
    def is_command(cmd):
        return bool(shutil.which(cmd))
else:
    from webbrowser import _iscommand
    is_command = _iscommand
