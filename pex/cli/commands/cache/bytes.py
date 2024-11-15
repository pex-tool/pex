# Copyright 2024 Pex project contributors.
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import

import math

from pex.enum import Enum
from pex.typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Optional, Union

    import attr  # vendor:skip
else:
    from pex.third_party import attr


class ByteUnits(Enum["ByteUnits.Value"]):
    class Value(Enum.Value):
        def __init__(
            self,
            value,  # type: str
            multiple,  # type: float
            singular=None,  # type: Optional[str]
        ):
            # type: (...) -> None
            Enum.Value.__init__(self, value)
            self.multiple = multiple
            self._singular = singular or value

        def render(self, total_bytes):
            # type: (Union[int, float]) -> str
            return self._singular if round(total_bytes) == 1 else self.value

    BYTES = Value("bytes", 1.0, singular="byte")
    KB = Value("kB", 1000 * BYTES.multiple)
    MB = Value("MB", 1000 * KB.multiple)
    GB = Value("GB", 1000 * MB.multiple)
    TB = Value("TB", 1000 * GB.multiple)
    PB = Value("PB", 1000 * TB.multiple)


ByteUnits.seal()


@attr.s(frozen=True)
class ByteAmount(object):
    @classmethod
    def bytes(cls, total_bytes):
        # type: (int) -> ByteAmount
        return cls(total_bytes=total_bytes, unit=ByteUnits.BYTES)

    @classmethod
    def kilobytes(cls, total_bytes):
        # type: (int) -> ByteAmount
        return cls(total_bytes=total_bytes, unit=ByteUnits.KB)

    @classmethod
    def megabytes(cls, total_bytes):
        # type: (int) -> ByteAmount
        return cls(total_bytes=total_bytes, unit=ByteUnits.MB)

    @classmethod
    def gigabytes(cls, total_bytes):
        # type: (int) -> ByteAmount
        return cls(total_bytes=total_bytes, unit=ByteUnits.GB)

    @classmethod
    def terabytes(cls, total_bytes):
        # type: (int) -> ByteAmount
        return cls(total_bytes=total_bytes, unit=ByteUnits.TB)

    @classmethod
    def petabytes(cls, total_bytes):
        # type: (int) -> ByteAmount
        return cls(total_bytes=total_bytes, unit=ByteUnits.PB)

    @classmethod
    def human_readable(cls, total_bytes):
        # type: (int) -> ByteAmount

        def select_unit():
            for unit in ByteUnits.values():
                if total_bytes < (1000 * unit.multiple):
                    return unit
            return ByteUnits.PB

        return cls(total_bytes=total_bytes, unit=select_unit())

    @classmethod
    def for_unit(cls, unit):
        # type: (ByteUnits.Value) -> Callable[[int], ByteAmount]
        if ByteUnits.BYTES is unit:
            return cls.bytes
        elif ByteUnits.KB is unit:
            return cls.kilobytes
        elif ByteUnits.MB is unit:
            return cls.megabytes
        elif ByteUnits.GB is unit:
            return cls.gigabytes
        elif ByteUnits.TB is unit:
            return cls.terabytes
        elif ByteUnits.PB is unit:
            return cls.petabytes
        raise ValueError(
            "The unit {unit} has no known corresponding byte amount function".format(unit=unit)
        )

    total_bytes = attr.ib()  # type: int
    unit = attr.ib()  # type: ByteUnits.Value

    def __str__(self):
        # type: () -> str
        amount = self.total_bytes / self.unit.multiple
        integer_part = math.trunc(amount)
        if self.unit is ByteUnits.BYTES or integer_part // 100 > 0:
            return "{amount} {unit}".format(amount=round(amount), unit=self.unit.render(amount))
        elif integer_part // 10 > 0:
            return "{amount:.1f} {unit}".format(amount=amount, unit=self.unit.render(amount))
        elif integer_part > 0:
            return "{amount:.2f} {unit}".format(amount=amount, unit=self.unit.render(amount))
        else:
            return "{amount:.3f} {unit}".format(amount=amount, unit=self.unit.render(amount))
