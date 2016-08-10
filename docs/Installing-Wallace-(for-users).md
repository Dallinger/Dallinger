*If you would like to contribute to Wallace, please follow these [alternative install instructions](Developing-Wallace-(setup-guide).md).*

#### Install Python

Wallace is written in the language Python. For it to work, you will need to have Python 2.7 installed. You can check what version of Python you have by running:
```
python --version
```
If you do not have Python 2.7 installed, you can install it from the [Python website](https://www.python.org/downloads/). 

#### Install Postgres

Wallace uses Postgres to create local databases. On OS X, install Postgres from [postgresapp.com](http://postgresapp.com). This will require downloading a zip file, unzipping the file and installing the unzipped application. 

You will then need to add Postgres to your PATH environmental variable. If you use the default location for installing applications on OS X (namely `/Applications`), you can adjust your path by running the following command:
```
export PATH="/Applications/Postgres.app/Contents/Versions/9.3/bin:$PATH"
```
NB: If you have installed a more recent version of Postgres (e.g., the [the upcoming version 9.4](https://github.com/PostgresApp/PostgresApp/releases/tag/9.4rc1)), you may need to alter that command slightly to accommodate the more recent version number. To double check which version to include, then run:    
```
ls /Applications/Postgres.app/Contents/Versions/
```
Whatever number that returns is the version number that you should place in the `export` command above. If it does not return a number, you have not installed Postgres correctly in your `/Applications` folder or something else is horribly wrong.

#### Create the Database

After installing Postgres, you will need to create a database for your experiments to use. Run the following command from the comand line:

```
psql -c 'create database wallace;' -U postgres
```

#### Install Wallace

Install Wallace from the terminal by running
```
pip install wallace-platform
```

Test that your installation works by running:

```
wallace --version
```

If you use Anaconda installing wallace probably failed. The problem is that you need to install bindings for the `psycopg2` package (it helps python play nicely with postgres) and you need to use conda for conda to know where to look for the links. You do this with:

```
conda install psycopg2
```

Then, try the above installation commands, they should work now, meaning you can move on. 

Next, you'll need [access keys for AWS, Heroku, etc.](AWS-etc-keys.md)
