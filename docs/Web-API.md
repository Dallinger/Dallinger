The Wallace server comes with a number of pre-existing routes by which the front-end can communicate with the back end. Many of these routes correspond to specific functions of Wallace's [classes](https://github.com/berkeley-cocosci/Wallace/wiki/Classes), particularly Node. For instance, Nodes have a connect method that creates new Vectors between Nodes and there is a corresponding connect route that allows the front end to call this method.

#### Miscellaneous routes

**/ad_address/\<mode>/\<hit_id>** [get]   
Used to get the address of the experiment on the psiTurk server and to return participants to MTurk upon completion of the experiment. This route is pinged automatically by the function `submit_assignment` in wallace.js.

**/\<directory>/\<page>** [get]   
Returns the html page with the name \<page> from the directory called \<directory>.

**/summary** [get]   
Returns a summary of the statuses of Participants.

**/\<page>** [get]   
Returns the html page with the name \<page>.

#### Experiment routes

**/experiment_property/\<property>** [get]   
Returns the value of the requested property as a json `<property>`.

**/info/\<node_id>/\<info_id>** [get]   
Returns a json description of the requested info as `info`. *node_id* must be specified to ensure the requesting node has access to the requested info. Calls experiment method `info_get_request(node, info).

**/info/\<node_id>** [post]   
Create an info with its origin set to the specified node. *contents* must be passed as data. *info_type* can be passed as data and will cause the info to be of the specified type. Also calls experiment method `info_post_request(node, info)`.

**/launch** [post]   
Initializes the experiment and opens recruitment. This route is automatically pinged by Wallace.

**/network/\<network_id>** [get]   
Returns a json description of the requested network as `network`.

**/node/\<node_id>/connect/\<other_node_id>** [post]   
Create vector(s) between the `node` and `other_node` by calling `node.connect(whom=other_node)`. Direction can be passed as data and will be forwarded as an argument. Calls experiment method `vector_post_request(node, vectors)`. Returns a list of json descriptions of the created vectors as `vectors`.

**/node/\<node_id>/infos** [get]   
Returns a list of json descriptions of the infos created by the node as `infos`. Infos are identified by calling `node.infos()`. *info_type* can be passed as data and will be forwarded as an argument. Requesting node and the list of infos are also passed to experiment method `info_get_request(node, infos)`.

**/node/\<node_id>/neighbors** [get]   
Returns a list of json descriptions of the node's neighbors as `nodes`. Neighbors are identified by calling `node.neighbors()`. *node_type* and *connection* can be passed as data and will be forwarded as arguments. Requesting node and list of neighbors are also passed to experiment method `node_get_request(node, nodes)`.

**/node/\<node_id>/received_infos** [get]   
Returns a list of json descriptions of the infos sent to the node as `infos`. Infos are identified by calling `node.received_infos()`. *info_type* can be passed as data and will be forwarded as an argument. Requesting node and the list of infos are also passed to experiment method `info_get_request(node, infos)`.

**/node/\<int:node_id>/transformations** [get]   
Returns a list of json descriptions of all the transformations of a node identified using `node.transformations()`. The node id must be specified in the url. You can also pass *transformation_type* as data and it will be forwarded to `node.transformations()` as the argument *type*.

**/node/\<node_id>/transmissions** [get]   
Returns a list of json descriptions of the transmissions sent to/from the node as `transmissions`. Transmissions are identified by calling `node.transmissions()`. *direction* and *status* can be passed as data and will be forwarded as arguments. Requesting node and the list of transmissions are also passed to experiment method `transmission_get_request(node, transmissions)`.

**/node/\<node_id>/transmit** [post]   
Transmit to another node by calling `node.transmit()`. The sender's node id must be specified in the url. As with node.transmit() the key parameters are what and to_whom and they should be passed as data. However, the values these accept are more limited than for the back end due to the necessity of serialization.   
If what and to_whom are not specified they will default to None.
Alternatively you can pass an int (e.g. '5') or a class name (e.g.
'Info' or 'Agent'). Passing an int will get that info/node, passing
a class name will pass the class. Note that if the class you are specifying
is a custom class it will need to be added to the dictionary of
known_classes in your experiment code.   
You may also pass the values property1, property2, property3, property4
and property5. If passed this will fill in the relevant values of the
transmissions created with the values you specified.   
The transmitting node and a list of created transmissions are sent to experiment method `transmission_post_request(node, transmissions)`. This route returns a list of json descriptions of the created transmissions as `transmissions`.
For example, to transmit all infos of type Meme to the node with id 10:
```
reqwest({
    url: "/node/" + my_node_id + "/transmit",
    method: 'post',
    type: 'json',
    data: {
        what: "Meme",
        to_whom: 10,
    },
});
```

**/node/\<node_id>/vectors** [get]   
Returns a list of json descriptions of vectors connected to the node as `vectors`. Vectors are identified by calling `node.vectors()`. *direction* and *failed* can be passed as data and will be forwarded as arguments. Requesting node and list of vectors are also passed to experiment method `vector_get_request(node, vectors)`. 

**/node/\<participant_id>** [post]   
Create a node for the specified participant. The route calls the following experiment methods: `get_network_for_participant(participant)`, `create_node(network, participant)`, `add_node_to_network(node, network)`, and `node_post_request(participant, node)`. Returns a json description of the created node as `node`.

**/participant/\<participant_id>** [get]   
Returns a json description of the requested participant as `participant`.

**/participant/\<worker_id>/\<hit_id>/\<assignment_id>/\<mode>** [post]   
Create a participant. Returns a json description of the participant as `participant`.

**/question/\<participant_id>** [post]   
Create a question. *question*, *response* and *question_id* should be passed as data. Does not return anything.
