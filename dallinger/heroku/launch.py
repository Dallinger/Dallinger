"""Launch the experiment server."""

from dallinger.experiment_server.gunicorn import launch


if __name__ == '__main__':
    from gevent import monkey
    monkey.patch_all()

    launch()
