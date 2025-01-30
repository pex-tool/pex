"""Run the EasyInstall command"""

if __name__ == '__main__':
    if "setuptools" in __import__("os").environ.get("__PEX_UNVENDORED__", ""):
        from setuptools.command.easy_install import main  # vendor:skip
    else:
        from pex.third_party.setuptools.command.easy_install import main

    main()
