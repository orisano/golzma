# goasm_arm64.py : DSL for generating Go Plan 9 ARM64 assembly

g_text = []

# Auto-label counter
_label_counter = 0


class MemOperand:
    def __init__(self, base, offset):
        self.base = base
        self._offset = offset

    def __str__(self):
        if isinstance(self._offset, str):
            # "name+0(Rn)" form so the plan9 preprocessor expands name as
            # an object-like macro instead of trying a function-like call.
            return f"{self._offset}({self.base})"
        if self._offset == 0:
            return f"({self.base})"
        return f"{self._offset}({self.base})"


class Mem:
    def __init__(self, base, index):
        self.base = base
        self.index = index

    def __str__(self):
        return f"({self.base})({self.index})"


class FPArg:
    def __init__(self, name, offset):
        self.name = name
        self.offset = offset

    def __str__(self):
        return f"{self.name}+{self.offset}(FP)"


class Imm:
    def __init__(self, value, fmt="dec"):
        self.value = value
        self.fmt = fmt

    def __str__(self):
        if self.fmt == "hex":
            return f"$0x{self.value:X}"
        return f"${self.value}"


class ShiftedReg:
    def __init__(self, reg, op, amount):
        self.reg = reg
        self.op = op
        self.amount = amount

    def __str__(self):
        return f"{self.reg}{self.op}{self.amount}"


class Reg:
    def __init__(self, idx, name):
        self.idx = idx
        self.name = name

    def __str__(self):
        return self.name

    def __add__(self, other):
        if isinstance(other, (int, str)):
            return MemOperand(self, other)
        if isinstance(other, (Reg, ShiftedReg)):
            return Mem(self, other)
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, int):
            return MemOperand(self, -other)
        return NotImplemented

    def lsl(self, n):
        return ShiftedReg(self, "<<", n)

    def asr(self, n):
        return ShiftedReg(self, "->", n)

    def offset(self, n):
        return MemOperand(self, n)


class Condition:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


class Label:
    def __init__(self, name=None):
        global _label_counter
        if name is None:
            self._name = f"_label_{_label_counter}"
            _label_counter += 1
        else:
            self._name = name

    def __str__(self):
        return self._name


def fmt_operand(op):
    if isinstance(op, int):
        return f"${op}"
    if isinstance(op, Imm):
        return str(op)
    if isinstance(op, Label):
        return str(op)
    return str(op)


# Code generation engine

def init(*includes):
    """Initialize code generation. Extra includes are added after textflag.h.

    Example: init("go_asm.h") emits both #include "textflag.h" and #include "go_asm.h".
    """
    global g_text
    g_text.clear()
    g_text.append('#include "textflag.h"')
    for inc in includes:
        g_text.append(f'#include "{inc}"')
    g_text.append("")


def emit(line):
    g_text.append("\t" + line)


def emit_raw(line):
    g_text.append(line)


def term():
    print("\n".join(g_text))


def comment(text):
    g_text.append("// " + text)


def blank():
    g_text.append("")


def L(label):
    g_text.append(f"{label}:")


# General-purpose registers R0-R30
R0  = Reg(0,  "R0")
R1  = Reg(1,  "R1")
R2  = Reg(2,  "R2")
R3  = Reg(3,  "R3")
R4  = Reg(4,  "R4")
R5  = Reg(5,  "R5")
R6  = Reg(6,  "R6")
R7  = Reg(7,  "R7")
R8  = Reg(8,  "R8")
R9  = Reg(9,  "R9")
R10 = Reg(10, "R10")
R11 = Reg(11, "R11")
R12 = Reg(12, "R12")
R13 = Reg(13, "R13")
R14 = Reg(14, "R14")
R15 = Reg(15, "R15")
R16 = Reg(16, "R16")
R17 = Reg(17, "R17")
R18 = Reg(18, "R18")
R19 = Reg(19, "R19")
R20 = Reg(20, "R20")
R21 = Reg(21, "R21")
R22 = Reg(22, "R22")
R23 = Reg(23, "R23")
R24 = Reg(24, "R24")
R25 = Reg(25, "R25")
R26 = Reg(26, "R26")
R27 = Reg(27, "R27")
R28 = Reg(28, "R28")
R29 = Reg(29, "R29")
R30 = Reg(30, "R30")

# Special registers
RSP = Reg(31, "RSP")
ZR  = Reg(31, "ZR")

# Condition codes
EQ = Condition("EQ")
NE = Condition("NE")
HS = Condition("HS")
LO = Condition("LO")
HI = Condition("HI")
LS = Condition("LS")
PL = Condition("PL")
MI = Condition("MI")
GE = Condition("GE")
LT = Condition("LT")


# ---------------------------------------------------------------------------
# Instruction emitters
# ---------------------------------------------------------------------------

