#!/bin/sh
export FLASK_APP="app.py"
export FLASK_DEBUG=1

# --eager-loading is required because we're patching IO with gevent.monkey.patch_all()
# See somewhat indirect reference:
# https://github.com/miguelgrinberg/Flask-SocketIO/issues/901
echo "Starting flask..."
echo "Remember to terminate this process with <control-c> before running 'dallinger bootstrap' again"
flask run ${FLASK_OPTIONS} "$@"
