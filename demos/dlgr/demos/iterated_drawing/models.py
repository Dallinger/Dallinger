import base64
import json
import os
import random

from dallinger.nodes import Source


class DrawingSource(Source):
    """A Source that reads in a random image from a file and transmits it."""

    __mapper_args__ = {"polymorphic_identity": "drawing_source"}

    def _contents(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information() -> _contents().
        """
        images = ["owl.png"]

        # We're selecting from a list of only one item here, but it's a useful
        # technique to demonstrate:
        image = random.choice(images)

        image_path = os.path.join("static", "stimuli", image)

        uri_encoded_image = "data:image/png;base64," + base64.b64encode(
            open(image_path, "rb").read()
        ).decode("ascii")

        return json.dumps({"image": uri_encoded_image, "sketch": ""})
