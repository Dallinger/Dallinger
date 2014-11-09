import wallace
import requests
import json
import time
import re
import os
import random


class TranslationTransformation(wallace.models.Transformation):
    """Translates from English to Latin or Latin to English."""

    __mapper_args__ = {"polymorphic_identity": "translation_tranformation"}

    def apply(self):

        # Detect the language.
        api_key = "AIzaSyBTyfWACesHGvIPrWksUOABTg7R-I_PAW4"
        base_url = "https://www.googleapis.com/language/translate/v2"
        payload = {
            "key": api_key,
            "q": self.info_in.contents}
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
            "q": self.info_in.contents,
            "source": source,
            "target": destination}
        r = requests.get(base_url, params=payload)
        r_dict = json.loads(r.text)
        print r_dict
        translation = r_dict[
            "data"]["translations"][0]["translatedText"].encode("utf-8")

        # Mutate
        dictionary_path = os.path.join(
            "static", "dictionaries", destination + ".txt")
        with open(dictionary_path) as f:
            dictionary = f.read().split()

        words = list(set([w for w in re.split('\W', translation)]))
        for word in words:
            if random.random() < 0.02:
                new_word = random.choice(dictionary)
                translation = translation.replace(word, new_word)

        time.sleep(1)

        # Create a new info
        info_out = wallace.models.Info(
            origin=self.node,
            contents=translation)

        self.info_out = info_out

        return info_out
