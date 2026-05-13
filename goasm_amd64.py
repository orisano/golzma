# goasm_amd64.py : DSL for generating Go Plan 9 AMD64 assembly

g_text = []

# Auto-label counter
_label_counter = 0


class ScaledIndex:
    """Represents reg*scale for use in memory addressing."""

    def __init__(self, reg, scale):
        assert scale in (1, 2, 4, 8), f"scale must be 1, 2, 4, or 8; got {scale}"
        self.reg = reg
        self.scale = scale

    def __str__(self):
        return f"{self.reg}*{self.scale}"

    def __radd__(self, other):
        if isinstance(other, MemOperand):
            return MemOperand(other.base, other._offset, index=self.reg, scale=self.scale)
        if isinstance(other, Reg):
            return MemOperand(other, 0, index=self.reg, scale=self.scale)
        return NotImplemented


class MemOperand:
    """Represents an AMD64 memory operand: offset(base) or offset(base)(index*scale)."""

    def __init__(self, base, offset, index=None, scale=None):
        self.base = base
        self._offset = offset
        self.index = index
        self.scale = scale if scale is not None else 1

    def idx(self, index, scale=1):
        """Return a new MemOperand with an index register added."""
        return MemOperand(self.base, self._offset, index=index, scale=scale)

    def __add__(self, other):
        if isinstance(other, int):
            new_offset = (self._offset + other) if isinstance(self._offset, int) else self._offset
            return MemOperand(self.base, new_offset, index=self.index, scale=self.scale)
        if isinstance(other, ScaledIndex):
            return MemOperand(self.base, self._offset, index=other.reg, scale=other.scale)
        if isinstance(other, Reg):
            return MemOperand(self.base, self._offset, index=other, scale=1)
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, int):
            return self.__add__(other)
        return NotImplemented

    def __str__(self):
        if self.index is not None:
            scale = self.scale if self.scale is not None else 1
            index_part = f"({self.index}*{scale})"
            if isinstance(self._offset, str):
                return f"{self._offset}({self.base}){index_part}"
            if self._offset == 0:
                return f"({self.base}){index_part}"
            return f"{self._offset}({self.base}){index_part}"
        else:
            if isinstance(self._offset, str):
                return f"{self._offset}({self.base})"
            if self._offset == 0:
                return f"({self.base})"
            return f"{self._offset}({self.base})"


class Imm:
    """Immediate value with optional hex formatting."""

    def __init__(self, value, fmt="dec"):
        self.value = value
        self.fmt = fmt

    def __str__(self):
        if self.fmt == "hex":
            return f"$0x{self.value:X}"
        return f"${self.value}"


class FPArg:
    """Frame pointer argument: name+offset(FP)."""

    def __init__(self, name, offset):
        self.name = name
        self.offset = offset

    def __str__(self):
        return f"{self.name}+{self.offset}(FP)"


class Reg:
    """AMD64 general-purpose register."""

    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name

    def __add__(self, other):
        if isinstance(other, int):
            return MemOperand(self, other)
        if isinstance(other, str):
            return MemOperand(self, other)
        if isinstance(other, ScaledIndex):
            return MemOperand(self, 0, index=other.reg, scale=other.scale)
        if isinstance(other, Reg):
            return MemOperand(self, 0, index=other, scale=1)
        return NotImplemented

    def __radd__(self, other):
        if isinstance(other, int):
            return MemOperand(self, other)
        return NotImplemented

    def __sub__(self, other):
        if isinstance(other, int):
            return MemOperand(self, -other)
        return NotImplemented

    def __mul__(self, scale):
        return ScaledIndex(self, scale)

    def __rmul__(self, scale):
        return ScaledIndex(self, scale)


class Label:
    """Named or auto-numbered label."""

    def __init__(self, name=None):
        global _label_counter
        if name is None:
            self._name = f"_label_{_label_counter}"
            _label_counter += 1
        else:
            self._name = name

    def __str__(self):
        return self._name


