"""(De)compressor for the .rou format — port of scripts/helper/Compressor.gd.

`encode` ALWAYS produces the "uncompressed" stream (each byte preceded by a
0 bit). The game accepts that format just as it accepts the compressed one.
`decode` understands both: literal chunks and LZ77-style back-references (the
files saved by the game come compressed).

The tables are transcribed VERBATIM from the original to maintain byte-for-byte
compatibility; in particular `BITMASK_TABLE_2[13]` is 0x1ff (which is almost
certainly a historical typo for 0x1fff), but it is kept identical to upstream
because it is never triggered with real route files (small routes).
"""
from __future__ import annotations

from .bitstream import BitArray, BitReader

# decompress_table: (length_in_bits, base_value)
DECOMPRESS_FIELD0 = [1, 2, 3, 4, 5, 6, 7, 8]
DECOMPRESS_FIELD4 = [0x00, 0x02, 0x06, 0x0e, 0x1e, 0x3e, 0x7e, 0xfe]

BITMASK_TABLE_1 = [0x01, 0x03, 0x07, 0x0f, 0x1f, 0x3f, 0x7f, 0xff]

BITMASK_TABLE_2 = [
    0x00, 0x01, 0x03, 0x07, 0x0f, 0x1f, 0x3f, 0x7f,
    0xff, 0x1ff, 0x3ff, 0x7ff, 0xfff, 0x1ff, 0x3fff, 0x7fff,
    0xffff, 0x1ffff, 0x3ffff, 0x7ffff, 0xfffff, 0x1fffff, 0x3fffff, 0x7fffff,
    0xffffff, 0x1ffffff, 0x3ffffff, 0x7ffffff, 0xfffffff, 0x1fffffff,
    0x3FFFFFFF, 0x7FFFFFFF,
]


def encode(data: bytes) -> bytes:
    """Serializes `data` into the .rou framing, all as literals."""
    bit_array = BitArray()
    bit_array.concatenate(BitArray.from_number(len(data), 32))
    for byte in data:
        bit_array.append(0)
        bit_array.concatenate(BitArray.from_number(byte, 8))
    return bit_array.to_bytes()


def decode(data: bytes) -> bytes:
    """Decompresses a .rou (literals and/or LZ77 back-references)."""
    reader = BitReader.from_bit_array(BitArray.from_bytes(data))
    length = reader.read_unsigned(32)
    output = bytearray()
    while len(output) < length:
        if reader.read_unsigned(1) == 1:
            # Compressed chunk (back-reference).
            chunk_type = reader.read_unsigned(3)
            chunk_length = DECOMPRESS_FIELD0[chunk_type]
            chunk = reader.read_unsigned(chunk_length)
            negated_value = DECOMPRESS_FIELD4[chunk_type] + (BITMASK_TABLE_1[chunk_type] & chunk)
            offset = ~negated_value  # negative: distance backwards
            elements = 1
            output_elements = 2
            while True:
                elements += 1
                compressed_data = reader.read_unsigned(elements)
                compressed_elements = BITMASK_TABLE_1[elements] & compressed_data
                output_elements += compressed_elements
                if compressed_elements != BITMASK_TABLE_2[elements]:
                    break
            repeated_value_index = len(output) + offset
            for i in range(output_elements):
                # Copy that may overlap with recently added bytes (LZ77).
                output.append(output[repeated_value_index + i])
        else:
            # Literal chunk.
            output.append(reader.read_unsigned(8))
    return bytes(output)
