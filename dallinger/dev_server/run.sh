#!/bin/sh
export FLASK_APP="app.py"
export FLASK_ENV="development"

# We want to run the worker and clock process in the background,
# but also have them terminate when control-c is sent to the
# foreground Flask process:
trap 'kill $WORKER_PID; kill $CLOCK_PID; exit' INT
dallinger_heroku_worker &
WORKER_PID=$!
dallinger_heroku_clock &
CLOCK_PID=$!

# --eager-loading is required because we're patching IO with gevent.monkey.patch_all()
# See somewhat indirect reference:
# https://github.com/miguelgrinberg/Flask-SocketIO/issues/901
echo "Starting flask..."
echo "Remember to terminate this process with <control-c> before running 'dallinger bootstrap' again"
flask run --eager-loading "$@" || kill $WORKER_PID; kill $CLOCK_PID; exit
