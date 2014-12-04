Wallace
=======
[![Build Status](https://magnum.travis-ci.com/suchow/Wallace.svg?token=ygVLzsadbn3UbxEk8GzT&branch=master)](https://magnum.travis-ci.com/suchow/Wallace)
[![Coverage Status](https://coveralls.io/repos/suchow/Wallace/badge.png?branch=master)](https://coveralls.io/r/suchow/Wallace?branch=master)
[![License](http://img.shields.io/badge/license-MIT-red.svg)](http://en.wikipedia.org/wiki/MIT_License)

<img src="portrait.jpg?raw=true" align="left" width="125" alt="Portrait of Alfred Russel Wallace">

Wallace is a platform for conducting research on experimental cultural evolution. Its namesake is Alfred Russel Wallace, a British naturalist and the oft-ignored codiscoverer of evolution by natural selection. You can use Wallace to create new experiments or to reproduce existing experiments. For example, the following code runs a replication of Bartlett's 1932 study, where participants pass a story down a chain, from one to the next.

    wallace create bartlett1932
    cd bartlett1932
    wallace deploy

Features
--------

- Run experiments on experimental cultural evolution
- Coordinates participant recruitment using Mechanical Turk
- Example experiments that cover a range of common experimental designs

Installation
------------

Install Wallace by running:

    pip install wallace

Contribute
----------

- Issue Tracker: github.com/suchow/Wallace/issues
- Source Code: github.com/suchow/Wallace

Support
-------

If you are having issues, please let us know.
We have a mailing list located at: wallace-project@lists.berkeley.edu

License
-------

The project is licensed under the MIT license.
