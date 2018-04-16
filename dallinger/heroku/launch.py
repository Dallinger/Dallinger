"""Launch the experiment server."""

if __name__ == '__main__':
    # Make sure gevent patches are applied early
    import gevent.monkey
    gevent.monkey.patch_all()

    from dallinger.experiment_server.gunicorn import launch
    launch()
