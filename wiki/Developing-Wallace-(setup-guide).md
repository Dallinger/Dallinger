# Getting Started: Developing Wallace

#### Install Python 2.7

You will need Python 2.7. You can check what version of Python you have by running:
    ```
    python --version
    ```
If you do not have Python 2.7 installed, you can install it from the [Python website] (https://www.python.org/downloads/).

Or, if you know `brew`:
```
brew install python
```

If you have Python 3.x installed and and symlinked to the command `python` you will need to create a `virtualenv` that interprets the code as `python2.7` (because of compatibility with the `psiturk` module). Fortunately, we will be creating a virtual environment anyway, so as long as you run `brew install python` and you don't run into any errors because of your symlinks then you can just proceed with the instructions. If you do run into any errors, may god have pity on your soul (or your python installation… whichever proves to be easier). 

#### Install Postgres using `brew`

```
brew install postgres
```

***

#### Detailed installation for setting up virtual environments in which to work on Wallace.

If you would like to develop Wallace(or if you primarily use Python3), you will need to set up a virtual environment (you only need to run these commands once):

```
pip install virtualenv
pip install virtualenvwrapper
export WORKON_HOME=$HOME/.virtualenvs
mkdir -p $WORKON_HOME
source $(which virtualenvwrapper.sh)
mkvirtualenv wallace --python /usr/local/bin/python2.7
```

These commands use `pip` the python package manager to install two packages `virtualenv` and `virtualenvwrapper`. They set up an environmental variable named `WORKON_HOME` with a string that gives a path to a subfolder of your home directory (`~`) called `Envs`, which the next command (`mkdir`) then makes according to the path described in `$WORKON_HOME` (recursively, due to the `-p` flag). That is where your environments will be stored. The `source` command will run the command that follows, which in this case locates the the `virtualenvwrapper.sh` shell script the contents of which are beyond the scope of this setup tutorial. If you want to know what it does a more in depth description can be found at [this page on `virtualenvwrapper.sh`](http://virtualenvwrapper.readthedocs.org/en/latest/install.html#python-interpreter-virtualenv-and-path). Finally the `mkvirtualenv` makes your first virtual environment which you've named `wallace`. We have explicitly passed it the location of `python2.7` so that even if your `python` command has been remapped to `python3` it will create the environment with `python2.7` as its interpreter.

In the future, you can work on your virtual environment by running:

```
source $(which virtualenvwrapper.sh)
workon wallace
```

NB: **To stop working on the virtual environment, just run `deactivate`.** If you ever need to see what environments you have (if you don't remember their names) use the command `workon` with no arguments

Now, navigate to the directory in which you want to house your development work on Wallace. Once you are there, clone the git repository using:

```
git clone https://github.com/berkeley-cocosci/Wallace
```

This will create a directory called `Wallace` in your current directory. 

Change into your the new directory and make sure you are in your virtual environment before installing the dependencies. If you want to be extra carfeul, run the command `workon wallace`, which will ensure that you are in the right virtual environment.

```
cd Wallace
```

Now we need to install the dependencies by running the following command:

```
pip install -r requirements.txt
```

Then run `setup.py` with the argument `develop`:

```
python setup.py develop
```



Once that's finished, we need to input the credentials for 3rd party applications including Amazon Web Services (AWS), Amazon Mechanical Turk (AMT), PsiTurk & Heroku. [Instructions for this process as it applies to Wallace live at this page.](https://github.com/berkeley-cocosci/Wallace/wiki/Setting-up-AWS,-psiTurk,-MTurk,-and-Heroku)
