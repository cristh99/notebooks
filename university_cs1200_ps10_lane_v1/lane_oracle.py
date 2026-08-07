from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import itertools
import json
import random
import time
from pathlib import Path

from ps10_models import (
    Instruction,
    add_overflows,
    broken_mul_overflows_from_source,
    compare_total_program_runtimes,
    fixed_word_overflow_decider_floyd,
    fixed_word_overflow_decider_seen,
    guarded_word_simulation,
    halting_to_overflow_reduction_finite,
    max_word_value,
    mul_overflows,
    run_ram,
    straight_line_program,
    waiting_for_godot_finite,
)


def arithmetic_word_case(word_length: int) -> dict:
    maximum = max_word_value(word_length)
    addition_overflows = 0
    multiplication_overflows = 0
    pairs = 0
    for x in range(maximum + 1):
        for y in range(maximum + 1):
            expected_add = x + y > maximum
            expected_mul = x * y > maximum
            actual_add = add_overflows(x, y, maximum)
            actual_mul = mul_overflows(x, y, maximum)
            assert actual_add == expected_add
            assert actual_mul == expected_mul
            addition_overflows += int(actual_add)
            multiplication_overflows += int(actual_mul)
            pairs += 1
    return {
        "word_length": word_length,
        "pairs": pairs,
        "checks": 2 * pairs,
        "addition_overflows": addition_overflows,
        "multiplication_overflows": multiplication_overflows,
    }


def micro_instruction_options(program_length: int) -> tuple[Instruction, ...]:
    targets = range(program_length)
    options = [
        Instruction("halt"),
        Instruction("output", 0),
        Instruction("set", 0, 0),
        Instruction("set", 0, 1),
        Instruction("set", 1, 1),
        Instruction("add", 0, 0, 1),
        Instruction("mul", 0, 0, 1),
        Instruction("sub", 0, 0, 1),
        Instruction("malloc"),
        Instruction("read", 0, 1),
        Instruction("write", 0, 1),
    ]
    options.extend(Instruction("goto", target) for target in targets)
    options.extend(Instruction("jz", 0, target) for target in targets)
    return tuple(options)


def micro_programs(program_length: int = 3) -> list[tuple[Instruction, ...]]:
    options = micro_instruction_options(program_length)
    return [tuple(items) for items in itertools.product(options, repeat=program_length)]


def finite_state_case(payload) -> dict:
    index, program, word_length = payload
    seen = fixed_word_overflow_decider_seen(program, word_length)
    floyd = fixed_word_overflow_decider_floyd(program, word_length)
    assert seen == floyd
    return {
        "program_index": index,
        "word_length": word_length,
        "overflow": seen,
    }


def random_straight_line_program(seed: int) -> tuple[Instruction, ...]:
    rng = random.Random(seed)
    instructions = [
        Instruction("set", 0, rng.randint(0, 3)),
        Instruction("set", 1, rng.randint(0, 3)),
    ]
    choices = ("set", "copy", "add", "mul", "sub", "malloc", "read", "write")
    for _ in range(rng.randint(3, 9)):
        op = rng.choice(choices)
        if op == "set":
            instructions.append(
                Instruction("set", rng.randrange(3), rng.randint(0, 5))
            )
        elif op == "copy":
            instructions.append(
                Instruction("copy", rng.randrange(3), rng.randrange(3))
            )
        elif op in {"add", "mul", "sub"}:
            instructions.append(
                Instruction(
                    op,
                    rng.randrange(3),
                    rng.randrange(3),
                    rng.randrange(3),
                )
            )
        elif op == "malloc":
            instructions.append(Instruction("malloc"))
        elif op == "read":
            instructions.append(
                Instruction("read", rng.randrange(3), rng.randrange(3))
            )
        else:
            instructions.append(
                Instruction("write", rng.randrange(3), rng.randrange(3))
            )
    return straight_line_program(instructions)


def guarded_simulation_case(seed: int) -> dict:
    program = random_straight_line_program(seed)
    ram = run_ram(program)
    assert ram.event == "output"
    sufficient_word_length = max(
        1,
        (ram.peak_value + 1).bit_length(),
        (ram.peak_memory + 1).bit_length(),
    ) + 1
    guarded = guarded_word_simulation(program, sufficient_word_length)
    assert guarded.event == "output"
    assert guarded.output == ram.output

    smaller_word_lengths_checked = 0
    for word_length in range(1, min(sufficient_word_length, 9)):
        probe = guarded_word_simulation(program, word_length)
        assert probe.event != "overflow"
        smaller_word_lengths_checked += 1

    assert halting_to_overflow_reduction_finite(
        program, sufficient_word_length
    )
    assert waiting_for_godot_finite(program)
    return {
        "seed": seed,
        "instructions": len(program),
        "sufficient_word_length": sufficient_word_length,
        "smaller_word_lengths_checked": smaller_word_lengths_checked,
        "ram_output": ram.output,
    }


