#!/usr/bin/env python3
"""
CPython 3.13 Opcode Scrambling Script

Scrambles all opcode values in a CPython 3.13 source tree so that the
bytecode appears fully randomized (e.g., CACHE is no longer 0).

Two scrambling modes:
  1. Reversal (default): new_value = 254 - old_value (deterministic)
  2. Random shuffle (--seed N): uses a seeded random permutation

Usage:
    python scramble_opcodes.py <cpython_source_root>
    python scramble_opcodes.py <cpython_source_root> --seed 42
    python scramble_opcodes.py <cpython_source_root> --seed 12345
"""

import os
import re
import sys
import random


def parse_opcode_ids_h(filepath):
    """Parse Include/opcode_ids.h to extract opcode name -> value mappings."""
    opcodes = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'#define\s+(\w+)\s+(\d+)', line.strip())
            if m:
                name = m.group(1)
                value = int(m.group(2))
                if name in ('HAVE_ARGUMENT', 'MIN_INSTRUMENTED_OPCODE', 'NB_OPARG_LAST'):
                    continue
                if name.startswith('NB_'):
                    continue
                opcodes[name] = value
    return opcodes


def parse_opcode_metadata_py(filepath):
    """Parse Lib/_opcode_metadata.py to extract opmap and specialized_opmap."""
    namespace = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    exec(content, namespace)
    return {
        'opmap': namespace['opmap'],
        '_specialized_opmap': namespace['_specialized_opmap'],
        '_specializations': namespace['_specializations'],
        'HAVE_ARGUMENT': namespace['HAVE_ARGUMENT'],
        'MIN_INSTRUMENTED_OPCODE': namespace['MIN_INSTRUMENTED_OPCODE'],
    }


def compute_reversed_mapping(opcodes):
    """Reversal: real opcodes 0-254 -> 254-0, pseudo 256-267 -> 267-256."""
    MAX_REAL = 254
    PSEUDO_BASE = 256
    PSEUDO_MAX = 267
    new_opcodes = {}
    for name, value in opcodes.items():
        if value <= MAX_REAL:
            new_opcodes[name] = MAX_REAL - value
        elif value >= PSEUDO_BASE:
            new_opcodes[name] = (PSEUDO_BASE + PSEUDO_MAX) - value
        else:
            raise ValueError(f"Unexpected opcode value {value} for {name}")
    return new_opcodes


def compute_random_mapping(opcodes, seed):
    """Random shuffle: permute real opcodes within 0-254, pseudo within 256-267."""
    MAX_REAL = 254
    PSEUDO_BASE = 256
    PSEUDO_MAX = 267

    rng = random.Random(seed)

    # Separate real and pseudo opcodes
    real_names = [n for n, v in opcodes.items() if v <= MAX_REAL]
    pseudo_names = [n for n, v in opcodes.items() if v >= PSEUDO_BASE]

    # Shuffle target values
    real_values = list(range(MAX_REAL + 1))
    rng.shuffle(real_values)
    pseudo_values = list(range(PSEUDO_BASE, PSEUDO_MAX + 1))
    rng.shuffle(pseudo_values)

    new_opcodes = {}
    for name, value in opcodes.items():
        if value <= MAX_REAL:
            idx = [n for n, v in opcodes.items() if v <= MAX_REAL].index(name)
            new_opcodes[name] = real_values[idx]
        elif value >= PSEUDO_BASE:
            idx = [n for n, v in opcodes.items() if v >= PSEUDO_BASE].index(name)
            new_opcodes[name] = pseudo_values[idx]
        else:
            raise ValueError(f"Unexpected opcode value {value} for {name}")
    return new_opcodes


def write_opcode_ids_h(filepath, new_opcodes):
    """Write updated Include/opcode_ids.h with new opcode values."""
    # Re-parse to get original values for HAVE_ARGUMENT calculation
    original_opcodes = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            m = re.match(r'#define\s+(\w+)\s+(\d+)', line.strip())
            if m:
                name = m.group(1)
                value = int(m.group(2))
                if name not in ('HAVE_ARGUMENT', 'MIN_INSTRUMENTED_OPCODE',
                                'NB_OPARG_LAST') and not name.startswith('NB_'):
                    original_opcodes[name] = value

    orig_have_argument = 44
    min_has_arg = 255
    for name, orig_val in original_opcodes.items():
        if orig_val >= orig_have_argument:
            new_val = new_opcodes[name]
            if new_val < min_has_arg:
                min_has_arg = new_val

    min_instrumented = 255
    for name, orig_val in original_opcodes.items():
        if name.startswith('INSTRUMENTED_'):
            new_val = new_opcodes[name]
            if new_val < min_instrumented:
                min_instrumented = new_val

    new_lines = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            m = re.match(r'#define\s+(\w+)\s+(\d+)', stripped)
            if m:
                name = m.group(1)
                if name in ('HAVE_ARGUMENT',):
                    new_lines.append(f'#define HAVE_ARGUMENT'
                                     f'{"".ljust(36)}{min_has_arg}\n')
                    continue
                elif name in ('MIN_INSTRUMENTED_OPCODE',):
                    new_lines.append(f'#define MIN_INSTRUMENTED_OPCODE'
                                     f'{"".ljust(24)}{min_instrumented}\n')
                    continue
                elif name.startswith('NB_') or name == 'NB_OPARG_LAST':
                    new_lines.append(line)
                    continue
                elif name in new_opcodes:
                    padding = 40 - len(name) - 9
                    if padding < 1:
                        padding = 1
                    new_lines.append(f'#define {name}'
                                     f'{" " * padding}{new_opcodes[name]}\n')
                    continue
            new_lines.append(line)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)


