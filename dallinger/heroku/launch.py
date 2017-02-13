"""Launch the experiment server."""

from dallinger.experiment_server.gunicorn import launch


if __name__ == '__main__':
    launch()