def _emit_instr(name, *operands, comment=None):
    parts = [fmt_operand(op) for op in operands]
    line = name + "\t" + ", ".join(parts)
    if comment:
        line = line.ljust(45) + "// " + comment
    emit(line)


# Data movement

def MOVD(src, dst, **kw):
    """dst = (uint64)src"""
    _emit_instr("MOVD", src, dst, **kw)

def MOVW(src, dst, **kw):
    """dst = (int32)src  (sign-extended to 64-bit when loading)"""
    _emit_instr("MOVW", src, dst, **kw)

def MOVWU(src, dst, **kw):
    """dst = (uint32)src"""
    _emit_instr("MOVWU", src, dst, **kw)

def MOVB(src, dst, **kw):
    """dst = (int8)src"""
    _emit_instr("MOVB", src, dst, **kw)

def MOVBU(src, dst, **kw):
    """dst = (uint8)src"""
    _emit_instr("MOVBU", src, dst, **kw)

def MOVBU_P(src, dst, **kw):
    """dst = (uint8)*src; src.base++  (post-increment load)"""
    _emit_instr("MOVBU.P", src, dst, **kw)

def MOVH(src, dst, **kw):
    """dst = (int16)src"""
    _emit_instr("MOVH", src, dst, **kw)

def MOVHU(src, dst, **kw):
    """dst = (uint16)src"""
    _emit_instr("MOVHU", src, dst, **kw)

def MOVHU_W(src, dst, **kw):
    """dst = (uint16)*src; src.base += offset  (pre-increment load)"""
    _emit_instr("MOVHU.W", src, dst, **kw)


# Arithmetic

def ADD(*args, **kw):
    """dst = x + y  (64-bit)"""
    _emit_instr("ADD", *args, **kw)

def ADDS(*args, **kw):
    """dst = x + y; set flags  (64-bit)"""
    _emit_instr("ADDS", *args, **kw)

def ADDW(*args, **kw):
    """dst = x + y  (32-bit)"""
    _emit_instr("ADDW", *args, **kw)

def ADDSW(*args, **kw):
    """dst = x + y; set flags  (32-bit)"""
    _emit_instr("ADDSW", *args, **kw)

def ADCW(*args, **kw):
    """dst = x + y + carry  (32-bit)"""
    _emit_instr("ADCW", *args, **kw)

def SUB(*args, **kw):
    """dst = x - y  (64-bit)"""
    _emit_instr("SUB", *args, **kw)

def SUBS(*args, **kw):
    """dst = x - y; set flags  (64-bit)"""
    _emit_instr("SUBS", *args, **kw)

def SUBW(*args, **kw):
    """dst = x - y  (32-bit)"""
    _emit_instr("SUBW", *args, **kw)

def SUBSW(*args, **kw):
    """dst = x - y; set flags  (32-bit)"""
    _emit_instr("SUBSW", *args, **kw)

def NEG(*args, **kw):
    """dst = -src"""
    _emit_instr("NEG", *args, **kw)

def MULW(*args, **kw):
    """dst = x * y  (32-bit)"""
    _emit_instr("MULW", *args, **kw)

def CMP(*args, **kw):
    """x - y; set flags  (64-bit, result discarded)"""
    _emit_instr("CMP", *args, **kw)

def CMPW(*args, **kw):
    """x - y; set flags  (32-bit, result discarded)"""
    _emit_instr("CMPW", *args, **kw)

def CMN(*args, **kw):
    """x + y; set flags  (64-bit, result discarded)"""
    _emit_instr("CMN", *args, **kw)

def TSTW(*args, **kw):
    """x & y; set flags  (32-bit, result discarded)"""
    _emit_instr("TSTW", *args, **kw)


# Logic

def AND(*args, **kw):
    """dst = x & y  (64-bit)"""
    _emit_instr("AND", *args, **kw)

def ANDW(*args, **kw):
    """dst = x & y  (32-bit)"""
    _emit_instr("ANDW", *args, **kw)

def ORR(*args, **kw):
    """dst = x | y  (64-bit)"""
    _emit_instr("ORR", *args, **kw)

def ORRW(*args, **kw):
    """dst = x | y  (32-bit)"""
    _emit_instr("ORRW", *args, **kw)

def EORW(*args, **kw):
    """dst = x ^ y  (32-bit)"""
    _emit_instr("EORW", *args, **kw)


# Shift

def LSL(*args, **kw):
    """dst = x << n  (64-bit)"""
    _emit_instr("LSL", *args, **kw)

def LSLW(*args, **kw):
    """dst = x << n  (32-bit)"""
    _emit_instr("LSLW", *args, **kw)

def LSRW(*args, **kw):
    """dst = x >> n  (32-bit, logical/unsigned)"""
    _emit_instr("LSRW", *args, **kw)


# Conditional select

def CSEL(cond, src1, src2, dst, **kw):
    """dst = cond ? src1 : src2  (64-bit)"""
    _emit_instr("CSEL", cond, src1, src2, dst, **kw)

