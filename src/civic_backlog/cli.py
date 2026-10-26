import argparse
from . import __version__


def main():
    parser = argparse.ArgumentParser(prog="civic", description="Snapshot-based civic backlog analysis")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args()


if __name__ == "__main__": main()
