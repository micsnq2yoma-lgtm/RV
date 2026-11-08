"""Protocol v1: explicitly little endian, no native alignment."""
import math
import struct

STATE = struct.Struct('<4sId15dII')
COMMAND = struct.Struct('<4sIII8d')
assert STATE.size == 144 and COMMAND.size == 80


def command_values(packet):
    if len(packet) != COMMAND.size:
        raise ValueError('command length')
    magic, seq, ack, mode, *values = COMMAND.unpack(packet)
    if magic != b'RVC1' or mode not in (0, 1) or not all(map(math.isfinite, values)):
        raise ValueError('invalid command')
    return seq, ack, mode, values
