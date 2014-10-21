import wallace
import requests
import json
import time


class TranslationTransformation(wallace.models.Transformation):
    """Translates from English to Latin or Latin to English.
    """

    __mapper_args__ = {"polymorphic_identity": "translation_tranformation"}

    def apply(self, info_in):

        # Detect the language.
        api_key = "AIzaSyBTyfWACesHGvIPrWksUOABTg7R-I_PAW4"
        base_url = "https://www.googleapis.com/language/translate/v2"
        payload = {
            "key": api_key,
            "q": info_in.contents}
        r = requests.get(base_url + "/detect", params=payload)
        print r.text
        r_dict = json.loads(r.text)
        source = str(r_dict["data"]["detections"][0][0]["language"])

        # Tranlsate en->es and es->en.
        if source == "en":
            destination = "la"
        elif source == "la":
            destination = "en"

        payload = {
            "key": api_key,
            "q": info_in.contents,
            "source": source,
            "target": destination}
        r = requests.get(base_url, params=payload)
        r_dict = json.loads(r.text)
        print r_dict
        translation = r_dict[
            "data"]["translations"][0]["translatedText"].encode("utf-8")

        time.sleep(1)

        # Create a new information
        info_out = wallace.models.Info(
            origin=self.node,
            contents=translation)

        return info_out
