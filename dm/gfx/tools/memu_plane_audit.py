#!/usr/bin/env python3
"""Evaluate only a converted mesh_plane_store helper, never guest code.

All floats are raw words. Supports only this helper's integer/control-flow
subset and refuses unfamiliar instructions. Useful for comparing real
uploaded modules without game input buffers or physical GPU addresses.
"""
import struct
from pathlib import Path


def instructions(words):
    i = 5
    while i < len(words):
        n, op = words[i] >> 16, words[i] & 65535
        if not n or i + n > len(words):
            raise ValueError("malformed instruction")
        yield op, words[i + 1:i+n]
        i += n


class PlaneHelper:
    def __init__(self, words):
        self.constants, self.variables, self.body, self.params = {}, {}, [], []
        target, inside = None, False
        for op, a in instructions(words):
            if op == 5 and struct.pack(f"<{len(a)-1}I", *a[1:]).split(b"\0", 1)[0] == b"mesh_plane_store":
                target = a[0]
            elif op == 43:
                self.constants[a[1]] = a[2]
            elif op in (41, 42):
                self.constants[a[1]] = op == 41
            elif op == 44:
                self.constants[a[1]] = tuple(self.constants[i] for i in a[2:])
            elif op == 59 and not inside:
                self.variables[a[1]] = a[2]
            if op == 54:
                inside = a[1] == target
            elif inside and op == 55:
                self.params.append(a[1])
            elif inside and op == 56:
                inside = False
            elif inside:
                self.body.append((op, a))
        if len(self.params) != 2 or not self.body:
            raise ValueError("not the two-word mesh-plane helper")
        self.labels = {a[0]: i for i, (op, a) in enumerate(self.body) if op == 248}

    @classmethod
    def read(cls, path):
        data = Path(path).read_bytes()
        return cls(struct.unpack(f"<{len(data)//4}I", data))

    def run(self, word, value, base=4096):
        v = dict(self.constants)
        memory, written = {}, {}
        for i, sc in self.variables.items():
            v[i] = (i, ())
            if sc == 6:
                memory[(i, ())] = base
        v.update(zip(self.params, (word & 0xffffffff, value & 0xffffffff)))
        pc, steps, branches = 0, 0, 0
        while pc < len(self.body):
            op, a = self.body[pc]; pc += 1; steps += 1
            if steps > 2000:
                raise ValueError("unexpected helper loop")
            if op in (248, 247):
                continue
            if op == 250:
                branches += 1; pc = self.labels[a[1] if v[a[0]] else a[2]]
            elif op == 249:
                pc = self.labels[a[0]]
            elif op == 253:
                return written, steps, branches
            elif op == 124:
                v[a[1]] = v[a[2]]
            elif op in (65, 66):
                root, indices = v[a[2]]
                v[a[1]] = root, indices + tuple(v[i] for i in a[3:])
            elif op == 61:
                v[a[1]] = memory[v[a[2]]]
            elif op == 62:
                written[v[a[0]]] = v[a[1]]; memory[v[a[0]]] = v[a[1]]
            elif op == 77:
                v[a[1]] = v[a[2]][v[a[3]]]
            elif op == 169:
                v[a[1]] = v[a[3] if v[a[2]] else a[4]]
            elif op in (128, 132, 134, 137, 170, 176, 194, 196, 199):
                x, y = v[a[2]], v[a[3]]
                v[a[1]] = {128: lambda: (x+y) & 0xffffffff, 132: lambda: (x*y) & 0xffffffff,
                            134: lambda: x//y, 137: lambda: x%y, 170: lambda: x == y,
                            176: lambda: x < y, 194: lambda: x >> y,
                            196: lambda: (x << y) & 0xffffffff, 199: lambda: x & y}[op]()
            else:
                raise ValueError(f"unsupported helper instruction {op}")
        raise ValueError("helper fell through without return")
