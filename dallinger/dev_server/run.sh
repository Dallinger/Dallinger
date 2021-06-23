#!/bin/sh
# export EXPLAIN_TEMPLATE_LOADING="True"
export FLASK_ENV="development"

flask run --port 7000 --eager-loading
