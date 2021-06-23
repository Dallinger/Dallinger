import sys
from dallinger.config import get_config
from dallinger.utils import open_browser


def main(url):
    config = get_config()
    config.load()
    open_browser(url)


if __name__ == "__main__":
    url = sys.argv[1]
    main(url)
