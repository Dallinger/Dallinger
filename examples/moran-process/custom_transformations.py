from wallace.models import Transformation, Info
from collections import OrderedDict


class SubstitutionCipher(Transformation):
    """Translates from English to Latin or Latin to English."""

    __mapper_args__ = {"polymorphic_identity": "translation_tranformation"}

    alphabet = "abcdefghijklmnopqrstuvwxyz"
    keyword = "zebras"

    # Generate the ciphertext alphabet
    kw_unique = ''.join(OrderedDict.fromkeys(keyword).keys())
    non_keyword_letters = ''.join([l for l in alphabet if l not in kw_unique])
    ciphertext_alphabet = kw_unique + non_keyword_letters

    def apply(self):

        text = self.info_in.contents

        # Do the lower case.
        for i in range(len(self.alphabet)):
            text = text.replace(self.alphabet[i], self.ciphertext_alphabet[i])

        # And the upper case.
        alphabet_up = self.alphabet.upper()
        ciphertext_alphabet_up = self.ciphertext_alphabet.upper()
        for i in range(len(alphabet_up)):
            text = text.replace(alphabet_up[i], ciphertext_alphabet_up[i])

        # Create a new info
        info_out = Info(origin=self.node, contents=text)

        self.info_out = info_out

        return info_out
