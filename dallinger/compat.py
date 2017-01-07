"""Compatibility utilities."""

try:
    unicode = unicode
except NameError:  # Python 3
    unicode = str
