Required Experiment Files
=========================

Dallinger is flexible with regards to the form the front end takes.
However, there are a number of required or forbidden files. You can
verify that a directory is compatible by running the
:ref:`verify <dallinger-verify>` command
from a terminal within the directory. Though just because these checks
pass doesn't mean the experiment will run! The minimal required
structure is as follows:

.. figure:: _static/directories.jpg
   :alt: 

Blue items are (optional) directories (note that the experiment
directory can have any name), green items are required files (the README
file can be either a txt file or a md file), and red items are forbidden
files that will cause a conflict at run time.

Required files
^^^^^^^^^^^^^^

-  config.txt - The config file contains a variety of parameters that
   affect how Dallinger runs. For more info see...

-  experiment.py - This is a python file containing the custom
   experiment code.

-  README.txt/md - This (hopefully) contains a helpful description of
   the experiment.

Forbidden files
^^^^^^^^^^^^^^^

A number of files cannot be included in the experiment directory. This
is because, when Dallinger runs, it inserts a number of required files
into the experiment directory and will overwrite any files with the same
name. The files are as follows:

-  complete.html - this html page shows when dallinger is run in debug
   mode and the experiment is complete.
-  error\_dallinger.html - this is a flexible error page that shows when
   something goes wrong.
-  launch.html - this page is shown when the /launch route is pinged and
   the experiment starts successfully.
-  waiting.html - this page shows a standard waiting room for experiments
   that require multiple users at once.
-  robots.txt - this file is returned to bots (e.g. from Google) that
   bump into the experiment when crawling the internet.
-  dallinger2.js - this is a javascript library with a number of helpful
   functions.
-  `reqwest.min.js <https://github.com/ded/reqwest>`__ - this is
   required for dallinger2.js to work.
-  dallinger.css - this contains several css classes that are used in the
   demos.

Custom files
^^^^^^^^^^^^

You can specify files from outside the experiment directory that should
be merged in using the `extra_files` function. This is a module-level
function in the `experiment.py` file that returns a sequence of source
and destination tuples. The source can be either a file or a directory.

For example:

.. code-block:: python

    def extra_files():
        return [
            ("/home/user/stimulus.txt", "/static/stimulus.txt"),
            ("/home/user/stimuluses", "/static/stimuluses"),
        ]

You can also provide this as a class method on the
:py:class:`~dallinger.experiment.Experiment` class.