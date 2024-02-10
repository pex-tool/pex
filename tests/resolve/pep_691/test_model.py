# Copyright 2022 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import hashlib
import itertools
from collections import defaultdict

import pytest

from pex.resolve.pep_691.model import File
from pex.resolve.resolved_requirement import Fingerprint
from pex.sorted_tuple import SortedTuple
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import DefaultDict, List, Tuple


def file(**hashes):
    # type (**str) -> File
    return File(
        filename="foo.tar.gz",
        url="https://files.example.org/foo.tar.gz",
        hashes=SortedTuple(Fingerprint(algorithm, hash_) for algorithm, hash_ in hashes.items()),
    )


def test_select_fingerprint_none():
    # type: () -> None

    assert file().select_fingerprint() is None


@pytest.mark.parametrize("guaranteed_algorithm", sorted(hashlib.algorithms_guaranteed))
def test_select_fingerprint_single_guaranteed(guaranteed_algorithm):
    # type: (str) -> None

    hashes = {guaranteed_algorithm: "hash_hex_value"}
    assert (
        Fingerprint(algorithm=guaranteed_algorithm, hash="hash_hex_value")
        == file(**hashes).select_fingerprint()
    )


def test_select_fingerprint_sha256_trumps_all_others():
    # type: () -> None

    hashes = {algorithm: "hash_hex_value" for algorithm in hashlib.algorithms_available}
    hashes["sha256"] = "preferred"
    assert Fingerprint(algorithm="sha256", hash="preferred") == file(**hashes).select_fingerprint()


def test_select_fingerpint_none_guaranteed():
    # type: () -> None

    hashes = {
        algorithm: "hash_hex_value"
        for algorithm in set(hashlib.algorithms_available) - set(hashlib.algorithms_guaranteed)
    }
    assert file(**hashes).select_fingerprint() is None


@pytest.mark.parametrize(
    "guaranteed_algorithm_pair",
    [
        pytest.param(
            (one, two),
            id="{one}[{one_size}] vs {two}[{two_size}]".format(
                one=one,
                one_size=hashlib.new(one).digest_size,
                two=two,
                two_size=hashlib.new(two).digest_size,
            ),
        )
        for one, two in sorted(
            itertools.combinations(set(hashlib.algorithms_guaranteed) - {"sha256"}, 2)
        )
    ],
)
def test_select_fingerprint_ranking(guaranteed_algorithm_pair):
    # type: (Tuple[str, str]) -> None

    algorithms_by_size = defaultdict(list)  # type: DefaultDict[int, List[str]]
    hashes = {}
    for algorithm in guaranteed_algorithm_pair:
        algorithms_by_size[hashlib.new(algorithm).digest_size].append(algorithm)
        hashes[algorithm] = "{algorithm}_hash_hex_value".format(algorithm=algorithm)

    # We expect algorithms are preferred for greatest digest size and then tie-broken by alphabetic
    # order.
    expected_algorithm = sorted(algorithms_by_size[max(algorithms_by_size)])[0]
    expected_hash = hashes[expected_algorithm]

    assert (
        Fingerprint(algorithm=expected_algorithm, hash=expected_hash)
        == file(**hashes).select_fingerprint()
    )
