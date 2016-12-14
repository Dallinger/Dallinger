from dallinger import db
from experiment import Bartlett1932


def build():
    """Potentially move PsiturkConfig stuff in here"""
    return Bartlett1932(db.init_db())
