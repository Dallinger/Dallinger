# Database Models

* [Node](#node)
* [Vector](#vector)
* [Meme](#meme)
* [Transmission](#transmission)

## Node

```python
>>> from wallace import db, models
>>> session = db.init_db(drop_all=True)
>>> node = models.Node()
>>> session.add(node)
>>> session.commit()
>>> node
Node-92792f-base
```

### Attributes

* `uuid` -- the unique identifier of the node, which is generated automatically on creation.
* `type` -- the type of the node, which allows for custom models to inherit from the `Node` class. By default, the value is `'base'`.
* `creation_time` -- the time the node was created. This is set automatically on creation.
* `memes` -- the memes that were created by this node.
* `outdegree` -- the outdegree of this node (how many outgoing edges it has)
* `indegree` -- the indegree of this node (how many incoming edges it has)
* `incoming_vectors` -- the incoming edges to this node
* `outgoing_vectors` -- the outgoing edges from this node
* `successors` -- nodes that are connected to this node by an outgoing edge
* `predecessors` -- nodes that are connected to this node by an incoming edge
* `incoming_transmissions` -- all transmissions to this node
* `outgoing_transmissions` -- all transmissions from this node

### Functions

* `connect(direction, whom)` -- creates vector(s) between this node and whom in the given direction
* `transmit(what, whom)` -- creates transmission(s) of what from this node to whom
* `broadcast(meme)` -- creates transmission of the given meme to all connected nodes
* `is_connected(direction, whom)` -- whether this node has a vector to/from another node

## Vector

```python
>>> node1 = models.Node()
>>> node2 = models.Node()
>>> vector = models.Vector(origin=node1, destination=node2)
>>> session.add_all([node1, node2, vector])
>>> session.commit()
>>> vector
Vector-1d04da-052a13
```

### Attributes

* `origin_uuid` -- the UUID of the origin node
* `origin` -- the origin node
* `destination_uuid` -- the UUID of the destination node
* `destination` -- the destination node
* `transmissions` -- all transmissions that have occurred along this vector

## Meme

```python
>>> node = models.Node()
>>> meme = models.Meme(origin=node, contents="these are my contents")
>>> session.add_all([node, meme])
>>> session.commit()
>>> meme
Meme-f8c9be-base
```

### Attributes

* `uuid` -- the unique identifier for this meme. Automatically generated upon creation.
* `type` -- the type of the meme, which allows custom models to inherit from `Meme`. By default, the value is `'base'`.
* `origin_uuid` -- the UUID of the node that created the meme
* `origin` -- the node that created the meme
* `creation_time` -- the time the node was created. Set automatically upon creation.
* `contents` -- the actual contents of the meme.
* `transmissions` -- the individual transmission events for this meme

### Functions

* `copy_to(other_node)` -- creates a copy of the meme with a different node as the origin

## Transmission

```python
>>> node1 = models.Node()
>>> node2 = models.Node()
>>> node1.connect(whom=node2)
>>> meme = models.Meme(origin=node1)
>>> session.add_all([node1, node2, meme])
>>> session.commit()
>>> transmission = models.Transmission(meme=meme, destination=node2)
>>> session.add(transmission)
>>> session.commit()
>>> transmission
Transmission-8c4a33
```

### Attributes

* `uuid` -- the unique identifier of this transmission event. Automatically generated upon creation.
* `meme_uuid` -- the UUID of the meme that was transmitted
* `meme` -- the meme that was transmitted
* `origin_uuid` -- the UUID of the node the transmission originated from
* `origin` -- the node that the transmission originated from
* `destination_uuid` -- the UUID of the transmission's destination node
* `destination` -- the transmission's destination node
* `transmit_time` -- the time the transmission occurred. Set automatically upon creation.
* `vector` -- the vector that this transmission occurred along