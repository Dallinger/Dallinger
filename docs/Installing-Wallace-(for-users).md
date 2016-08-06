*If you would like to contribute to Wallace please follow these [alternative install instructions](https://github.com/suchow/Wallace/wiki/Installing-Wallace-(for-developers)).*

#### Install Python

Wallace is written in the language Python. For it to work you will need to have Python 2.7 installed. You can check what version of Python you have by running:
```
python --version
```
If you do not have Python 2.7 installed, you can install it from the [Python website] (https://www.python.org/downloads/). 

#### Install Postgres

Wallace uses Postgres to create local databases. Install Postgres from [postgresapp.com](http://postgresapp.com). This will require downloading a zip file, unzipping the file and installing the unzipped application. 

You will then need to add Postgres to your PATH environmental variable. If you use the default location for installing applications on OS X (namely `/Applications`), you can adjust your path by running the following command:
```
export PATH="/Applications/Postgres.app/Contents/Versions/9.3/bin:$PATH"
```
NB: If you have installed a more recent version of Postgres (e.g., the [the upcoming version 9.4](https://github.com/PostgresApp/PostgresApp/releases/tag/9.4rc1)) you may need to alter that command slightly to accommodate the more recent version number. If you need to – or want to – double check which version to include, then run:    
```
ls /Applications/Postgres.app/Contents/Versions/
```
Whatever number that returns is the version number that you should place in the `export` command above. If it does not return a number, you have not installed Postgres correctly in your /Applications folder or something else is horribly wrong.

#### Create the Database

After installing Postgres, you will need to create a database for your experiment to use. Run the following command from the comand line:

```
psql -c 'create database wallace;' -U postgres
```

#### Install Wallace

Install Wallace from the terminal by running
```
pip install wallace
```

#### Testing Wallace

To test that Wallace works we will run an example experiment in debug mode. From a terminal within the Wallace directory, run

```
cd examples/bartlett1932
wallace debug
```

You will see some print-out as Wallace loads. When it is finished you will see something that looks like:

```
Now serving on http://0.0.0.0:5000
[psiTurk server:on mode:sdbx #HITs:4]$
```

Into that prompt type,

```
debug
```

This will cause the experiment to open in a new window in your browser. Once you have finished the experiment you can type `debug` again to play as the next participant too.

**Help, the experiment page is blank!** This may happen if you are using an ad-blocker. Try disabling your ad-blocker and refresh the page.
