First, make sure you have Wallace installed:

* [Installation instructions for users](Installing-Wallace-(for-users).md)
* [Installation instructions for developers](Developing-Wallace-(setup-guide).md)

To test out Wallace, we'll run an example experiment in debug mode. From a terminal within the Wallace directory, run

```
cd examples/bartlett1932
wallace debug
```

You will see some output as Wallace loads. When it is finished, you will see something that looks like:

```
Now serving on http://0.0.0.0:5000
[psiTurk server:on mode:sdbx #HITs:4]$
```

This is the psiTurk prompt. Into that prompt type:

```
debug
```

This will cause the experiment to open in a new window in your browser. Once you have finished the experiment, you can type `debug` again to play as the next participant.

**Help, the experiment page is blank!** This may happen if you are using an ad-blocker. Try disabling your ad-blocker and refresh the page.
