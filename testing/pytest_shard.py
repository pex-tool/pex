# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, print_function

import json
import os.path
from collections import defaultdict
from typing import DefaultDict, Tuple

from _pytest.config import create_terminal_writer, hookimpl  # type: ignore[import]
from _pytest.reports import TestReport  # type: ignore[import]

from pex.common import pluralize
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Dict, List

    import attr  # vendor:skip
    from _pytest import nodes  # type: ignore[import]
    from _pytest.config import Config  # type: ignore[import]
    from _pytest.config.argparsing import Parser  # type: ignore[import]
    from _pytest.terminal import TerminalReporter  # type: ignore[import]
else:
    from pex.third_party import attr


DEFAULT_TIMINGS_PATH = ".test_timings"


@attr.s(frozen=True)
class Plugin(object):
    config = attr.ib()  # type: Config

    @property
    def terminal_reporter(self):
        # type: () -> TerminalReporter
        return self.config.pluginmanager.get_plugin("terminalreporter")


@attr.s(frozen=True)
class RecordTestTimings(Plugin):
    @classmethod
    def load_timings(cls, timings_path=DEFAULT_TIMINGS_PATH):
        # type: (str) -> Dict[str, float]
        if not os.path.exists(timings_path):
            return {}
        with open(timings_path) as fp:
            return json.load(fp)  # type: ignore[no-any-return]

    @classmethod
    def create(
        cls,
        config,  # type: Config
        timings_path=DEFAULT_TIMINGS_PATH,  # type: str
        clear_timings=False,  # type: bool
    ):
        # type: (...) -> RecordTestTimings
        return cls(
            config=config,
            seed_timings=tuple(() if clear_timings else cls.load_timings(timings_path).items()),
            timings_path=timings_path,
        )

    seed_timings = attr.ib()  # type: Tuple[Tuple[str, float], ...]
    timings_path = attr.ib(default=DEFAULT_TIMINGS_PATH)  # type: str

    def pytest_sessionfinish(self):
        # type: () -> None

        test_times = defaultdict(lambda: 0)  # type: DefaultDict[str, float]
        for test_reports in self.terminal_reporter.stats.values():
            for test_report in test_reports:
                if isinstance(test_report, TestReport) and test_report.passed:
                    test_times[test_report.nodeid] += test_report.duration

        timings = dict(self.seed_timings)
        for test, timing in test_times.items():
            timings[test] = timing

        with open(self.timings_path, "w") as fp:
            json.dump(timings, fp, sort_keys=True, indent=2)

        self.terminal_reporter.write_line(
            "pex-record-timings: Recorded {count} test {timings} at {timings_path}".format(
                count=len(test_times),
                timings=pluralize(test_times, "timing"),
                timings_path=self.timings_path,
            ),
            cyan=True,
        )


@attr.s(frozen=True)
class Shard(object):
    @classmethod
    def parse(cls, spec):
        # type: (str) -> Shard
        slot, total_slots = spec.split("/", 1)
        return cls(slot=int(slot), total_slots=int(total_slots))

    slot = attr.ib()  # type: int
    total_slots = attr.ib()  # type: int

    def __attrs_post_init__(self):
        # type: () -> None
        if self.slot <= 0:
            raise ValueError("The shard number must be >=1; given: {slot}".format(slot=self.slot))
        if self.total_slots < self.slot:
            raise ValueError(
                "The total shard count must be >={slot}; given: {total_slots}".format(
                    slot=self.slot, total_slots=self.total_slots
                )
            )

    def __str__(self):
        # type: () -> str
        return "{slot}/{total_slots}".format(slot=self.slot, total_slots=self.total_slots)


@attr.s
class ShardTests(Plugin):
    @classmethod
    def create(
        cls,
        config,  # type: Config
        shard,  # type: Shard
        timings_path=DEFAULT_TIMINGS_PATH,  # type: str
    ):
        # type: (...) -> ShardTests
        timings = RecordTestTimings.load_timings(timings_path=timings_path)
        return cls(config=config, shard=shard, timings=tuple(timings.items()))

    shard = attr.ib()  # type: Shard
    timings = attr.ib()  # type: Tuple[Tuple[str, float], ...]

    @hookimpl(trylast=True)
    def pytest_collection_modifyitems(
        self,
        config,  # type: Config
        items,  # type: List[nodes.Item]
    ):
        # type: (...) -> None

        timing_by_test = {test: timing for test, timing in self.timings}
        average_timing = (
            sum(timing_by_test.values()) / len(timing_by_test) if timing_by_test else 0.0
        )
        timing_by_item = {item: timing_by_test.get(item.nodeid, average_timing) for item in items}

        total_time_by_slot = {}  # type: Dict[int, float]
        deselected_tests = []  # type: List[nodes.Item]
        selected_tests = []  # type: List[nodes.Item]
        for test, timing in sorted(
            timing_by_item.items(), key=lambda entry: (entry[1], entry[0].nodeid), reverse=True
        ):
            if total_time_by_slot:
                slot, _ = min(total_time_by_slot.items(), key=lambda entry: (entry[1], entry[0]))
            else:
                for slot in range(1, self.shard.total_slots + 1):
                    total_time_by_slot[slot] = 0.0
                slot = 1

            total_time_by_slot[slot] += timing
            if self.shard.slot == slot:
                selected_tests.append(test)
            else:
                deselected_tests.append(test)

        items[:] = selected_tests
        config.hook.pytest_deselected(items=deselected_tests)

        self.terminal_reporter.write_line(
            "pex-shard-tests: Selected {count} {tests} for {shard} with an estimated run "
            "time of {minutes:.2f} minutes".format(
                count=len(items),
                tests=pluralize(items, "test"),
                shard=self.shard,
                minutes=total_time_by_slot[self.shard.slot] / 60,
            ),
            cyan=True,
        )


def pytest_addoption(parser):
    # type: (Parser) -> None
    group = parser.getgroup(
        "Split tests into shards whose execution time is about the same. Run with `--save-timings` "
        "to store information about test execution times."
    )
    group.addoption(
        "--timings-path",
        dest="timings_path",
        default=DEFAULT_TIMINGS_PATH,
        help="The path to store and read test timings from.",
    )
    group.addoption(
        "--record-timings",
        dest="record_timings",
        action="store_true",
        help="Record test timings to `--timings-path`.",
    )
    group.addoption(
        "--clear-timings",
        dest="clear_timings",
        action="store_true",
        help=(
            "Remove any prior test timings for tests which are not present while running tests "
            "with `--record-timings`."
        ),
    )
    group.addoption(
        "--shard",
        dest="shard",
        type=Shard.parse,
        help=(
            "Shard tests. Values take the form M/N where M is the shard to pick of N total shards. "
            "M numbering is 1-based. For example, `--shard 1/3` means to shard three ways and pick "
            "the 1st shard, `--shard 2/3` picks the 2nd shard and `--shard 3/3 the third."
        ),
    )


def pytest_configure(config):
    # type: (Config) -> None

    if config.option.record_timings:
        config.pluginmanager.register(
            RecordTestTimings.create(
                config=config,
                timings_path=config.option.timings_path,
                clear_timings=config.option.clear_timings,
            ),
            "pex-record-test-timings-plugin",
        )

    if config.option.shard:
        config.pluginmanager.register(
            ShardTests.create(
                config=config, shard=config.option.shard, timings_path=config.option.timings_path
            ),
            "pex-shard-tests-plugin",
        )
