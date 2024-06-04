# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import sys

from pex.pep_440 import Version
from pex.specifier_sets import ExcludedRange, LowerBound, Range, UpperBound, as_range, includes
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


def test_range_simplification():
    # type: () -> None

    # No simplification.
    assert (
        Range(
            lower=LowerBound(Version("2.7"), inclusive=True),
            upper=UpperBound(Version("3.13"), inclusive=False),
            excludes=tuple(
                [
                    ExcludedRange(
                        lower=LowerBound(Version("3"), inclusive=True),
                        upper=UpperBound(Version("3.1"), inclusive=False),
                    ),
                    ExcludedRange(
                        lower=LowerBound(Version("3.1"), inclusive=True),
                        upper=UpperBound(Version("3.2"), inclusive=False),
                    ),
                    ExcludedRange(
                        lower=LowerBound(Version("3.2"), inclusive=True),
                        upper=UpperBound(Version("3.3"), inclusive=False),
                    ),
                    ExcludedRange(
                        lower=LowerBound(Version("3.3"), inclusive=True),
                        upper=UpperBound(Version("3.4"), inclusive=False),
                    ),
                    ExcludedRange(
                        lower=LowerBound(Version("3.4"), inclusive=True),
                        upper=UpperBound(Version("3.5"), inclusive=False),
                    ),
                ]
            ),
        )
    ) == as_range(">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,<3.13")

    # Bounds narrowing and exclude trimming.
    assert (
        Range(
            lower=LowerBound(Version("3"), inclusive=True),
            upper=UpperBound(Version("6"), inclusive=False),
            excludes=tuple(
                [
                    ExcludedRange(
                        lower=LowerBound(Version("4"), inclusive=True),
                        upper=UpperBound(Version("5"), inclusive=False),
                    )
                ]
            ),
        )
        == as_range(">0,!=1.*,>=2,!=2.*,!=4.*,<6,!=7.*,<42")
    )


def test_includes():
    # type: () -> None

    assert includes("", "")
    assert includes("", "==1")
    assert includes("", ">1")
    assert includes("", ">=1")
    assert includes("", "<1")
    assert includes("", "<=1")
    assert includes("", "==1.*")
    assert includes("", "!=1.*")
    assert includes("", "~=1.2")

    assert not includes("", "===bob")

    # Arbitrary equality: versions treated as strings and must match exactly.
    assert includes("===bob", "===bob")
    assert not includes("===fred", "===bob")
    assert includes("===1", "===1")
    assert not includes("===1.0", "===1")
    assert not includes("===1", "===1.0")

    # Compatible X.Y: should be equivalent to >=X.Y,==X.* or, equivalently >=X.Y,<X+1.
    assert includes("~=1.2", ">=1.2,==1.*")
    assert includes("~=1.2", ">=1.2,<2")
    assert includes("~=1.2", ">=1.3,<2")
    assert includes("~=1.2", ">=1.2,<1.9")
    assert includes("~=1.2", "==1.2.*")
    assert includes("~=1.2", "==1.3.*")
    assert includes("~=1.2", "==1.3")

    assert not includes("~=1.2", "==1.1")
    assert not includes("~=1.2", "==2")
    assert not includes("~=1.2", "==1.*")
    assert not includes("~=1.2", "")

    assert includes("~=1.2.3", ">=1.2.3,==1.2.*")
    assert includes("~=1.2.3", ">=1.2.3,<1.3")
    assert includes("~=1.2.3", "==1.2.3")
    assert includes("~=1.2.3", "==1.2.13")

    assert not includes("~=1.2.3", "==1.3")
    assert not includes("~=1.2.3", "==1.2.2")

    # Equality: missing components should be 0-filled for comparison.
    assert includes("==1", "==1")
    assert includes("==1.0", "==1")
    assert includes("==1", "==1.0")

    assert not includes("==1", "==1.0.1")
    assert not includes("==1", "==0.9")
    assert not includes("==1", "==1.*")

    assert includes("!=2", "==1")
    assert includes("!=2", "==3")
    assert includes("!=2", "==2.1")
    assert includes("!=2", "<2")
    assert includes("!=2", ">2")
    assert includes("!=2", ">2,<2.1")

    assert not includes("!=2", "==2")
    assert not includes("!=2", "==2.0")
    assert not includes("!=2", "~=2.0")
    assert not includes("!=2", ">=1,<3")

    # N.B.: The LHS is the empty range, and we make the policy call that no range contains the
    # empty range.
    assert not includes("!=2", ">2,<=2")
    assert not includes("!=2", ">2,<2")
    assert not includes("!=2", ">=2,<2")
    # And vice-versa, which involves no policy call.
    assert not includes(">2,<2", "")
    assert not includes(">2,<2", "==2")

    assert not includes("!=1", "")

    assert includes(">1", ">1")
    assert includes(">1.0", ">1")
    assert includes(">1", ">1.0")

    # Newer versions of vendored packaging used for Python>=3.7 enforce the .* suffix is only used
    # with == and != operators; so we don't test for those versions.
    if sys.version_info[:2] < (3, 7):
        assert includes(">1.*", ">1")
        assert includes(">1.*", ">1.0")
        assert includes(">1", ">1.*")
        assert includes(">1.0", ">1.*")
        assert includes(">1.*", ">1.*")

    complex_requirement = ">=2.7,!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,<3.13"
    assert includes(complex_requirement, "==2.7")
    assert includes(complex_requirement, "==2.7.18")
    assert includes(complex_requirement, "==3.5")
    assert includes(complex_requirement, "==3.12.3")

    assert not includes(complex_requirement, "==2.6")
    assert not includes(complex_requirement, "==3")
    assert not includes(complex_requirement, "==3.0")
    assert not includes(complex_requirement, "==3.0.0")
    assert not includes(complex_requirement, "==3.0.1")
    assert not includes(complex_requirement, "==3.1")
    assert not includes(complex_requirement, "==3.2")
    assert not includes(complex_requirement, "==3.3")
    assert not includes(complex_requirement, "==3.4")
    assert not includes(complex_requirement, "==3.4.99")
    assert not includes(complex_requirement, "==3.13")
    assert not includes(complex_requirement, ">=2.6,<3.14")

    assert includes("", "!=2.*")
    assert not includes("==2", "!=2.*")
    assert not includes(">2", "!=2.*")
    assert not includes("<=2", "!=2.*")

    assert not includes(">=1,!=2,<4", ">=1,<4")
    assert includes(">=1,<4", ">=1,!=2,<4")
    assert not includes(">=1,!=2,!=3,<4", ">=1,!=2,<4")
    assert includes("!=2", ">=1,!=2,<4")

    assert includes(">=2,!=3.*,<4", ">=1,!=1.*,<3")
    assert includes(">=2,!=3.*,<4", ">=1,!=1.*,<3,>0,<6")
    assert includes(">=2,!=3.*,<4,>=1,<=42", ">=1,!=1.*,<3")
