from wallace import processes, agents, sources, networks, db

"""This demo runs a transmission chain. The source transmits a random binary
string to the first agent in line. At each time step, the string is passed
down the line.
"""

session = db.init_db(drop_all=True)

# Settings
N = 10
num_steps = 9

# Create a network
n = networks.Chain(session, N)

# Add a binary string source and transmit to everyone
source = sources.RandomBinaryStringSource()
n.add_local_source(source, n.first_agent)
n.trigger_source(source)

# Run the process
p = processes.RandomWalkFromSource(n)
for i in xrange(num_steps):
    p.step()