def CSELW(cond, src1, src2, dst, **kw):
    """dst = cond ? src1 : src2  (32-bit)"""
    _emit_instr("CSELW", cond, src1, src2, dst, **kw)

def CSINCW(cond, src1, src2, dst, **kw):
    """dst = cond ? src1 : src2 + 1  (32-bit)"""
    _emit_instr("CSINCW", cond, src1, src2, dst, **kw)


# Load/Store pair

def STP(r1, r2, mem, **kw):
    """*mem = r1; *(mem+8) = r2  (store pair)"""
    comment = kw.get("comment")
    base_str = str(mem.base)
    if isinstance(mem._offset, str):
        line = f"STP\t({r1}, {r2}), ({mem._offset})({base_str})"
    elif mem._offset == 0:
        line = f"STP\t({r1}, {r2}), ({base_str})"
    else:
        line = f"STP\t({r1}, {r2}), {mem._offset}({base_str})"
    if comment:
        line = line.ljust(45) + "// " + comment
    emit(line)

def LDP(mem, r1, r2, **kw):
    """r1 = *mem; r2 = *(mem+8)  (load pair)"""
    comment = kw.get("comment")
    line = f"LDP\t{fmt_operand(mem)}, ({r1}, {r2})"
    if comment:
        line = line.ljust(45) + "// " + comment
    emit(line)


# Branch

def B(label, **kw):
    """goto label"""
    _emit_instr("B", label, **kw)

def BEQ(label, **kw):
    """if == goto label"""
    _emit_instr("BEQ", label, **kw)

def BNE(label, **kw):
    """if != goto label"""
    _emit_instr("BNE", label, **kw)

def BHI(label, **kw):
    """if unsigned > goto label"""
    _emit_instr("BHI", label, **kw)

def BHS(label, **kw):
    """if unsigned >= goto label"""
    _emit_instr("BHS", label, **kw)

def BLO(label, **kw):
    """if unsigned < goto label"""
    _emit_instr("BLO", label, **kw)

def BLS(label, **kw):
    """if unsigned <= goto label"""
    _emit_instr("BLS", label, **kw)

def BLT(label, **kw):
    """if signed < goto label"""
    _emit_instr("BLT", label, **kw)

def BGE(label, **kw):
    """if signed >= goto label"""
    _emit_instr("BGE", label, **kw)


# Conditional branch

def CBZ(reg, label, **kw):
    """if reg == 0 goto label"""
    _emit_instr("CBZ", reg, label, **kw)

def TBZ(bit, reg, label, **kw):
    """if reg[bit] == 0 goto label"""
    comment = kw.get("comment")
    line = f"TBZ\t${bit}, {fmt_operand(reg)}, {label}"
    if comment:
        line = line.ljust(45) + "// " + comment
    emit(line)


# Misc

def RET(**kw):
    """return to caller"""
    comment = kw.get("comment")
    if comment:
        emit("RET".ljust(45) + "// " + comment)
    else:
        emit("RET")


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

class Func:
    def __init__(self, name, nosplit=False, noframe=False, frame=0, args=0):
        self.name = name
        self.nosplit = nosplit
        self.noframe = noframe
        self.frame = frame
        self.args = args

    def __enter__(self):
        flags = []
        if self.nosplit:
            flags.append("NOSPLIT")
        if self.noframe:
            flags.append("NOFRAME")
        flag_str = "|".join(flags)
        if flag_str:
            flag_str = ", " + flag_str
        emit_raw(f"TEXT ·{self.name}(SB){flag_str}, ${self.frame}-{self.args}")
        emit_raw("")
        return self

    def __exit__(self, *args):
        emit_raw("")


class StackFrame:
    def __init__(self, saves=None, frame_extra=0, call_ret=True):
        self.saves = saves or []
        self.frame_extra = frame_extra
        self.call_ret = call_ret

    def __enter__(self):
        saves = self.saves
        save_size = len(saves) * 8
        total = save_size + self.frame_extra
        # Align to 16
        total = (total + 15) & ~15
        self.total = total

        SUB(self.total, RSP, RSP)

        # Save pairs with STP, odd remainder with MOVD
        off = 0
        i = 0
        while i + 1 < len(saves):
            STP(saves[i], saves[i+1], RSP.offset(off))
            off += 16
            i += 2
        if i < len(saves):
            MOVD(saves[i], RSP.offset(off))
        return self

    def __exit__(self, *args):
        saves = self.saves
        off = 0
        i = 0
        while i + 1 < len(saves):
            LDP(RSP.offset(off), saves[i], saves[i+1])
            off += 16
            i += 2
        if i < len(saves):
            MOVD(RSP.offset(off), saves[i])

        ADD(self.total, RSP, RSP)
        if self.call_ret:
            RET()


def section(title):
    emit_raw("// " + "=" * 60)
    emit_raw("// " + title)
    emit_raw("// " + "=" * 60)
