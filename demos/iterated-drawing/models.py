import base64
import json
import os

from dallinger.nodes import Source


class DrawingSource(Source):
    """A Source that reads in a random image from a file and transmits it."""

    __mapper_args__ = {
        "polymorphic_identity": "drawing_source"
    }

    def _contents(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information() -> _contents().
        """
        images = [
            "owl.png",
            "xkcd.png",
            "portrait.png",
        ]

        image = images[(self.network.id - 1) % len(images)]

        image_path = os.path.join("static", "stimuli", image)
        uri_encoded_image = (
            "data:image/png;base64," +
            base64.b64encode(open(image_path, "rb").read())
        )

        return json.dumps({
            "image": uri_encoded_image,
            "sketch": ""
        })
