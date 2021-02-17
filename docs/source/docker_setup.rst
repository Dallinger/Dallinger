Image generation
================

Starting from version XXX, Dallinger can generate docker images to be used for deployment.

A base image is provided in the docker registry: `dallingerimages/dallinger:<version>`
for a specific version, and `dallingerimages/dallinger:<version>` for the latest one.

The dallinger CLI can generate an image for an experiment and upload it to heroku.


Deployment to Heroku
====================

Use the command `deploy-container` to deploying the experiment to Heroku using docker containers.
