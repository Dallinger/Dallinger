This is a guide to running experiments on Wallace.
   
If, instead, you would like to contribute to Wallace, go to [Developing Wallace](https://github.com/berkeley-cocosci/Wallace/wiki/Developing-Wallace-(setup-guide)), which will take you through the steps necessary for setting up a development environment for Wallace.


# Getting Started: Running Wallace

1. You will need to have Python 2.7 installed. You can check what version of Python you have by running:

    ```
    python --version
    ```

    If you do not have Python 2.7 installed, you can install it from the [Python website] (https://www.python.org/downloads/). 

2. Install Postgres from [postgresapp.com](http://postgresapp.com). This will require downloading a zip file, unzipping the file and installing the unzipped application. 

   You will then need to add Postgres to your PATH environmental variable. If you use the default location for installing applications on OS X (namely `/Applications`), you can adjust your path by running the following command:

    ```
    export PATH="/Applications/Postgres.app/Contents/Versions/9.3/bin:$PATH"
    ```
   NB: If you have installed a more recent version of Postgres (e.g., the [the upcoming version 9.4](https://github.com/PostgresApp/PostgresApp/releases/tag/9.4rc1)) you may need to alter that command slightly to accommodate the more recent version number. If you need to – or want to – double check which version to include, then run:    
    `ls /Applications/Postgres.app/Contents/Versions/`    
    Whatever number that returns is the version number that you should place in the `export` command above. If it does not return a number, you have not installed Postgres correctly in your /Applications folder or something else is horribly wrong. :(

3. Install Wallace and its dependencies using pip (`pip install wallace`). Or, if you want to develop with Wallace, follow the instructions below (in the section [Developing Wallace](https://github.com/berkeley-cocosci/Wallace/wiki/Developing-Wallace-(setup-guide))).

## Testing Wallace
1. Change directory to the `bartlett1932` demo.
    ```
    cd examples/bartlett1932
    ```

2. Run the demo.
    ```
    wallace debug
    ```

3. Then when wallace has loaded a server, you should see a prompt that looks somewhat like:
    ```
    Now serving on http://0.0.0.0:5000
    [psiTurk server:on mode:sdbx #HITs:4]$
    ```
    Into that prompt type, `debug`.
