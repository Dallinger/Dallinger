#!/bin/sh

# Generate a unique URL for the experiment app.
UUID=$(python  -c 'import uuid; print uuid.uuid4()')
UUID="x${UUID:0:18}"  # Play nice with Heroku demands (< 30, start with letter)
echo $UUID
BASEURL="meteor.com"
EXPERIMENT_URL="http://$UUID.$BASEURL"
export EXPERIMENT_URL  # Export to environment variable
echo $EXPERIMENT_URL
HEROKU_APP_NAME=$UUID
HEROKU_APP_URL="http://"$HEROKU_APP_NAME".herokuapp.com/"

# Deploy the frontend experiment app.
echo "Deploying experiment website."
cd examples/experiments/function-learning/webapp
meteor reset
export HEROKU_APP_URL="http://"$HEROKU_APP_NAME".herokuapp.com/"
sed "s,HEROKU_APP_URL,$HEROKU_APP_URL,g" server/methods.js > tmp && mv tmp server/methods.js
meteor deploy $EXPERIMENT_URL
sed "s,$HEROKU_APP_URL,HEROKU_APP_URL,g" server/methods.js > tmp && mv tmp server/methods.js
cd ..
cd ..
cd ..
cd ..

# Deploy the backend.
echo "Running the experiment on MTurk."
heroku apps:create $HEROKU_APP_NAME
heroku addons:add heroku-postgresql:hobby-dev
heroku pg:wait
heroku config:set EXPERIMENT_URL=$EXPERIMENT_URL
heroku config:push  # Set AWS keys, etc.

git push heroku recruiters:master --force

# Launch the experiment.
echo "Launching the experiment."
echo $HEROKU_APP_URL"launch"
curl -X POST $HEROKU_APP_URL"launch"