def looping_program_case(seed: int) -> dict:
    rng = random.Random(seed)
    # All variants reach a fixed state and loop; none executes unguarded overflow.
    register = rng.randrange(3)
    value = rng.randint(0, 3)
    program = (
        Instruction("set", register, value),
        Instruction("goto", 1),
    )
    ram = run_ram(program)
    assert ram.event == "loop"
    assert not waiting_for_godot_finite(program)
    checked = 0
    for word_length in range(1, 9):
        assert not halting_to_overflow_reduction_finite(program, word_length)
        checked += 1
    return {"seed": seed, "word_lengths_checked": checked}


def runtime_comparison_case(seed: int) -> dict:
    rng = random.Random(seed)
    left_work = rng.randint(0, 20)
    right_work = rng.randint(0, 20)
    left = tuple(Instruction("copy", 0, 0) for _ in range(left_work)) + (
        Instruction("halt"),
    )
    right = tuple(Instruction("copy", 0, 0) for _ in range(right_work)) + (
        Instruction("halt"),
    )
    actual = compare_total_program_runtimes(left, right, 4)
    expected = left_work < right_work
    assert actual == expected
    return {
        "seed": seed,
        "left_steps": left_work + 1,
        "right_steps": right_work + 1,
        "left_faster": actual,
    }


def _map(workers: int, function, payloads):
    if workers == 1:
        return [function(item) for item in payloads]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(function, payloads))


def run(workers: int) -> dict:
    started = time.perf_counter()

    arithmetic = _map(workers, arithmetic_word_case, list(range(1, 11)))

    programs = micro_programs(3)
    finite_payloads = [
        (index, program, word_length)
        for index, program in enumerate(programs)
        for word_length in (1, 2, 3)
    ]
    finite_state = _map(workers, finite_state_case, finite_payloads)

    guarded = _map(workers, guarded_simulation_case, list(range(10_000, 25_000)))
    looping = _map(workers, looping_program_case, list(range(25_000, 27_000)))
    runtime_comparisons = _map(
        workers, runtime_comparison_case, list(range(30_000, 45_000))
    )

    source_defect_raised = False
    try:
        broken_mul_overflows_from_source(0, 0, 7)
    except ZeroDivisionError:
        source_defect_raised = True
    assert source_defect_raised
    assert mul_overflows(0, 0, 7) is False
    assert mul_overflows(7, 1, 7) is False
    assert mul_overflows(7, 2, 7) is True

    scientific_payload = {
        "arithmetic": arithmetic,
        "finite_state": finite_state,
        "guarded": guarded,
        "looping": looping,
        "runtime_comparisons": runtime_comparisons,
        "source_defect_raised": source_defect_raised,
    }
    digest = hashlib.sha256(
        json.dumps(scientific_payload, sort_keys=True).encode()
    ).hexdigest()

    return {
        "schema": "university-cs1200-ps10/lane-oracle/1",
        "status": "PASS_PS10_INDEPENDENT_ORACLES",
        "workers": workers,
        "arithmetic_pairs": sum(item["pairs"] for item in arithmetic),
        "arithmetic_checks": sum(item["checks"] for item in arithmetic),
        "finite_programs": len(programs),
        "fixed_word_decider_cases": len(finite_state),
        "fixed_word_overflow_yes": sum(item["overflow"] for item in finite_state),
        "guarded_simulation_cases": len(guarded),
        "smaller_word_checks": sum(
            item["smaller_word_lengths_checked"] for item in guarded
        ),
        "halting_to_overflow_positive_cases": len(guarded),
        "halting_to_overflow_negative_cases": len(looping),
        "waiting_for_godot_positive_cases": len(guarded),
        "waiting_for_godot_negative_cases": len(looping),
        "runtime_comparison_cases": len(runtime_comparisons),
        "source_mul_zero_defect_control": "PASS_ZERO_DIVISION_REPRODUCED_AND_REPAIRED",
        "scientific_digest": digest,
        "elapsed_seconds": time.perf_counter() - started,
        "scope_boundary": (
            "Mandatory technical mechanisms and finite independent models only; "
            "optional NP-hardness, personal reflection, survey, private grader and "
            "official course completion are excluded."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.workers)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
