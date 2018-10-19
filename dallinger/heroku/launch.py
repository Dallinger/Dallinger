"""Launch the experiment server."""
# Make sure gevent patches are applied early.
import gevent.monkey
gevent.monkey.patch_all()


def main():
    from dallinger.experiment_server.gunicorn import launch
    launch()


if __name__ == '__main__':
    main()
