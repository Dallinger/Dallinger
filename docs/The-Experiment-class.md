Experiments are designed in Wallace by creating a custom subclass of the base Experiment class. The code for the Experiment class is in experiments.py. Unlike the [other classes](https://github.com/berkeley-cocosci/Wallace/wiki/Classes), each experiment involves only a single Experiment object and it is not stored as an entry in a corresponding table, rather each Experiment is a set of instructions that tell the server what to do with the database when the server receives requests from outside.

#### Attributes

+ verbose - Boolean, determines whether the experiment logs output when running. Default is True.
+ task - String, the name of the experiment. Default is "Experiment title".
+ session - session, the experiment's connection to the database.
+ practice_repeats - int, the number of practice networks (see [Network.role](https://github.com/berkeley-cocosci/Wallace/wiki/Classes#columns)). Default is 0.
+ experiment_repeats - int, the number of non practice networks (see [Network.role](https://github.com/berkeley-cocosci/Wallace/wiki/Classes#columns)). Default is 0.
+ recruiter - Recruiter, the Wallace class that recruits participants. Default is PsiTurkRecruiter.
+ initial_recruitment_size - int, the number of participants requested when the experiment first starts. Default is 1.
+ known_classes - dictionary, the classes Wallace can make in response to front-end requests. Experiments can add new classes to this dictionary.

#### Functions

experiment**.\_\_init\_\_**(*session*)   
Create the experiment class. Sets the value of attributes, see above.

experiment**.add_node_to_network**(*node, network*)   
Pass the *node* to *network.add_node()*.

experiment**.assignment_abandoned**(*participant*)   
Runs when a notification from AWS is received indicating that *participant* has run out of time. Calls fail_participant.

experiment**.assignment_returned**(*participant*)   
Runs when a notification from AWS is received indicating that *participant* has returned the experiment assignment. Calls fail_participant.

experiment**.attention_check**(*participant*)   
Return a boolean value indicating whether the *participant*'s data is acceptable. This is mean to check the participant's data to determine that they paid attention. This check will run once the *participant* completes the experiment. By default performs no checks and returns True. See also experiment.data_check().

experiment**.attention_check_failed**(*participant*)   
Runs when *participant* has failed the attention_check. By default calls fail_participant.

experiment**.bonus**(*participant*)   
Return the value of the bonus to be paid to *participant*. By default returns 0.

experiment**.bonus_reason**(*participant*)
Return a string that will be included in an email sent to the *participant* receiving a bonus. By default it is "Thank you for participant! Here is your bonus."

experiment**.create_network**()
Return a new network. By default, the type of network is determined by experiment.network_type(). If the experiment uses networks of different types, or needs to pass argument to the network's __init__() method, this function should be overwritten. Otherwise, it is simpler to overwrite network_type().

experiment**.create_node**(*participant, network*)
Return a new node associated with the *participant* and in *network*. By default, the type of node is determined by experiment.node_type(). If the experiment uses nodes of different types, or needs to pass argument to the node's __init__() method, this function should be overwritten. Otherwise, it is simpler to overwrite node_type().

experiment**.data_check**(*participant*)   
Return a boolean value indicating whether the *participant*'s data is acceptable. This is meant to check for missing or invalid data. This check will be run once the *participant* completes the experiment. By default performs no checks and returns True. See also, experiment.attention_check().

experiment**.data_check_failed**(*participant*)   
Runs when *participant* has failed the data_check. By default calls fail_participant.

experiment**.fail_participant**(*participant*)   
Instruct all *participant*'s unfailed nodes to fail.

experiment**.get_network_for_participant**(*participant*)   
Return a network that the *participant* can join. If not networks are available returns None. By default participants can participate only once in each network and participants first complete networks with role="practice" before doing all other networks in a random order.

experiment**.info_get_request**(*node, infos*)   
Overwritable method that runs after a request from the front-end from *node* to get infos.

experiment**.info_post_request**(*node, info*)   
Overwritable method that runs after a request from the front-end from *node* to make an info.

experiment**.log**(*text, [key, force]*)   
Print *text* to the logs. *key* will be appended to text. Logging is suppressed if verbose=False, but will still occur if *force*=True (by default it is False).

experiment**.log_summary**()   
Print a summary of participant statuses.

experiment**.networks**(*[role, full]*)   
Return a list of networks. Can filter by *role* (String) and *full* (Boolean), both default to "all".

experiment**.node_get_request**(*participant, [node, nodes]*)   
Overwritable method that runs after a request from the front-end from *participant* to get a node/nodes.

experiment**.node_post_request**(*participant, node*)   
Overwritable method that runs after a request from the front-end from *participant* to make a node.

experiment**.network_type**()   
Return the class of network to be created. See create_network().

experiment**.node_type**()   
Return the class of node to be created. See create_node().

experiment**.recruit**()   
Recruit more participants. This method runs whenever a participant successfully completes the experiment (participants who fail to finish successfully are automatically replaced). By default it recruits 1 participant at a time until all networks are full.

experiment**.save**(objects)   
Add *objects* to the database and then commit. This only needs to be done for networks and participants.

experiment**.setup**()   
Create networks if none are present.

experiment**.submission_successful**(*participant*)   
Overwritable method that runs after the *participant* completes the experiment and passes the data_check and attention_check(). By default does nothing.

experiment**.transformation_get_request**(*node, transformations*)   
Overwritable method that runs after a request from the front-end from *node* to get transformations.

experiment**.transformation_post_request**(*node, transformation*)   
Overwritable method that runs after a request from the front-end from *node* to make a transformation.

experiment**.transmission_get_request**(*node, transmissions*)   
Overwritable method that runs after a request from the front-end from *node* to get transmissions.

experiment**.transmission_post_request**(*node, transmission*)   
Overwritable method that runs after a request from the front-end from *node* to send a transmission.

experiment**.vector_get_request**(*node, vectors*)   
Overwritable method that runs after a request from the front-end from *node* to get vectors.

experiment**.vector_post_request**(*node, vector*)   
Overwritable method that runs after a request from the front-end from *node* to make a vector.
