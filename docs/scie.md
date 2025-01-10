# PEX with included Python interpreter

You can include a Python interpreter in your PEX by adding `--scie eager` to your `pex` command
line. Instead of a traditional [PEP-441](https://peps.python.org/pep-0441/) PEX zip file, you'll
get a native executable that contains both a Python interpreter and your PEX'd code.

## Background

Traditional PEX files allow you to build and ship a hermetic Python application environment to other
machines by just copying the PEX file there. There is a major caveat though: the machine must have a
Python interpreter installed and on the `PATH` that is compatible with the application for the PEX
to be able to run. Complicating things further, when executing the PEX file directly (e.g.:
`./my.pex`), the PEX's shebang must align with the names of Python binaries installed on the
machine. If the shebang is looking for `python` but the machine only has `python3` - even if the
underlying Python interpreter would be compatible - the operating system will fail to launch the PEX
file. This usually can be mitigated by using `--sh-boot` to alter the boot mechanism from Python to
a Posix-compatible shell at `/bin/sh`.  Although almost all Posix-compatible systems have a
`/bin/sh` shell, that still leaves the problem of having a compatible Python pre-installed on that
system as well.

When you add the `--scie eager` option to your `pex` command line, Pex uses the [science](
https://science.scie.app/) [projects](https://github.com/a-scie/) to produce what is known as a
`scie` (pronounced like "ski") binary powered by the [Python Standalone Builds](
https://github.com/astral-sh/python-build-standalone) CPython distributions or the distributions
released by [PyPy](https://pypy.org/download.html) depending on which interpreter your PEX targets.
The end product looks and behaves like a traditional PEX except in two aspects:
+ The PEX scie file is larger than the equivalent PEX file since it contains a Python distribution.
+ The PEX scie file is a native executable binary.

For example, here we create a traditional PEX, a `--sh-boot` PEX and a PEX scie and examine the
resulting files:
```sh
# Create a cowsay PEX in each style:
:; pex cowsay -c cowsay --inject-args=-t --venv -o cowsay.pex
:; pex cowsay -c cowsay --inject-args=-t --venv --sh-boot -o cowsay-sh-boot.pex
:; pex cowsay -c cowsay --inject-args=-t --venv --scie eager -o cowsay

# See what these files look like:
:; head -1 cowsay*
==> cowsay <==
ELF>��@�8

==> cowsay-sh-boot.pex <==
#!/bin/sh

==> cowsay.pex <==
#!/usr/bin/env python3.11

:; file cowsay*
cowsay:             ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), static-pie linked, BuildID[sha1]=f1f01ca2ad165fed27f8304d4b2fad02dcacdffe, stripped
cowsay-sh-boot.pex: POSIX shell script executable (binary data)
cowsay.pex:         Zip archive data, made by v2.0 UNIX, extract using at least v2.0, last modified, last modified Sun, Jan 01 1980 00:00:00, uncompressed size 0, method=deflate

:; ls -sSh1 cowsay*
 31M cowsay
728K cowsay-sh-boot.pex
724K cowsay.pex
```

The PEX scie can even be inspected like a traditional PEX file:
```sh
:; for pex in cowsay*; do echo $pex; unzip -l $pex | tail -7; echo; done
cowsay
warning [cowsay]:  31525759 extra bytes at beginning or within zipfile
  (attempting to process anyway)
        7  1980-01-01 00:00   .deps/cowsay-6.1-py3-none-any.whl/cowsay-6.1.dist-info/top_level.txt
      873  1980-01-01 00:00   PEX-INFO
     7588  1980-01-01 00:00   __main__.py
        0  1980-01-01 00:00   __pex__/
     7561  1980-01-01 00:00   __pex__/__init__.py
---------                     -------
  2634753                     217 files

cowsay-sh-boot.pex
        7  1980-01-01 00:00   .deps/cowsay-6.1-py3-none-any.whl/cowsay-6.1.dist-info/top_level.txt
      873  1980-01-01 00:00   PEX-INFO
     7588  1980-01-01 00:00   __main__.py
        0  1980-01-01 00:00   __pex__/
     7561  1980-01-01 00:00   __pex__/__init__.py
---------                     -------
  2634753                     217 files

cowsay.pex
        7  1980-01-01 00:00   .deps/cowsay-6.1-py3-none-any.whl/cowsay-6.1.dist-info/top_level.txt
      873  1980-01-01 00:00   PEX-INFO
     7588  1980-01-01 00:00   __main__.py
        0  1980-01-01 00:00   __pex__/
     7561  1980-01-01 00:00   __pex__/__init__.py
---------                     -------
  2634753                     217 files
```

The performance of the PEX scie compares favorably, as you'd hope.
```sh
:; hyperfine -w2 './cowsay.pex Moo!' './cowsay-sh-boot.pex Moo!' './cowsay Moo!'
Benchmark 1: ./cowsay.pex Moo!
  Time (mean ± σ):      99.2 ms ±   3.7 ms    [User: 86.4 ms, System: 13.7 ms]
  Range (min … max):    96.1 ms … 110.7 ms    30 runs

Benchmark 2: ./cowsay-sh-boot.pex Moo!
  Time (mean ± σ):      17.6 ms ±   0.3 ms    [User: 15.2 ms, System: 2.2 ms]
  Range (min … max):    16.8 ms …  18.7 ms    165 runs

Benchmark 3: ./cowsay Moo!
  Time (mean ± σ):      16.3 ms ±   0.4 ms    [User: 13.4 ms, System: 2.7 ms]
  Range (min … max):    15.5 ms …  18.6 ms    180 runs

Summary
  ./cowsay Moo! ran
    1.08 ± 0.03 times faster than ./cowsay-sh-boot.pex Moo!
    6.09 ± 0.27 times faster than ./cowsay.pex Moo!
```

But, unlike traditional PEXes, you can run the PEX scie anywhere:
```sh
# Traditional Python shebang boot:
:; env -i PATH= ./cowsay.pex Moo!
/usr/bin/env: 'python3.11': No such file or directory

# A --sh-boot /bin/sh boot:
:; env -i PATH= ./cowsay-sh-boot.pex Moo!
Failed to find any of these python binaries on the PATH:
python3.11
python3.13
...
python3
python2
pypy3
pypy2
python
pypy
Either adjust your $PATH which is currently:

Or else install an appropriate Python that provides one of the binaries in this list.

# A hermetic scie boot:
:; env -i PATH= ./cowsay Moo!
  ____
| Moo! |
  ====
    \
     \
       ^__^
       (oo)\_______
       (__)\       )\/\
           ||----w |
           ||     ||
```

## Lazy scies

Specifying `--scie eager` includes a full Python distribution in your PEX scie. If you ship more 
than one PEX scie to a machine using the same Python version, this can be wasteful in transfer
bandwidth and disk space. If your deployment machines have internet access, you can specify
`--scie lazy` and the Python distribution will then be fetched from the internet, but only if
needed. If a PEX scie (whether eager or lazy) using the same Python distribution has run previously
on the machine, the fetch will be skipped and the local distribution used instead. This lazy
fetching feature is powered by the [`ptex` binary](https://github.com/a-scie/ptex) from the science
projects, and you can read more there if you're curious.

If your network access is restricted, you can re-point the download location of the Python
distribution by ensuring the machine has the environment variable `PEX_BOOTSTRAP_URLS` set to the
path of a json file containing the new Python distribution URL. That file should look like:
```json
{
  "ptex": {
    "cpython-3.12.4+20240713-x86_64-unknown-linux-gnu-install_only.tar.gz": "<internal URL>"
  }
}
```

You can run `SCIE=inspect <your PEX scie> | jq '{ptex:.ptex}'` to get a starter file with the
correct default entries for your scie. You can then just edit the URLs. URLs of the form
`file://<absolute path>` are accepted. The only restriction for any custom URL is that it returns a
bytewise-identical copy of the Python distribution pointed to by the original URL. If the file
content hash does not match, the PEX scie will fail to boot. For example:
```sh
# Build a lazy PEX scie:
:; pex cowsay -c cowsay --inject-args=-t --scie lazy -o cowsay

# Generate a starter file for the alternate URLs:
:; SCIE=inspect ./cowsay | jq '{ptex:.ptex}' > starter.json

# Copy to pythons.json and edit it to point to a file that does not contain the original Python
# distribution:
:; jq 'first(.ptex | .[]) = "file:///etc/hosts"' starter.json > pythons.json
:; diff -u --label starter.json starter.json --label pythons.json pythons.json
--- starter.json
+++ pythons.json
@@ -1,5 +1,5 @@
 {
   "ptex": {
-    "cpython-3.11.9+20240726-x86_64-unknown-linux-gnu-install_only.tar.gz": "https://github.com/astral-sh/python-build-standalone/releases/download/20240726/cpython-3.11.9%2B20240726-x86_64-unknown-linux-gnu-install_only.tar.gz"
+    "cpython-3.11.9+20240726-x86_64-unknown-linux-gnu-install_only.tar.gz": "file:///etc/hosts"
   }
 }

# Clear the scie cache and try to run the lazy PEX scie:
:; rm -rf ~/.cache/nce
:; PEX_BOOTSTRAP_URLS=pythons.json ./cowsay Moo!
Error: Failed to establish atomic directory /home/jsirois/.cache/nce/0770bcb55edb6b8089bcc8cbe556d3f737f4a5e3a5cbc45e716206de554c0df9/locks/configure-ce4ae7966f25868830154e6fa8d56b0dd6e09cd2902ab837a4af55d51dc84d92. Population of work directory failed: Failed to establish atomic directory /home/jsirois/.cache/nce/f6e955dc9ddfcad74e77abe6f439dac48ebca14b101ed7c85a5bf3206ed2c53d/cpython-3.11.9+20240726-x86_64-unknown-linux-gnu-install_only.tar.gz. Population of work directory failed: The tar.gz destination /home/jsirois/.cache/nce/f6e955dc9ddfcad74e77abe6f439dac48ebca14b101ed7c85a5bf3206ed2c53d/cpython-3.11.9+20240726-x86_64-unknown-linux-gnu-install_only.tar.gz of size 410 had unexpected hash: 16183c427758316754b82e4d48d63c265ee46ec5ae96a40d9092e694dd5f77ab

The ./cowsay scie contains no alternate boot commands.
```

Here we see the error `.../cpython-3.11.9+20240726-x86_64-unknown-linux-gnu-install_only.tar.gz of
size 410 had unexpected hash: 16183c427758316754b82e4d48d63c265ee46ec5ae96a40d9092e694dd5f77ab`. We
can correct this by re-pointing to a valid file:
```sh
# Download the expected dstribution:
:; curl -fL https://github.com/astral-sh/python-build-standalone/releases/download/20240726/cpython-3.11.9%2B20240726-x86_64-unknown-linux-gnu-install_only.tar.gz > /tmp/example

# Re-point to the now valid copy of the expected Python distribution:
:; jq 'first(.ptex | .[]) = "file:///tmp/example"' starter.json > pythons.json
:; diff -u --label starter.json starter.json --label pythons.json pythons.json
--- starter.json
+++ pythons.json
@@ -1,5 +1,5 @@
 {
   "ptex": {
-    "cpython-3.11.9+20240726-x86_64-unknown-linux-gnu-install_only.tar.gz": "https://github.com/astral-sh/python-build-standalone/releases/download/20240726/cpython-3.11.9%2B20240726-x86_64-unknown-linux-gnu-install_only.tar.gz"
+    "cpython-3.11.9+20240726-x86_64-unknown-linux-gnu-install_only.tar.gz": "file:///tmp/example"
   }
 }

 # And lazy bootstrapping from the Python distribution in /tmp/example now works:
 :; PEX_BOOTSTRAP_URLS=pythons.json ./cowsay Moo!
  ____
| Moo! |
  ====
    \
     \
       ^__^
       (oo)\_______
       (__)\       )\/\
           ||----w |
           ||     ||
```

## BusyBox scies

Scies support multiple commands, but, by default, `pex --scie ...` generates a PEX scie that always
executes the entry point you configured for your PEX. You can, of course, run the scie using
`PEX_INTERPRETER`, `PEX_MODULE` and `PEX_SCRIPT` to modify the entry point just like you can with
a normal PEX, but sometimes it can be convenient to seal in a small set of commands you wish to use
for easier access. You do this by adding `--scie-busybox` to your `pex` command line with a list of
entry points you wish to expose. These entry points can be arbitrary modules or functions within a
module. They can also be console scripts from distributions in the PEX. The BusyBox entry point
specifications accepted are detailed below:

| Form                     | Example                 | Effect                                                                                                                            |
|--------------------------|-------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `<name>=<module>`        | `json=json.tool`        | Add a `json` command that invokes the `json.tool` module.                                                                         |
| `<name>=<module>:<func>` | `uuid=uuid:uuid4`       | Add a `uuid` command that invokes the `uuid4` function in the `uuid` module.                                                      |
| `<name>`                 | `cowsay`                | Add a `cowsay` command for the `cowsay` console script found anywhere in the PEX distributions.                                   |
| `!<name>`                | `!cowsay`               | Exclude all `cowsay` console scripts found in the PEX distributions (For use with `@` and `@<project>`).                          |
| `<name>@<project>`       | `ansible@ansible-core`  | Add an `ansible` command for the `ansible` console script found in the `ansible-core` distributions in the PEX.                   |
| `!<name>@<project>`      | `!ansible@ansible-core` | Exclude the `ansible` console script found in the `ansible-core` distributions in the PEX (For use with `@` and `@ansible-core`). |
| `@<project>`             | `@ansible-core`         | Add a command for all console scripts found in the `ansible-core` distributions in the PEX.                                       |
| `!@<project>`            | `!@ansible-core`        | Exclude all console scripts found in the `ansible-core` distributions in the PEX (For use with `@`).                              |
| `@`                      | `@`                     | Add a command for all console scripts found in all project distributions in the PEX.                                              |

For example, to build a BusyBox with tools both useful and frivolous:
```sh
# Build a PEX scie BusyBox with 3 commands:
:; pex cowsay -c cowsay --inject-args=-t --scie lazy --scie-busybox json=json.tool,uuid=uuid:uuid4,cowsay -otools

# Run the BusyBox to discover what commands it contains:
:; ./tools
Error: Could not determine which command to run.

Please select from the following boot commands:

cowsay
json
uuid

You can select a boot command by setting the SCIE_BOOT environment variable or else by passing it as the 1st argument.

# Use the tools:
:; ./tools uuid
16269f0f-76f5-4374-9da2-e0e873c40835
:; ./tools uuid
00e2584d-a5d3-40d9-9217-9a873fe7cac8
:; echo '{"Hello":"World!"}' | ./tools json
{
    "Hello": "World!"
}

# Install the tools on the $PATH individually for convenient access:
:; mkdir /tmp/bin
:; export PATH=/tmp/bin:$PATH
:; SCIE=install ./tools /tmp/bin
:; ls -1 /tmp/bin/
cowsay
json
uuid
:; which cowsay
/tmp/bin/cowsay
:; cowsay Moo!
  ____
| Moo! |
  ====
    \
     \
       ^__^
       (oo)\_______
       (__)\       )\/\
           ||----w |
           ||     ||
```