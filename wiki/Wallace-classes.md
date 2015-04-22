# Conceptual Wallace

This page provides a description of the core classes with which Wallace runs experiments. Below each class is described in detail, however, as a brief summary: At the highest level a Wallace experiment is instantiated as an Experiment. An experiment creates a number of Networks. Each Network is made up of Nodes and the Vectors that link them. Nodes create Infos which are sent along Vectors as Transmissions. Infos can be related to one another with Transformations.

The code for these classes can be found in models.py.

## Nodes

Each Node represents a single point in a single network. A Node can be occupied by a participant, but can also be automated. Nodes have a number of useful functions that allows them to do things like connect to other nodes and send information to each other. Nodes also have a status that is either alive, dead or failed. Nodes are alive unless specified otherwise.

### Methods common to all Nodes

#### kill()
Sets the status of the Node to dead. This may be used to distinguish Nodes that have completed all actions they will ever do from those that are ongoing.

#### fail()
Sets the status of the Node to failed. This is used to indicate that the Node has done something wrong and needs to be removed from the Network. For example, if a participant gives nonsense responses to a trial you can fail() that Node. Wallace will automatically find replacements for failed nodes.

#### get_incoming_vectors(status="alive")
Returns a list of all the Vectors starting at the Node. By default only alive Vectors are returned, you can alternatively request "all" or "dead" Vectors.

#### get_outgoing_vectors(status="alive")
Returns a list of all the Vectors arriving at the Node. By default only alive Vectors are returned, you can alternatively request "all" or "dead" Vectors.

#### get_upstream_nodes()
FIX!

#### get_downstream_nodes()
Fix!

#### get_infos()
FIX!

#### connect_to(other_node)
Links the Node to the other_node by creating a new Vector between them. Can be passed either a single Node or a list of Nodes. If a Vector already exists from the Node to the other_node a warning is printed to the console but no Vector is created.

#### connect_from(other_node)
This is the reverse of connect_to().

#### transmit(what, to_whom)
Sends the Info(s) specified by what from this Node to the other node(s) specified by to_whom. The transmission of a particular Info to another Node creates a new Transmission. Nodes can only transmit Infos they are the origin of and can only transmit to other nodes that they are connected to. The argument what can be an Info, a list of Infos, a subclass of Info (in which case all Infos belonging to that subclass are transmitted), a list of subclasses of Info or a mixed list of Infos and subclasses of Info. If no value of what is specified the Nodes _what() method is called to generate a value.
Similarly, to_whom can be a Node, a list of Nodes, a subclass of Node, a list of subclasses of Node or a mixed list of Nodes and subclasses of Node. If no value of to_whom is specified the Nodes default _to_whom() method is called to generate a value.

#### _what()
Returns a value for the argument what in transmit() if none was specified by the user. By default this returns the class Info meaning that the Node will transmit all Infos it has created.

#### _to_whom()
Returns a value for the argument to_whom in transmit() if none was specified by the user. By default this returns the class Node meaning that the Node will transmit to all Nodes it is connected to.

#### observe()
This is a special way to interact with Environments (a subclass of Node). Observe calls the environment's get_observed() function. By default this transmits _what() to the observer. However, unlike transmit, it also returns the value of _what(), allowing you to do this: `some_info = node.observe(environment)`. This allows you to get the contents of the info(s) sent by the environment without having to do a query.

#### update(infos)
Provides default behavior in response to the receipt of Infos and is called by receive() and receive_all(). Needs to be overridden.

#### receive_all()
Looks up all pending transmissions, marks them all as received and then passes them as a list to update().

#### receive(thing)
This is the equivalent of receive_all() but for a single transmission. The argument thing specifies what is being received, which can either be a specific pending transmission or a specific Info that has been transmitted. The meaning of this is that you can receive a specific transmission now, whilst other transmissions remain pending. Note that Transmissions need to already have been sent using transmit() before they can be received.






