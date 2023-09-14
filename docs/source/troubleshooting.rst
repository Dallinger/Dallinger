Troubleshooting
===============

A few common issues are reported when trying to run Dallinger. Always run with the `--verbose` flag for full logs

Python Processes Kept Alive
---------------------------

Sometimes when trying to run experiments consecutively in Debug mode, a straggling process creates Server 500 errors.
These are caused by background python processes and/or gunicorn workers. Filter for them using:

::

    ps -ef | grep -E "python|gunicorn"

This will display all running processes that have the name `python` or `gunicorn`. To kill all of them, run these commands:
::

    pkill python
    pkill gunicorn


Known Postgres issues
---------------------

If you get an error like the following...

::

    createuser: could not connect to database postgres: could not connect to server:
        Is the server running locally and accepting
        connections on Unix domain socket "/tmp/.s.PGSQL.5432"?

...then you probably did not start the app.

If you get a fatal error that your ROLE does not exist, run these commands:

::

    createuser dallinger
    dropdb dallinger
    createdb -O dallinger dallinger


Common Sandbox Error
--------------------


::


    ❯❯ Launching the experiment on MTurk...

    ❯❯ Error parsing response from /launch, check logs for details: <!DOCTYPE html>
        <html>
          <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <meta charset="utf-8">
            <title>Application Error</title>
            <style media="screen">
              html,body,iframe {
                margin: 0;
                padding: 0;
              }
              html,body {
                height: 100%;
                overflow: hidden;
              }
              iframe {
                width: 100%;
                height: 100%;
                border: 0;
              }
            </style>
          </head>
          <body>
            <iframe src="//www.herokucdn.com/error-pages/application-error.html"></iframe>
          </body>
        </html>
    Traceback (most recent call last):
      File "/Users/user/.virtualenvs/dallinger/bin/dallinger", line 11, in <module>
        load_entry_point('dallinger', 'console_scripts', 'dallinger')()
      File "/Users/user/.virtualenvs/dallinger/lib/python3.6/site-packages/click/core.py", line 722, in __call__
        return self.main(*args, **kwargs)
      File "/Users/user/.virtualenvs/dallinger/lib/python3.6/site-packages/click/core.py", line 697, in main
        rv = self.invoke(ctx)
      File "/Users/user/.virtualenvs/dallinger/lib/python3.6/site-packages/click/core.py", line 1066, in invoke
        return _process_result(sub_ctx.command.invoke(sub_ctx))
      File "/Users/user/.virtualenvs/dallinger/lib/python3.6/site-packages/click/core.py", line 895, in invoke
        return ctx.invoke(self.callback, **ctx.params)
      File "/Users/user/.virtualenvs/dallinger/lib/python3.6/site-packages/click/core.py", line 535, in invoke
        return callback(*args, **kwargs)
      File "/Users/user/Dallinger/dallinger/command_line.py", line 558, in sandbox
        _deploy_in_mode(u'sandbox', app, verbose)
      File "/Users/user/Dallinger/dallinger/command_line.py", line 550, in _deploy_in_mode
        deploy_sandbox_shared_setup(verbose=verbose, app=app)
      File "/Users/user/Dallinger/dallinger/command_line.py", line 518, in deploy_sandbox_shared_setup
        launch_data = handle_launch_data('{}/launch'.format(heroku_app.url))
      File "/Users/user/Dallinger/dallinger/command_line.py", line 386, in handle_launch_data
        launch_data = launch_request.json()
      File "/Users/user/.virtualenvs/dallinger/lib/python3.6/site-packages/requests/models.py", line 892, in json
        return complexjson.loads(self.text, **kwargs)
      File "/Library/Frameworks/Python.framework/Versions/3.6/lib/python3.6/json/__init__.py", line 339, in loads
        return _default_decoder.decode(s)
      File "/Library/Frameworks/Python.framework/Versions/3.6/lib/python3.6/json/decoder.py", line 364, in decode
        obj, end = self.raw_decode(s, idx=_w(s, 0).end())
      File "/Library/Frameworks/Python.framework/Versions/3.6/lib/python3.6/json/decoder.py", line 382, in raw_decode
        raise ValueError("No JSON object could be decoded")

If you get this from the sandbox, this usually means there's a deeper issue that requires `dallinger logs --app XXXXXX.` Usually this could be a requirements.txt file error (missing dependency or reference to an incorrect branch).


Combining Dallinger core development and running experiments
------------------------------------------------------------

A common pitfall while doing development on the dallinger codebase while also
working on external experiments which include dallinger as a dependency: you
pip install a demo experiment in your active virtual environment, and it
overwrites the dallinger.egg-link file in that environment's site-packages
directory with an actual copy of the dallinger package.

When installing dallinger with the intent to work on dallinger, the recommended
way to install dallinger itself is with pip's "editable mode", by passing the
-e or --editable flag to pip install:

::

    pip install -e .[data]


This creates a form of symbolic link in the active python's site-packages
directory to the working copy of dallinger you're sitting in. This allows you to
make changes to python files in the dallinger working copy and have them
immediately active when using dallinger commands or any other actions that
invoke the active python interpreter.

Running pip install without the -e flag, either while installing dallinger
directly, or while installing a separate experiment which includes dallinger as
a dependency, will instead place a copy of the dallinger package in the
site-packages directory. These files will then be executed when the active
python is running, and any changes to the files you're working on will be
ignored.

You can check to see if you are working in "editable mode" by inspecting the
contents of your active virtual environment's site-packages folder. In
"editable mode", you will see a dallinger.egg-link file listed in the directory:

::

    ...
    drwxr-xr-x    9 jesses  staff   306B May 29 12:30 coverage_pth-0.0.2.dist-info
    -rw-r--r--    1 jesses  staff    44B May 29 12:30 coverage_pth.pth
    -rw-r--r--    1 jesses  staff    33B Jun 14 16:08 dallinger.egg-link
    drwxr-xr-x   21 jesses  staff   714B Mar 19 17:24 datashape
    drwxr-xr-x   10 jesses  staff   340B Mar 19 17:24 datashape-0.5.2.dist-info
    ...


The contents of this file will include the path to the working copy that's
active. If you instead see a directory tree with actual dallinger files, you can
restore "editable mode" by re-running the installation steps for dallinger from
the :doc:`developing_dallinger_setup_guide` documentation.
