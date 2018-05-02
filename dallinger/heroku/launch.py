"""Launch the experiment server."""

if __name__ == '__main__':
    from gevent import monkey
    monkey.patch_all()

    from dallinger.experiment_server.gunicorn import launch
    launch()
