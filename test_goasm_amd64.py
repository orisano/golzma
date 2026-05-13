# test_goasm_amd64.py : Tests for the AMD64 Go Plan 9 assembly DSL

import pytest
import goasm_amd64 as g
from goasm_amd64 import (
    Reg, MemOperand, ScaledIndex, Imm, FPArg, Label,
    AX, BX, CX, DX, SI, DI, BP, SP,
    R8, R9, R10, R11, R12, R13, R14, R15,
    fmt_operand, init, term,
    MOVL, MOVQ, MOVB, MOVW, MOVBLZX, MOVWLZX,
    ADDQ, ADDL, SUBQ, SUBL, INCQ, INCL, DECQ, DECL, NEGQ, NEGL, IMULL, SBBL,
    ANDQ, ANDL, ORQ, ORL, XORL, XORQ,
    SHLL, SHRL, SARL, SHRQ, SHLQ,
    CMPL, CMPQ, TESTL, TESTQ,
    LEAQ, LEAL,
    CMOVLCC, CMOVLCS, CMOVLEQ, CMOVLNE, CMOVLMI, CMOVLPL, CMOVLHI, CMOVLLS,
    CMOVQCC, CMOVQCS, CMOVQEQ, CMOVQNE, CMOVQMI, CMOVQPL,
    JMP, JCC, JCS, JEQ, JNE, JMI, JPL, JHI, JLS, JGT, JGE, JLT, JLE,
    PUSHQ, POPQ, RET,
    Func, section, comment, blank, L,
)


# ---------------------------------------------------------------------------
# Core types
# ---------------------------------------------------------------------------

class TestReg:
    def test_str(self):
        assert str(AX) == "AX"
        assert str(R15) == "R15"
        assert str(SP) == "SP"

    def test_add_int_gives_memoperand(self):
        m = AX + 8
        assert isinstance(m, MemOperand)
        assert str(m) == "8(AX)"

    def test_add_zero_int(self):
        m = AX + 0
        assert str(m) == "(AX)"

    def test_sub_int(self):
        m = SP - 16
        assert str(m) == "-16(SP)"

    def test_mul_gives_scaled_index(self):
        si = AX * 4
        assert isinstance(si, ScaledIndex)
        assert si.reg is AX
        assert si.scale == 4

    def test_rmul(self):
        si = 8 * R9
        assert isinstance(si, ScaledIndex)
        assert si.scale == 8

    def test_add_scaled_index(self):
        m = SI + AX * 4
        assert isinstance(m, MemOperand)
        assert str(m) == "(SI)(AX*4)"

    def test_add_reg(self):
        m = SI + DI
        assert isinstance(m, MemOperand)
        assert str(m) == "(SI)(DI*1)"

    def test_radd_int(self):
        m = 16 + AX
        assert isinstance(m, MemOperand)
        assert str(m) == "16(AX)"

    def test_add_str(self):
        m = AX + "fieldName"
        assert str(m) == "fieldName(AX)"


class TestScaledIndex:
    def test_valid_scales(self):
        for s in (1, 2, 4, 8):
            si = AX * s
            assert si.scale == s

    def test_invalid_scale(self):
        with pytest.raises(AssertionError):
            _ = AX * 3

    def test_radd_memoperand(self):
        base = SI + 4  # MemOperand(SI, 4)
        idx = AX * 2
        result = idx.__radd__(base)
        assert isinstance(result, MemOperand)
        assert str(result) == "4(SI)(AX*2)"

    def test_radd_reg(self):
        idx = BX * 4
        result = idx.__radd__(SI)
        assert isinstance(result, MemOperand)
        assert str(result) == "(SI)(BX*4)"


