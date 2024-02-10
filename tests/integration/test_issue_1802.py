# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os.path
import subprocess
from textwrap import dedent

import pytest

from pex.common import safe_open
from pex.compatibility import PY2
from pex.typing import TYPE_CHECKING
from testing import run_pex_command

if TYPE_CHECKING:
    from typing import Any


@pytest.mark.skipif(PY2, reason="Example code used to drive test is Python 3 only.")
def test_stderr_not_torn_down(tmpdir):
    # type: (Any) -> None

    exe = os.path.join(str(tmpdir), "exe")
    with safe_open(exe, "w") as fp:
        fp.write(
            dedent(
                """\
                import sys
                import logging
                import atexit
                import logging.handlers
                import queue
                import sys
                import faulthandler

                import absl.app as absl_app
                import absl.logging as absl_logging
                from absl.flags import FLAGS


                def run():
                    print("hello")
                    absl_logging.error("HELP ME")


                def init_sys_logging():
                    root_logger = logging.getLogger()

                    FLAGS.alsologtostderr = True

                    # No limit on queue size.
                    log_queue = queue.Queue(-1)
                    queue_forwarder = logging.handlers.QueueHandler(log_queue)
                    root_logger.addHandler(queue_forwarder)

                    queue_handlers = []

                    # If absl logging is enabled; re-parent it to the queue.
                    absl_handler = absl_logging.get_absl_handler()
                    if absl_handler in root_logger.handlers:
                        root_logger.handlers.remove(absl_handler)
                        queue_handlers.append(absl_handler)

                    queue_log_listener = logging.handlers.QueueListener(
                        log_queue, *queue_handlers, respect_handler_level=True
                    )
                    queue_log_listener.start()

                    atexit.register(queue_log_listener.stop)

                    FLAGS.mark_as_parsed()


                if __name__ == "__main__":
                    absl_logging.set_verbosity(0)
                    absl_logging.use_absl_handler()
                    absl_logging.get_absl_handler().use_absl_log_file()

                    faulthandler.enable()

                    init_sys_logging()

                    def run_wrapper(fn) -> int:
                        absl_app._run_main(lambda args: fn(), sys.argv)
                        return 0

                    sys.exit(run_wrapper(run))
                """
            )
        )
    pex = os.path.join(str(tmpdir), "pex")
    run_pex_command(args=["absl-py==0.10.0", "--exe", exe, "-o", pex]).assert_success()
    process = subprocess.Popen(args=[pex], stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    error = stderr.decode("utf-8")
    assert 0 == process.returncode
    assert "HELP ME" in error
