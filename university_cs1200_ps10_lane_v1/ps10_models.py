from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class Instruction:
    op: str
    a: int = 0
    b: int = 0
    c: int = 0


@dataclass(frozen=True)
class MachineState:
    pc: int
    registers: tuple[int, ...]
    memory: tuple[int, ...]


@dataclass(frozen=True)
class RunResult:
    event: str
    steps: int
    output: int | None
    state: MachineState
    peak_value: int
    peak_memory: int


TERMINAL_EVENTS = {"halt", "output", "crash", "overflow", "guarded_stop"}


def max_word_value(word_length: int) -> int:
    if not isinstance(word_length, int) or word_length <= 0:
        raise ValueError("word_length must be a positive integer")
    return (1 << word_length) - 1


def add_overflows(x: int, y: int, maximum: int) -> bool:
    """Exact addition-overflow predicate using subtraction only."""
    if not 0 <= x <= maximum or not 0 <= y <= maximum:
        raise ValueError("operands must be words")
    return x > maximum - y


def mul_overflows(x: int, y: int, maximum: int) -> bool:
    """Exact multiplication-overflow predicate with the required y=0 guard."""
    if not 0 <= x <= maximum or not 0 <= y <= maximum:
        raise ValueError("operands must be words")
    if y == 0:
        return False
    return x > maximum // y


def broken_mul_overflows_from_source(x: int, y: int, maximum: int) -> bool:
    """Literal source formula, intentionally retaining its y=0 defect."""
    return x > maximum // y


def initial_state(register_count: int = 3) -> MachineState:
    return MachineState(0, tuple(0 for _ in range(register_count)), tuple())


def _replace(values: tuple[int, ...], index: int, value: int) -> tuple[int, ...]:
    mutable = list(values)
    mutable[index] = value
    return tuple(mutable)


def step_word(
    program: Sequence[Instruction],
    state: MachineState,
    word_length: int,
    *,
    guarded: bool = False,
) -> tuple[str, MachineState, int | None]:
    """Execute one deterministic Word-RAM step.

    `guarded=True` implements the overflow-free source transformation: a
    would-overflow arithmetic command stops before performing the operation.
    """
    maximum = max_word_value(word_length)
    if not 0 <= state.pc < len(program):
        return "crash", state, None

    instruction = program[state.pc]
    registers = state.registers
    memory = state.memory
    next_pc = state.pc + 1

    def require_register(index: int) -> None:
        if not 0 <= index < len(registers):
            raise IndexError("register outside program model")

    op = instruction.op
    if op == "halt":
        return "halt", state, None
    if op == "output":
        require_register(instruction.a)
        return "output", state, registers[instruction.a]
    if op == "set":
        require_register(instruction.a)
        if not 0 <= instruction.b <= maximum:
            return "crash", state, None
        registers = _replace(registers, instruction.a, instruction.b)
    elif op == "copy":
        require_register(instruction.a)
        require_register(instruction.b)
        registers = _replace(registers, instruction.a, registers[instruction.b])
    elif op in {"add", "mul", "sub"}:
        require_register(instruction.a)
        require_register(instruction.b)
        require_register(instruction.c)
        x = registers[instruction.b]
        y = registers[instruction.c]
        if op == "add":
            would_overflow = add_overflows(x, y, maximum)
            result = x + y
        elif op == "mul":
            would_overflow = mul_overflows(x, y, maximum)
            result = x * y
        else:
            would_overflow = False
            result = max(0, x - y)
        if would_overflow:
            return ("guarded_stop" if guarded else "overflow"), state, None
        registers = _replace(registers, instruction.a, result)
    elif op == "malloc":
        if len(memory) >= maximum + 1:
            return "crash", state, None
        memory = memory + (0,)
    elif op == "read":
        require_register(instruction.a)
        require_register(instruction.b)
        address = registers[instruction.b]
        if address < len(memory):
            registers = _replace(registers, instruction.a, memory[address])
    elif op == "write":
        require_register(instruction.a)
        require_register(instruction.b)
        address = registers[instruction.b]
        if address < len(memory):
            memory = _replace(memory, address, registers[instruction.a])
    elif op == "goto":
        next_pc = instruction.a
    elif op == "jz":
        require_register(instruction.a)
        if registers[instruction.a] == 0:
            next_pc = instruction.b
    else:
        raise ValueError(f"unknown instruction: {op}")

    return "continue", MachineState(next_pc, registers, memory), None


def run_word_until_event(
    program: Sequence[Instruction],
    word_length: int,
    *,
    guarded: bool = False,
) -> RunResult:
    state = initial_state()
    seen: set[MachineState] = set()
    steps = 0
    peak_value = 0
    peak_memory = 0

    while True:
        if state in seen:
            return RunResult("loop", steps, None, state, peak_value, peak_memory)
        seen.add(state)
        peak_value = max(peak_value, *state.registers, *(state.memory or (0,)))
        peak_memory = max(peak_memory, len(state.memory))
        event, next_state, output = step_word(
            program, state, word_length, guarded=guarded
        )
        if event in TERMINAL_EVENTS:
            return RunResult(event, steps + 1, output, state, peak_value, peak_memory)
        state = next_state
        steps += 1


def fixed_word_overflow_decider_seen(
    program: Sequence[Instruction], word_length: int
) -> bool:
    return run_word_until_event(program, word_length).event == "overflow"


