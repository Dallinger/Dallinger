from wallace import processes, agents, networks, db

"""This demo runs a neutral Moran process over a scale-free network. A source
transmits a random binary string to each individual. At each time step, a
randomly selected  individual is chosen and transmits its message to another
randomly selected individual. Eventually, one message becomes fixed in the
population.
"""

session = db.init_db(drop_all=True)

# Settings
N = 20
num_steps = 100

# Create a network
n = networks.ScaleFree(session, N)
print n.get_degrees()
# n = networks.FullyConnected(session, N)

# Add a binary string source and transmit to everyone
source = agents.RandomBinaryStringSource()
n.add_global_source(source)
n.trigger_source(source)

# Run the Moran process
p = processes.MoranProcess(n, num_steps)
p.run()
