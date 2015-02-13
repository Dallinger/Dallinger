from sqlalchemy import ForeignKey, Column, String, desc
from .models import Node, Info


class Environment(Node):
    __tablename__ = "environment"
    __mapper_args__ = {"polymorphic_identity": "environment"}

    # the unique environment id
    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    @property
    def state(self):
        state = Info\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Info.creation_time))\
            .first()
        return state

    def __repr__(self):
        return "Environment-{}-{}".format(self.uuid[:6], self.type)
