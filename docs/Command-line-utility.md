Wallace is executed from the command line within the experiment directory with the following commands:   
* [`wallace verify`](#verify)
* [`wallace debug`](#debug)
* [`wallace sandbox`](#sandbox)
* [`wallace deploy`](#deploy)
* [`wallace logs`](#logs)
* [`wallace status`](#status)
* [`wallace export`](#export)
* [`wallace summary`](#summary)
* [`wallace qualify`](#qualify)
* [`wallace hibernate`](#hibernate)
* [`wallace awaken`](#awaken)
* [`wallace create`](#create)


####verify
Verifies that a directory is a Wallace-compatible app.

####debug
`--verbose`   
Runs the experiment locally. If `--verbose` is included more detailed logs are printed to the command line.

####sandbox   
`--verbose`   
`--app <name>`   
Runs the experiment on MTurk's sandbox using Heroku as a server. If `--verbose` is included more detailed logs are printed to the command line. If `--app` is specified the app on heroku will have that name.

####deploy
`--verbose`   
`--app <name>`   
Runs the experiment live on MTurk using Heroku as a server. If `--verbose` is included more detailed logs are printed to the command line. If `--app` is specified the app on heroku will have that name.

####logs
`--app <app>`   
Opens the app's logs in Papertrail.

####status
Returns the status of an experiment.

####export
Downloads the database and partial server logs to a zipped folder within the data directory of the experimental folder. Databases are stored in csv format.

####summary
`--app <app-id>`   
Prints a summary of the participant table to the command line. You must specify the app id.

####qualify   
`--qualification <qualification_id>`   
`--value <value>`   
`--worker <worker_id>`   
Assigns qualification `qualification_id` with value `value` to worker `worker_id`. This is useful when compensating workers if something goes wrong with the experiment.

####hibernate
`--app <app>`   
Temporarily scales down the specified app to save money. All dynos are removed and so are many of the add-ons. Hibernating apps are non-functional. It is likely that the app will not be entirely free while hibernating. To restore the app use `awaken`.

####awaken
`--app <app>`   
Retore a hibernating app.


####create
`--example <demo>`   
Copies the `<demo>` experiment from the examples directory to the command line location. `<demo>` must be the name of a directory with the examples directory. The default is `bartlett1932`.