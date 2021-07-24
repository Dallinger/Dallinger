#!/bin/sh
export FLASK_ENV="development"

flask run --port 7000 --eager-loading
