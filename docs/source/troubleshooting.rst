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

    ❯❯ Error parsing response from /launch, check web dyno logs for details: <!DOCTYPE html>
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
      File "/Users/user/.virtualenvs/dallinger/lib/python2.7/site-packages/click/core.py", line 722, in __call__
        return self.main(*args, **kwargs)
      File "/Users/user/.virtualenvs/dallinger/lib/python2.7/site-packages/click/core.py", line 697, in main
        rv = self.invoke(ctx)
      File "/Users/user/.virtualenvs/dallinger/lib/python2.7/site-packages/click/core.py", line 1066, in invoke
        return _process_result(sub_ctx.command.invoke(sub_ctx))
      File "/Users/user/.virtualenvs/dallinger/lib/python2.7/site-packages/click/core.py", line 895, in invoke
        return ctx.invoke(self.callback, **ctx.params)
      File "/Users/user/.virtualenvs/dallinger/lib/python2.7/site-packages/click/core.py", line 535, in invoke
        return callback(*args, **kwargs)
      File "/Users/user/Dallinger/dallinger/command_line.py", line 558, in sandbox
        _deploy_in_mode(u'sandbox', app, verbose)
      File "/Users/user/Dallinger/dallinger/command_line.py", line 550, in _deploy_in_mode
        deploy_sandbox_shared_setup(verbose=verbose, app=app)
      File "/Users/user/Dallinger/dallinger/command_line.py", line 518, in deploy_sandbox_shared_setup
        launch_data = _handle_launch_data('{}/launch'.format(heroku_app.url))
      File "/Users/user/Dallinger/dallinger/command_line.py", line 386, in _handle_launch_data
        launch_data = launch_request.json()
      File "/Users/user/.virtualenvs/dallinger/lib/python2.7/site-packages/requests/models.py", line 892, in json
        return complexjson.loads(self.text, **kwargs)
      File "/Library/Frameworks/Python.framework/Versions/2.7/lib/python2.7/json/__init__.py", line 339, in loads
        return _default_decoder.decode(s)
      File "/Library/Frameworks/Python.framework/Versions/2.7/lib/python2.7/json/decoder.py", line 364, in decode
        obj, end = self.raw_decode(s, idx=_w(s, 0).end())
      File "/Library/Frameworks/Python.framework/Versions/2.7/lib/python2.7/json/decoder.py", line 382, in raw_decode
        raise ValueError("No JSON object could be decoded")

If you get this from the sandbox, this usually means there's a deeper issue that requires `dallinger logs --app XXXXXX.` Usually this could be a requirements.txt file error (missing dependency or reference to an incorrect branch).
