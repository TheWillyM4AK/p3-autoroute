"""Bit-level reading/writing — port of scripts/helper/{BitArray,BitReader}.gd.

Bits are stored and packed in LSB-first order (bit 0 = least significant bit),
just like in the original. This is essential for the (de)compressor to be
byte-for-byte compatible with the .rou files.
"""
from __future__ import annotations

from typing import List


class BitArray:
    def __init__(self) -> None:
        self.bits: List[int] = []

    @staticmethod
    def from_number(value: int, length: int = 8) -> "BitArray":
        ba = BitArray()
        for i in range(length):
            ba.bits.append((value >> i) & 0x01)
        return ba

    @staticmethod
    def from_bytes(data: bytes) -> "BitArray":
        ba = BitArray()
        for byte in data:
            for j in range(8):
                ba.bits.append((byte >> j) & 0x01)
        return ba

    def size(self) -> int:
        return len(self.bits)

    def append(self, value: int) -> "BitArray":
        self.bits.append(value & 0x01)
        return self

    def concatenate(self, other: "BitArray") -> "BitArray":
        self.bits.extend(other.bits)
        return self

    def to_bytes(self) -> bytes:
        # Packs LSB-first. Same as the original: a final partial byte is only
        # emitted if its value != 0 (trailing zeros are discarded).
        out = bytearray()
        value = 0
        shift = 0
        for bit in self.bits:
            value += bit << shift
            shift += 1
            if shift == 8:
                out.append(value)
                value = 0
                shift = 0
        if value != 0:
            out.append(value)
        return bytes(out)

    def read_unsigned(self, offset: int, length: int) -> int:
        # Tolerant read: bits past the end count as 0, just like
        # PackedByteArray.decode_u8 in Godot. `to_bytes` discards the trailing
        # zero bits, so decode may request up to 7 nonexistent bits.
        result = 0
        n = len(self.bits)
        for i in range(length):
            idx = offset + i
            if idx < n:
                result += self.bits[idx] << i
        return result


class BitReader:
    def __init__(self, bit_array: BitArray) -> None:
        self.data = bit_array
        self.position = 0

    @staticmethod
    def from_bit_array(bit_array: BitArray) -> "BitReader":
        return BitReader(bit_array)

    def read_unsigned(self, size: int = 8) -> int:
        value = self.data.read_unsigned(self.position, size)
        self.position += size
        return value

    def read_signed(self, size: int = 8) -> int:
        value = self.data.read_unsigned(self.position, size)
        self.position += size
        sign_bit = 1 << (size - 1)
        if value & sign_bit:
            value -= (1 << size)
        return value
