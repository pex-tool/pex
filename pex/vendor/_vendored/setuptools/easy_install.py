"""Run the EasyInstall command"""

if __name__ == '__main__':
    if "__PEX_UNVENDORED__" in __import__("os").environ:
      from setuptools.command.easy_install import main  # vendor:skip
    else:
      from pex.third_party.setuptools.command.easy_install import main

    main()
