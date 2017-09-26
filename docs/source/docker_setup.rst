Docker Setup
============

Docker support is newly added. Install Dallinger by pulling our image from Dockerhub. This installs Dallinger within an isolated Ubuntu 16.04 environment, running all the neccessary services bridged to your local machine's ports.

Innstructions
-------------
Install Dallinger by pulling our image from Dockerhub.

::

    docker pull dallinger/dallinger

Make sure your ports 5000, 5432, and 6379 are open, then run:

::

    docker run -p 5000:5000 -p 5432:5432 -p 6379:6379 -it dallinger/dallinger

This command will attach you to the Ubuntu container and run the Bartlett (1932) experiment demo.
You can visit the URL(s) at the end of the log using the command:

::

    python -m webbrowser <URL_IN_LOG>