def write_opcode_metadata_py(filepath, new_opcodes, metadata):
    """Write updated Lib/_opcode_metadata.py with new opcode values."""
    new_opmap = {}
    for name, value in metadata['opmap'].items():
        if name in new_opcodes:
            new_opmap[name] = new_opcodes[name]
        else:
            new_opmap[name] = value

    new_specialized_opmap = {}
    for name, value in metadata['_specialized_opmap'].items():
        if name in new_opcodes:
            new_specialized_opmap[name] = new_opcodes[name]
        else:
            new_specialized_opmap[name] = value

    orig_have_argument = metadata['HAVE_ARGUMENT']
    min_has_arg = 255
    for name, orig_val in metadata['opmap'].items():
        if orig_val >= orig_have_argument:
            new_val = new_opcodes.get(name, orig_val)
            if new_val < min_has_arg:
                min_has_arg = new_val

    min_instrumented = 255
    for name, orig_val in metadata['opmap'].items():
        if name.startswith('INSTRUMENTED_'):
            new_val = new_opcodes.get(name, orig_val)
            if new_val < min_instrumented:
                min_instrumented = new_val

    lines = []
    lines.append('# This file is generated by Tools/cases_generator/py_metadata_generator.py')
    lines.append('# from:')
    lines.append('#   Python/bytecodes.c')
    lines.append('# Do not edit!')
    lines.append('')

    lines.append('_specializations = {')
    for parent, children in metadata['_specializations'].items():
        lines.append(f'    "{parent}": [')
        for child in children:
            lines.append(f'        "{child}",')
        lines.append('    ],')
    lines.append('}')
    lines.append('')

    lines.append('_specialized_opmap = {')
    for name in sorted(new_specialized_opmap.keys(), key=lambda x: new_specialized_opmap[x]):
        lines.append(f"    '{name}': {new_specialized_opmap[name]},")
    lines.append('}')
    lines.append('')

    lines.append('opmap = {')
    for name in sorted(new_opmap.keys(), key=lambda x: new_opmap[x]):
        lines.append(f"    '{name}': {new_opmap[name]},")
    lines.append('}')
    lines.append('')

    lines.append(f'HAVE_ARGUMENT = {min_has_arg}')
    lines.append(f'MIN_INSTRUMENTED_OPCODE = {min_instrumented}')
    lines.append('')

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def update_extra_cases(filepath, new_opcodes):
    """Update EXTRA_CASES in pycore_opcode_metadata.h with new unused values."""
    used_values = set()
    for name, value in new_opcodes.items():
        if value <= 254:
            used_values.add(value)

    gaps = []
    for v in range(256):
        if v not in used_values:
            gaps.append(v)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    extra_cases_lines = []
    for v in gaps:
        extra_cases_lines.append(f'    case {v}: \\')

    extra_cases_str = '#define EXTRA_CASES \\\n' + '\n'.join(extra_cases_lines)
    if extra_cases_lines:
        extra_cases_str = extra_cases_str.rstrip(' \\')
        extra_cases_str += '\n        ;'

    pattern = r'#define EXTRA_CASES\s*\\[^;]*;'
    content = re.sub(pattern, extra_cases_str, content, flags=re.DOTALL)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Scramble CPython 3.13 opcode values")
    parser.add_argument("source_root", help="CPython source root directory")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for shuffle (omit for deterministic reversal)")
    args = parser.parse_args()

    source_root = os.path.abspath(args.source_root)

    opcode_ids_h = os.path.join(source_root, 'Include', 'opcode_ids.h')
    opcode_metadata_py = os.path.join(source_root, 'Lib', '_opcode_metadata.py')
    opcode_metadata_h = os.path.join(source_root, 'Include', 'internal',
                                      'pycore_opcode_metadata.h')

    for f in [opcode_ids_h, opcode_metadata_py, opcode_metadata_h]:
        if not os.path.exists(f):
            print(f"Error: {f} not found. Is this a CPython 3.13 source tree?")
            sys.exit(1)

    mode = "random shuffle" if args.seed is not None else "reversal"
    print(f"=== CPython 3.13 Opcode Scrambling Script (mode: {mode}) ===\n")

    print("[1/4] Parsing current opcode definitions...")
    opcodes = parse_opcode_ids_h(opcode_ids_h)
    print(f"  Found {len(opcodes)} opcodes")

    print("[2/4] Computing new opcode mapping...")
    if args.seed is not None:
        new_opcodes = compute_random_mapping(opcodes, args.seed)
        print(f"  Using random seed: {args.seed}")
    else:
        new_opcodes = compute_reversed_mapping(opcodes)
        print("  Using reversal (default)")

    examples = ['CACHE', 'NOP', 'LOAD_CONST', 'POP_TOP', 'RESUME',
                'INSTRUMENTED_LINE', 'JUMP', 'STORE_FAST_MAYBE_NULL']
    print("  Examples (name: old -> new):")
    for name in examples:
        if name in opcodes:
            print(f"    {name}: {opcodes[name]} -> {new_opcodes[name]}")

    print("[3/4] Updating header and metadata files...")
    write_opcode_ids_h(opcode_ids_h, new_opcodes)
    print(f"  Updated {opcode_ids_h}")

    metadata = parse_opcode_metadata_py(opcode_metadata_py)
    write_opcode_metadata_py(opcode_metadata_py, new_opcodes, metadata)
    print(f"  Updated {opcode_metadata_py}")

    update_extra_cases(opcode_metadata_h, new_opcodes)
    print(f"  Updated {opcode_metadata_h}")

    print("\n=== Done! ===")
    print("Opcode values have been scrambled. The modified Python interpreter")
    print("will use completely different bytecode values, making .pyc files")
    print("incompatible with standard Python 3.13.")
    print("\nYou need to rebuild CPython for changes to take effect.")


if __name__ == '__main__':
    main()
