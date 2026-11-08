"""The Vulkan builder must import the complete key-function dependency set without running a build."""
import ast
import hashlib
import struct
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / 'tools'

class BorrowKeyTests(unittest.TestCase):
    def test_real_record_hash_and_spilled_reference(self):
        tree = ast.parse((TOOLS / 'vk_android_build.py').read_text(encoding='utf-8'))
        nodes = []
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == 'borrow_key': nodes.append(node)
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Tuple) and any(isinstance(e, ast.Name) and e.id == 'KEY_FNS' for e in t.elts) for t in node.targets): nodes.append(node)
        ns = {'ast': ast, 'struct': struct, 'hashlib': hashlib, 'SPLIT': str(TOOLS / 'shader_split.py'), 'sys': __import__('sys')}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<key import>', 'exec'), ns)
        key = ns['borrow_key']((0, 0))
        ctl = bytearray(0xd8); ctl[:8] = bytes.fromhex('34127698c9000000')
        struct.pack_into('<I', ctl, 0x44, 32)
        code = bytes(range(32))
        expected = hashlib.sha256(ctl[:0x30] + bytes(4) + ctl[0x34:0x48] + code).hexdigest()[:16]
        self.assertEqual(key(bytes(ctl), code), expected)
        reference = ('\x00code', 'not-opened.bin', 0, len(code), 'hash', expected)
        self.assertEqual(key(bytes(ctl), reference), expected)

if __name__ == '__main__': unittest.main()