def _advance(
    program: Sequence[Instruction],
    state: MachineState,
    word_length: int,
) -> tuple[str, MachineState]:
    event, next_state, _ = step_word(program, state, word_length)
    return event, next_state


def fixed_word_overflow_decider_floyd(
    program: Sequence[Instruction], word_length: int
) -> bool:
    """Independent cycle-detection oracle using constant-memory Floyd traversal."""
    start = initial_state()

    def one(state: MachineState) -> tuple[str, MachineState]:
        return _advance(program, state, word_length)

    event, tortoise = one(start)
    if event == "overflow":
        return True
    if event in TERMINAL_EVENTS:
        return False

    event, hare = one(tortoise)
    if event == "overflow":
        return True
    if event in TERMINAL_EVENTS:
        return False

    while tortoise != hare:
        event, tortoise = one(tortoise)
        if event == "overflow":
            return True
        if event in TERMINAL_EVENTS:
            return False

        for _ in range(2):
            event, hare = one(hare)
            if event == "overflow":
                return True
            if event in TERMINAL_EVENTS:
                return False

    return False


def step_ram(
    program: Sequence[Instruction], state: MachineState
) -> tuple[str, MachineState, int | None]:
    """Unbounded-natural RAM analogue used only for finite validation cases."""
    if not 0 <= state.pc < len(program):
        return "crash", state, None
    instruction = program[state.pc]
    registers = state.registers
    memory = state.memory
    next_pc = state.pc + 1
    op = instruction.op

    if op == "halt":
        return "halt", state, None
    if op == "output":
        return "output", state, registers[instruction.a]
    if op == "set":
        registers = _replace(registers, instruction.a, instruction.b)
    elif op == "copy":
        registers = _replace(registers, instruction.a, registers[instruction.b])
    elif op == "add":
        registers = _replace(
            registers,
            instruction.a,
            registers[instruction.b] + registers[instruction.c],
        )
    elif op == "mul":
        registers = _replace(
            registers,
            instruction.a,
            registers[instruction.b] * registers[instruction.c],
        )
    elif op == "sub":
        registers = _replace(
            registers,
            instruction.a,
            max(0, registers[instruction.b] - registers[instruction.c]),
        )
    elif op == "malloc":
        memory = memory + (0,)
    elif op == "read":
        address = registers[instruction.b]
        if address < len(memory):
            registers = _replace(registers, instruction.a, memory[address])
    elif op == "write":
        address = registers[instruction.b]
        if address < len(memory):
            memory = _replace(memory, address, registers[instruction.a])
    elif op == "goto":
        next_pc = instruction.a
    elif op == "jz":
        if registers[instruction.a] == 0:
            next_pc = instruction.b
    else:
        raise ValueError(op)
    return "continue", MachineState(next_pc, registers, memory), None


def run_ram(
    program: Sequence[Instruction], *, max_steps: int = 100_000
) -> RunResult:
    state = initial_state()
    seen: set[MachineState] = set()
    peak_value = 0
    peak_memory = 0
    for steps in range(max_steps):
        if state in seen:
            return RunResult("loop", steps, None, state, peak_value, peak_memory)
        seen.add(state)
        peak_value = max(peak_value, *state.registers, *(state.memory or (0,)))
        peak_memory = max(peak_memory, len(state.memory))
        event, next_state, output = step_ram(program, state)
        if event in {"halt", "output", "crash"}:
            return RunResult(
                event, steps + 1, output, state, peak_value, peak_memory
            )
        state = next_state
    return RunResult("step_limit", max_steps, None, state, peak_value, peak_memory)


def guarded_word_simulation(
    program: Sequence[Instruction], word_length: int
) -> RunResult:
    return run_word_until_event(program, word_length, guarded=True)


def halting_to_overflow_reduction_finite(
    program: Sequence[Instruction], word_length: int
) -> bool:
    """Finite analogue of the reduction used in the undecidability proof.

    The source program is first simulated through the guarded overflow-free model.
    If it halts normally, repeated doubling necessarily produces an overflow at
    this fixed finite word length. If it does not halt normally, no arithmetic
    overflow is executed by the guarded simulation.
    """
    result = guarded_word_simulation(program, word_length)
    if result.event not in {"halt", "output"}:
        return False
    maximum = max_word_value(word_length)
    value = 1
    while not add_overflows(value, value, maximum):
        value += value
    return True


def compare_total_program_runtimes(
    first: Sequence[Instruction],
    second: Sequence[Instruction],
    word_length: int,
) -> bool:
    left = run_word_until_event(first, word_length)
    right = run_word_until_event(second, word_length)
    if left.event not in {"halt", "output"} or right.event not in {"halt", "output"}:
        raise ValueError("comparison contract requires two total programs")
    return left.steps < right.steps


def waiting_for_godot_finite(program: Sequence[Instruction]) -> bool:
    """Finite validation analogue of the source reduction.

    'Vladimir' simulates P on the empty input and emits Godot iff P halts;
    'Estragon' loops. Thus the constructed problem accepts iff P halts.
    """
    return run_ram(program).event in {"halt", "output"}


def straight_line_program(instructions: Iterable[Instruction]) -> tuple[Instruction, ...]:
    return tuple(instructions) + (Instruction("output", 0),)
