"""Data structures used to parse the response from the Elliptec devices."""

import construct


class HardwareInfoAdapter(construct.Adapter):
    def _decode(self, obj, context, path):
        # obj is a 2-character string containing hex digits (e.g. "81")
        value = int(obj, base=16)  # convert "81" to integer 0x81 (129 decimal)
        thread_type = (value >> 7) & 0x01  # most significant bit
        hardware_release = value & 0x7F  # lower 7 bits
        return (thread_type, hardware_release)

    def _encode(self, obj, context, path):
        # obj is a tuple: (thread_type, hardware_release)
        thread_type, hardware_release = obj
        value = ((thread_type & 0x01) << 7) | (hardware_release & 0x7F)
        # format back into a 2-character uppercase hex string padded with 0
        return f"{value:02X}"


class StringIntegerAdapter(construct.Adapter):
    def _decode(self, obj, context, path):
        return int(obj)

    def _encode(self, obj, context, path):
        return str(obj)


class HexStringIntegerAdapter(construct.Adapter):
    def _decode(self, obj, context, path):
        return int(obj, base=16)

    def _encode(self, obj, context, path):
        return f"{obj:02X}"


Word = construct.Int16ub
Short = construct.Int16sb
Dword = construct.Int32ub
Long = construct.Int32sb
Single = construct.Float32b

MotorInfo = construct.Struct(
    "header"
    / construct.BitStruct(
        "reserved" / construct.BitsInteger(4),
        "motor" / construct.BitsInteger(4),
    ),
    "current" / Word,
    construct.Padding(4),
    "forward_period" / Word,
    "backward_period" / Word,
)


Info = construct.Struct(
    "ell" / HexStringIntegerAdapter(construct.PaddedString(2, "utf8")),
    "sn" / construct.PaddedString(8, "utf8"),
    "year" / construct.PaddedString(4, "utf8"),
    "firmware" / construct.PaddedString(2, "utf8"),
    "hardware" / HardwareInfoAdapter(construct.PaddedString(2, "ascii")),
    "travel" / HexStringIntegerAdapter(construct.PaddedString(4, "utf8")),
    "pulse" / StringIntegerAdapter(construct.PaddedString(8, "utf8")),
)