class TestMemOperand:
    def test_offset(self):
        m = MemOperand(AX, 16)
        assert str(m) == "16(AX)"

    def test_zero_offset(self):
        m = MemOperand(AX, 0)
        assert str(m) == "(AX)"

    def test_negative_offset(self):
        m = MemOperand(SP, -8)
        assert str(m) == "-8(SP)"

    def test_indexed(self):
        m = MemOperand(SI, 0, index=AX, scale=4)
        assert str(m) == "(SI)(AX*4)"

    def test_offset_indexed(self):
        m = MemOperand(SI, 12, index=DI, scale=2)
        assert str(m) == "12(SI)(DI*2)"

    def test_string_offset(self):
        m = MemOperand(AX, "myField")
        assert str(m) == "myField(AX)"

    def test_string_offset_indexed(self):
        m = MemOperand(AX, "myField", index=BX, scale=1)
        assert str(m) == "myField(AX)(BX*1)"

    def test_add_int_adjusts_offset(self):
        m = MemOperand(AX, 4) + 8
        assert str(m) == "12(AX)"

    def test_add_int_zero_result(self):
        m = MemOperand(AX, -4) + 4
        assert str(m) == "(AX)"

    def test_idx_method(self):
        m = MemOperand(SI, 0).idx(AX, 4)
        assert str(m) == "(SI)(AX*4)"

    def test_idx_method_with_offset(self):
        m = MemOperand(SI, 8).idx(DI, 2)
        assert str(m) == "8(SI)(DI*2)"

    def test_add_scaled_index(self):
        m = MemOperand(SI, 0) + AX * 4
        assert str(m) == "(SI)(AX*4)"

    def test_add_reg(self):
        m = MemOperand(SI, 0) + AX
        assert str(m) == "(SI)(AX*1)"

    def test_radd_int(self):
        m = 4 + MemOperand(AX, 8)
        assert str(m) == "12(AX)"


class TestImm:
    def test_dec(self):
        assert str(Imm(42)) == "$42"

    def test_hex(self):
        assert str(Imm(255, "hex")) == "$0xFF"

    def test_hex_uppercase(self):
        assert str(Imm(0xDEAD, "hex")) == "$0xDEAD"

    def test_zero(self):
        assert str(Imm(0)) == "$0"


class TestFPArg:
    def test_str(self):
        a = FPArg("src", 0)
        assert str(a) == "src+0(FP)"

    def test_nonzero_offset(self):
        a = FPArg("dst", 8)
        assert str(a) == "dst+8(FP)"


class TestLabel:
    def test_named(self):
        lb = Label("myLabel")
        assert str(lb) == "myLabel"

    def test_auto(self):
        lb = Label()
        assert str(lb).startswith("_label_")

    def test_auto_increments(self):
        lb1 = Label()
        lb2 = Label()
        assert lb1._name != lb2._name


# ---------------------------------------------------------------------------
# fmt_operand
# ---------------------------------------------------------------------------

class TestFmtOperand:
    def test_int(self):
        assert fmt_operand(42) == "$42"

    def test_neg_int(self):
        assert fmt_operand(-1) == "$-1"

    def test_reg(self):
        assert fmt_operand(AX) == "AX"

    def test_memoperand(self):
        assert fmt_operand(AX + 8) == "8(AX)"

    def test_label(self):
        lb = Label("loop")
        assert fmt_operand(lb) == "loop"

    def test_imm(self):
        assert fmt_operand(Imm(10, "hex")) == "$0xA"


# ---------------------------------------------------------------------------
# Code generation engine
# ---------------------------------------------------------------------------

def get_output():
    """Capture what term() would print."""
    return "\n".join(g.g_text)


class TestInit:
    def test_basic(self):
        init()
        out = get_output()
        assert '#include "textflag.h"' in out

    def test_extra_include(self):
        init("go_asm.h")
        out = get_output()
        assert '#include "go_asm.h"' in out

    def test_clears_previous(self):
        init()
        g.emit("MOVL\tAX, BX")
        init()
        out = get_output()
        assert "MOVL" not in out


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------

def last_emitted():
    """Return the last non-empty line added to g_text."""
    for line in reversed(g.g_text):
        if line.strip():
            return line
    return ""


class TestMovInstructions:
    def setup_method(self):
        init()

    def test_movl_reg_reg(self):
        MOVL(AX, BX)
        assert last_emitted() == "\tMOVL\tAX, BX"

    def test_movq_mem_reg(self):
        MOVQ(AX + 8, BX)
        assert last_emitted() == "\tMOVQ\t8(AX), BX"

    def test_movq_reg_mem(self):
        MOVQ(AX, BX + 16)
        assert last_emitted() == "\tMOVQ\tAX, 16(BX)"

    def test_movb_store(self):
        MOVB(AX, SI + 0)
        assert last_emitted() == "\tMOVB\tAX, (SI)"

    def test_movblzx(self):
        MOVBLZX(AX + 0, BX)
        assert last_emitted() == "\tMOVBLZX\t(AX), BX"

    def test_movl_imm(self):
        MOVL(Imm(0, "hex"), AX)
        assert last_emitted() == "\tMOVL\t$0x0, AX"


