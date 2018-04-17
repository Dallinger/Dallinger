"""Launch the experiment server."""

if __name__ == '__main__':
    # Make sure gevent patches are applied early.
    # Avoid patching threads because dallinger configuration
    # is a thread local, and turning it into a greenlet context local
    # makes it get lost when greenlets are spawned.
    # (Note that it will still get patched by gunicorn's gevent handler,
    # but that's okay because it happens late enough that the config
    # thread local has already been instantiated. :-o )
    import gevent.monkey
    gevent.monkey.patch_all(thread=False)

    from dallinger.experiment_server.gunicorn import launch
    launch()
