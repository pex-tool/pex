import sys


def calculate_url():
    if "final" == sys.version_info.releaselevel:
        return  "https://bootstrap.pypa.io/virtualenv/{major}.{minor}/virtualenv.pyz".format(
            major=sys.version_info.major, minor=sys.version_info.minor
        )
    else:
        # Assume a beta or alpha version of the latest Python and use the latest virtualenv
        return "https://bootstrap.pypa.io/virtualenv.pyz"


if __name__ == "__main__":
    print(calculate_url())