class TestLeaq:
    def setup_method(self):
        init()

    def test_leaq_basic(self):
        LEAQ(AX + 8, BX)
        assert last_emitted() == "\tLEAQ\t8(AX), BX"

    def test_leaq_indexed(self):
        LEAQ(SI + DI * 1, AX)
        assert last_emitted() == "\tLEAQ\t(SI)(DI*1), AX"

    def test_leaq_offset_indexed(self):
        m = MemOperand(SI, 4, index=DI, scale=2)
        LEAQ(m, AX)
        assert last_emitted() == "\tLEAQ\t4(SI)(DI*2), AX"


class TestShift:
    def setup_method(self):
        init()

    def test_shll_imm(self):
        SHLL(Imm(3), AX)
        assert last_emitted() == "\tSHLL\t$3, AX"

    def test_shrl(self):
        SHRL(CX, AX)
        assert last_emitted() == "\tSHRL\tCX, AX"

    def test_shlq(self):
        SHLQ(Imm(1), R8)
        assert last_emitted() == "\tSHLQ\t$1, R8"


class TestCmov:
    def setup_method(self):
        init()

    def test_cmovlcc(self):
        CMOVLCC(AX, BX)
        assert last_emitted() == "\tCMOVLCC\tAX, BX"

    def test_cmovqeq(self):
        CMOVQEQ(SI, DI)
        assert last_emitted() == "\tCMOVQEQ\tSI, DI"


class TestBranch:
    def setup_method(self):
        init()

    def test_jmp_label(self):
        lb = Label("loop")
        JMP(lb)
        assert last_emitted() == "\tJMP\tloop"

    def test_jcc(self):
        lb = Label("done")
        JCC(lb)
        assert last_emitted() == "\tJCC\tdone"

    def test_jne(self):
        lb = Label("retry")
        JNE(lb)
        assert last_emitted() == "\tJNE\tretry"


class TestArithmetic:
    def setup_method(self):
        init()

    def test_imull(self):
        IMULL(AX, BX)
        assert last_emitted() == "\tIMULL\tAX, BX"

    def test_incq(self):
        INCQ(R10)
        assert last_emitted() == "\tINCQ\tR10"

    def test_negq(self):
        NEGQ(AX)
        assert last_emitted() == "\tNEGQ\tAX"

    def test_addq_imm(self):
        ADDQ(Imm(8), SP)
        assert last_emitted() == "\tADDQ\t$8, SP"

    def test_subq_imm(self):
        SUBQ(Imm(32), SP)
        assert last_emitted() == "\tSUBQ\t$32, SP"


class TestStack:
    def setup_method(self):
        init()

    def test_pushq(self):
        PUSHQ(BX)
        assert last_emitted() == "\tPUSHQ\tBX"

    def test_popq(self):
        POPQ(BX)
        assert last_emitted() == "\tPOPQ\tBX"


class TestRet:
    def setup_method(self):
        init()

    def test_ret_plain(self):
        RET()
        assert last_emitted() == "\tRET"

    def test_ret_with_comment(self):
        RET(comment="done")
        line = last_emitted()
        assert "RET" in line
        assert "// done" in line


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------

class TestFuncContextManager:
    def setup_method(self):
        init()

    def test_basic_func(self):
        with Func("myFunc", nosplit=True, frame=0, args=8):
            RET()
        out = get_output()
        assert "TEXT ·myFunc(SB), NOSPLIT, $0-8" in out

    def test_nosplit_noframe(self):
        with Func("f", nosplit=True, noframe=True, frame=0, args=0):
            pass
        out = get_output()
        assert "NOSPLIT|NOFRAME" in out

    def test_no_flags(self):
        with Func("bare", frame=16, args=24):
            pass
        out = get_output()
        assert "TEXT ·bare(SB), $16-24" in out

    def test_func_adds_trailing_blank(self):
        with Func("g", nosplit=True):
            pass
        # After __exit__, an empty line is appended
        assert g.g_text[-1] == ""


class TestSectionAndComment:
    def setup_method(self):
        init()

    def test_section(self):
        section("My Section")
        out = get_output()
        assert "// " + "=" * 60 in out
        assert "// My Section" in out

    def test_comment(self):
        comment("this is a comment")
        assert last_emitted() == "// this is a comment"

    def test_blank(self):
        blank()
        assert g.g_text[-1] == ""

    def test_label(self):
        lb = Label("loop")
        L(lb)
        assert last_emitted() == "loop:"


class TestComment:
    def setup_method(self):
        init()

    def test_instruction_with_comment(self):
        MOVL(AX, BX, comment="copy ax to bx")
        line = last_emitted()
        assert "MOVL" in line
        assert "AX, BX" in line
        assert "// copy ax to bx" in line
