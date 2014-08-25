import numpy as np
from wallace import Wallace

"""This is a simple demo of Wallace's behavior. In this demo, an
initial stimulus of "0-0-0-0-0" is transmitted to a random
participant. That participant then transmits the (possibly mutated)
stimulus to another random participant. This type of transmission is
repeated several times.

"""

if __name__ == "__main__":
    # initialize Wallace
    w = Wallace(drop_all=True)

    # create the source node (which generates the stimuli)
    source = w.add_source("Origin")

    # create participants
    for name in ["Jess", "Jordan", "Tom", "Mike", "Stephan"]:
        w.add_participant(name)

    # create vectors between participants
    participants = w.get_participants()
    for p1 in participants:
        w.add_vector(source, p1)
        for p2 in participants:
            if p1.id != p2.id:
                w.add_vector(p1, p2)

    # commit the initial setup to the database
    w.db.commit()

    # create the initial stimulus
    stim = w.add_meme(source, contents="0-0-0-0-0")

    # create random transmissions
    for i in xrange(20):

        # first pick the vector, and send the stimulus
        vectors = w.get_vectors(origin=stim.origin)
        vidx = np.random.randint(0, len(vectors))
        p = vectors[vidx].destination
        print "'{}' sends '{}' to '{}'".format(
            stim.origin.name, stim.contents, p.name)
        stim.transmit(p)
        w.db.commit()

        # then randomly mutate the stimulus and add the new meme to
        # the database
        contents = [int(x) for x in stim.contents.split("-")]
        if np.random.rand() < 0.5:
            idx = np.random.randint(0, len(contents))
            contents[idx] += 1
        contents = "-".join([str(x) for x in contents])
        stim = w.add_meme(p, contents=contents)