# ---------------------------------------------------------------------------
# Registers
# ---------------------------------------------------------------------------

AX  = Reg("AX")
BX  = Reg("BX")
CX  = Reg("CX")
DX  = Reg("DX")
SI  = Reg("SI")
DI  = Reg("DI")
BP  = Reg("BP")
SP  = Reg("SP")
R8  = Reg("R8")
R9  = Reg("R9")
R10 = Reg("R10")
R11 = Reg("R11")
R12 = Reg("R12")
R13 = Reg("R13")
R14 = Reg("R14")
R15 = Reg("R15")


# ---------------------------------------------------------------------------
# Code generation engine
# ---------------------------------------------------------------------------

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


def fmt_operand(op):
    if isinstance(op, int):
        return f"${op}"
    return str(op)


def _emit_instr(name, *operands, comment=None):
    parts = [fmt_operand(op) for op in operands]
    line = name + "\t" + ", ".join(parts)
    if comment:
        line = line.ljust(45) + "// " + comment
    emit(line)


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

# Data movement

def MOVQ(src, dst, **kw):
    """dst = (uint64)src"""
    _emit_instr("MOVQ", src, dst, **kw)

def MOVL(src, dst, **kw):
    """dst = (uint32)src"""
    _emit_instr("MOVL", src, dst, **kw)

def MOVW(src, dst, **kw):
    """dst = (uint16)src"""
    _emit_instr("MOVW", src, dst, **kw)

def MOVB(src, dst, **kw):
    """dst = (uint8)src"""
    _emit_instr("MOVB", src, dst, **kw)

def MOVBLZX(src, dst, **kw):
    """dst = zero_extend_byte_to_32(src)"""
    _emit_instr("MOVBLZX", src, dst, **kw)

def MOVWLZX(src, dst, **kw):
    """dst = zero_extend_word_to_32(src)"""
    _emit_instr("MOVWLZX", src, dst, **kw)


# Arithmetic

def ADDQ(src, dst, **kw):
    """dst += src  (64-bit)"""
    _emit_instr("ADDQ", src, dst, **kw)

def ADDL(src, dst, **kw):
    """dst += src  (32-bit)"""
    _emit_instr("ADDL", src, dst, **kw)

def SUBQ(src, dst, **kw):
    """dst -= src  (64-bit)"""
    _emit_instr("SUBQ", src, dst, **kw)

def SUBL(src, dst, **kw):
    """dst -= src  (32-bit)"""
    _emit_instr("SUBL", src, dst, **kw)

def INCQ(dst, **kw):
    """dst++  (64-bit)"""
    _emit_instr("INCQ", dst, **kw)

def INCL(dst, **kw):
    """dst++  (32-bit)"""
    _emit_instr("INCL", dst, **kw)

def DECQ(dst, **kw):
    """dst--  (64-bit)"""
    _emit_instr("DECQ", dst, **kw)

def DECL(dst, **kw):
    """dst--  (32-bit)"""
    _emit_instr("DECL", dst, **kw)

def NEGQ(dst, **kw):
    """dst = -dst  (64-bit)"""
    _emit_instr("NEGQ", dst, **kw)

def NEGL(dst, **kw):
    """dst = -dst  (32-bit)"""
    _emit_instr("NEGL", dst, **kw)

def IMULL(src, dst, **kw):
    """dst *= src  (32-bit signed multiply)"""
    _emit_instr("IMULL", src, dst, **kw)

def SBBL(src, dst, **kw):
    """dst -= src + CF  (32-bit subtract with borrow)"""
    _emit_instr("SBBL", src, dst, **kw)


# Logic

def ANDQ(src, dst, **kw):
    """dst &= src  (64-bit)"""
    _emit_instr("ANDQ", src, dst, **kw)

def ANDL(src, dst, **kw):
    """dst &= src  (32-bit)"""
    _emit_instr("ANDL", src, dst, **kw)

def ORQ(src, dst, **kw):
    """dst |= src  (64-bit)"""
    _emit_instr("ORQ", src, dst, **kw)

def ORL(src, dst, **kw):
    """dst |= src  (32-bit)"""
    _emit_instr("ORL", src, dst, **kw)

def XORL(src, dst, **kw):
    """dst ^= src  (32-bit)"""
    _emit_instr("XORL", src, dst, **kw)

def XORQ(src, dst, **kw):
    """dst ^= src  (64-bit)"""
    _emit_instr("XORQ", src, dst, **kw)


# Shift

def SHLL(count, dst, **kw):
    """dst <<= count  (32-bit logical left shift)"""
    _emit_instr("SHLL", count, dst, **kw)

def SHRL(count, dst, **kw):
    """dst >>= count  (32-bit logical right shift)"""
    _emit_instr("SHRL", count, dst, **kw)

def SARL(count, dst, **kw):
    """dst >>= count  (32-bit arithmetic right shift)"""
    _emit_instr("SARL", count, dst, **kw)

def SHRQ(count, dst, **kw):
    """dst >>= count  (64-bit logical right shift)"""
    _emit_instr("SHRQ", count, dst, **kw)

def SHLQ(count, dst, **kw):
    """dst <<= count  (64-bit logical left shift)"""
    _emit_instr("SHLQ", count, dst, **kw)


# Compare/Test

def CMPL(a, b, **kw):
    """flags = a - b  (32-bit). Go Plan 9 CMP X, Y computes X - Y.
    Swap only when first arg is immediate (Go asm requires reg/mem first)."""
    if isinstance(a, (int, Imm)):
        _emit_instr("CMPL", b, a, **kw)
    else:
        _emit_instr("CMPL", a, b, **kw)

def CMPQ(a, b, **kw):
    """flags = a - b  (64-bit). Go Plan 9 CMP X, Y computes X - Y.
    Swap only when first arg is immediate (Go asm requires reg/mem first)."""
    if isinstance(a, (int, Imm)):
        _emit_instr("CMPQ", b, a, **kw)
    else:
        _emit_instr("CMPQ", a, b, **kw)

def TESTL(a, b, **kw):
    """a & b; set flags  (32-bit, result discarded)"""
    _emit_instr("TESTL", a, b, **kw)

def TESTQ(a, b, **kw):
    """a & b; set flags  (64-bit, result discarded)"""
    _emit_instr("TESTQ", a, b, **kw)


# LEA

def LEAQ(mem, dst, **kw):
    """dst = address of mem  (64-bit)"""
    _emit_instr("LEAQ", mem, dst, **kw)

def LEAL(mem, dst, **kw):
    """dst = address of mem  (32-bit)"""
    _emit_instr("LEAL", mem, dst, **kw)


# Conditional move (32-bit)

def CMOVLCC(src, dst, **kw):
    """if carry clear (unsigned >=): dst = src  (32-bit)"""
    _emit_instr("CMOVLCC", src, dst, **kw)

def CMOVLCS(src, dst, **kw):
    """if carry set (unsigned <): dst = src  (32-bit)"""
    _emit_instr("CMOVLCS", src, dst, **kw)

def CMOVLEQ(src, dst, **kw):
    """if equal: dst = src  (32-bit)"""
    _emit_instr("CMOVLEQ", src, dst, **kw)

def CMOVLNE(src, dst, **kw):
    """if not equal: dst = src  (32-bit)"""
    _emit_instr("CMOVLNE", src, dst, **kw)

def CMOVLMI(src, dst, **kw):
    """if minus (negative): dst = src  (32-bit)"""
    _emit_instr("CMOVLMI", src, dst, **kw)

def CMOVLPL(src, dst, **kw):
    """if plus (non-negative): dst = src  (32-bit)"""
    _emit_instr("CMOVLPL", src, dst, **kw)

def CMOVLHI(src, dst, **kw):
    """if unsigned >: dst = src  (32-bit)"""
    _emit_instr("CMOVLHI", src, dst, **kw)

def CMOVLLS(src, dst, **kw):
    """if unsigned <=: dst = src  (32-bit)"""
    _emit_instr("CMOVLLS", src, dst, **kw)


# Conditional move (64-bit)

def CMOVQCC(src, dst, **kw):
    """if carry clear (unsigned >=): dst = src  (64-bit)"""
    _emit_instr("CMOVQCC", src, dst, **kw)

def CMOVQCS(src, dst, **kw):
    """if carry set (unsigned <): dst = src  (64-bit)"""
    _emit_instr("CMOVQCS", src, dst, **kw)

def CMOVQEQ(src, dst, **kw):
    """if equal: dst = src  (64-bit)"""
    _emit_instr("CMOVQEQ", src, dst, **kw)

def CMOVQNE(src, dst, **kw):
    """if not equal: dst = src  (64-bit)"""
    _emit_instr("CMOVQNE", src, dst, **kw)

def CMOVQMI(src, dst, **kw):
    """if minus (negative): dst = src  (64-bit)"""
    _emit_instr("CMOVQMI", src, dst, **kw)

def CMOVQPL(src, dst, **kw):
    """if plus (non-negative): dst = src  (64-bit)"""
    _emit_instr("CMOVQPL", src, dst, **kw)


# Branch

def JMP(label, **kw):
    """goto label"""
    _emit_instr("JMP", label, **kw)

def JCC(label, **kw):
    """if carry clear (unsigned >=): goto label"""
    _emit_instr("JCC", label, **kw)

def JCS(label, **kw):
    """if carry set (unsigned <): goto label"""
    _emit_instr("JCS", label, **kw)

def JEQ(label, **kw):
    """if equal: goto label"""
    _emit_instr("JEQ", label, **kw)

def JNE(label, **kw):
    """if not equal: goto label"""
    _emit_instr("JNE", label, **kw)

def JMI(label, **kw):
    """if minus (negative): goto label"""
    _emit_instr("JMI", label, **kw)

def JPL(label, **kw):
    """if plus (non-negative): goto label"""
    _emit_instr("JPL", label, **kw)

def JHI(label, **kw):
    """if unsigned >: goto label"""
    _emit_instr("JHI", label, **kw)

def JLS(label, **kw):
    """if unsigned <=: goto label"""
    _emit_instr("JLS", label, **kw)

def JGT(label, **kw):
    """if signed >: goto label"""
    _emit_instr("JGT", label, **kw)

def JGE(label, **kw):
    """if signed >=: goto label"""
    _emit_instr("JGE", label, **kw)

def JLT(label, **kw):
    """if signed <: goto label"""
    _emit_instr("JLT", label, **kw)

def JLE(label, **kw):
    """if signed <=: goto label"""
    _emit_instr("JLE", label, **kw)


# SSE (128-bit unaligned move)

X0 = Reg("X0")
X1 = Reg("X1")

def MOVOU(src, dst, **kw):
    """128-bit unaligned move (movdqu)"""
    _emit_instr("MOVOU", src, dst, **kw)

def IMULQ(src, dst, **kw):
    """dst *= src  (64-bit signed multiply)"""
    _emit_instr("IMULQ", src, dst, **kw)


# Stack

def PUSHQ(src, **kw):
    """push 64-bit value onto stack"""
    _emit_instr("PUSHQ", src, **kw)

def POPQ(dst, **kw):
    """pop 64-bit value from stack"""
    _emit_instr("POPQ", dst, **kw)


# Return

def RET(**kw):
    """return to caller"""
    c = kw.get("comment")
    if c:
        emit("RET".ljust(45) + "// " + c)
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


def section(title):
    emit_raw("// " + "=" * 60)
    emit_raw("// " + title)
    emit_raw("// " + "=" * 60)
