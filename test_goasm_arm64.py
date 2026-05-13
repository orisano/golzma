import pytest
from goasm_arm64 import (
    Reg, ShiftedReg, Condition,
    MemOperand, Mem, FPArg, Imm, fmt_operand,
    init, emit, emit_raw, term, comment, blank, Label, L,
    R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13,
    R14, R15, R17, R19, R20, R21, R22, R24, R27, R28, R29, R30,
    RSP, ZR,
    EQ, NE, HS, LO, HI, LS, PL, GE, LT,
    g_text,
    MOVD, MOVW, MOVWU, MOVB, MOVBU, MOVBU_P, MOVH, MOVHU, MOVHU_W,
    ADD, ADDS, ADDW, ADDSW, ADCW, SUB, SUBS, SUBW, SUBSW, NEG, MULW,
    CMP, CMPW, CMN, TSTW,
    AND, ANDW, ORR, ORRW, EORW,
    LSL, LSLW, LSRW,
    CSEL, CSELW, CSINCW,
    STP, LDP,
    B, BEQ, BNE, BHI, BHS, BLO, BLS, BLT, BGE,
    CBZ, TBZ,
    RET,
    Func, StackFrame, section,
)


def test_reg_str_64bit():
    assert str(R0) == "R0"
    assert str(R15) == "R15"
    assert str(R30) == "R30"


def test_rsp():
    assert str(RSP) == "RSP"


def test_zr():
    assert str(ZR) == "ZR"


def test_shifted_reg_lsl():
    assert str(R3.lsl(1)) == "R3<<1"


def test_shifted_reg_asr():
    assert str(R4.asr(5)) == "R4->5"


def test_condition_constants():
    assert str(EQ) == "EQ"
    assert str(NE) == "NE"
    assert str(HS) == "HS"
    assert str(LO) == "LO"
    assert str(HI) == "HI"
    assert str(LS) == "LS"
    assert str(PL) == "PL"
    assert str(GE) == "GE"
    assert str(LT) == "LT"


# Reg __add__ / __sub__

def test_reg_add_int():
    assert str(R0 + 16) == "16(R0)"
    assert str(RSP + 80) == "80(RSP)"
    assert str(R11 + 0) == "(R11)"

def test_reg_sub_int():
    assert str(R7 - 1) == "-1(R7)"
    assert str(R9 - 8) == "-8(R9)"

def test_reg_add_str():
    assert str(R0 + "rangeDecoder_code") == "rangeDecoder_code+0(R0)"
    assert str(R7 + "cLzmaDec_buf") == "cLzmaDec_buf+0(R7)"

def test_reg_add_reg():
    assert str(R6 + R1) == "(R6)(R1)"
    assert str(R14 + R2) == "(R14)(R2)"

def test_reg_add_shifted():
    assert str(R11 + R3.lsl(1)) == "(R11)(R3<<1)"
    assert str(R10 + R3.lsl(1)) == "(R10)(R3<<1)"


# Task 2: Memory Operands

def test_mem_offset():
    m = R0.offset(16)
    assert str(m) == "16(R0)"


def test_mem_zero_offset():
    m = R0.offset(0)
    assert str(m) == "(R0)"


def test_mem_negative_offset():
    m = R7.offset(-1)
    assert str(m) == "-1(R7)"


def test_mem_indexed():
    m = Mem(R14, R2)
    assert str(m) == "(R14)(R2)"


def test_mem_indexed_shifted():
    m = Mem(R11, R3.lsl(1))
    assert str(m) == "(R11)(R3<<1)"


def test_fp_arg():
    a = FPArg("lzma", 0)
    assert str(a) == "lzma+0(FP)"


def test_fp_arg_ret():
    a = FPArg("ret", 24)
    assert str(a) == "ret+24(FP)"


def test_sp_offset():
    m = RSP.offset(80)
    assert str(m) == "80(RSP)"


# Task 3: Immediate and Operand Formatting

def test_imm_small():
    assert fmt_operand(0) == "$0"
    assert fmt_operand(128) == "$128"
    assert fmt_operand(255) == "$255"


def test_imm_large_hex():
    assert fmt_operand(256) == "$256"
    assert fmt_operand(2048) == "$2048"


def test_imm_hex_pattern():
    assert fmt_operand(Imm(0xFF000000, fmt="hex")) == "$0xFF000000"


def test_imm_negative():
    assert fmt_operand(-1) == "$-1"
    assert fmt_operand(-511) == "$-511"


def test_fmt_reg():
    assert fmt_operand(R0) == "R0"


def test_fmt_mem():
    assert fmt_operand(R0.offset(16)) == "16(R0)"


def test_fmt_shifted():
    assert fmt_operand(R3.lsl(1)) == "R3<<1"


# Task 4: Code Generation Engine

def test_init_term(capsys):
    init()
    term()
    out = capsys.readouterr().out
    assert '#include "textflag.h"' in out


def test_emit_raw(capsys):
    init()
    emit("MOVD\tR0, R1")
    term()
    out = capsys.readouterr().out
    assert "\tMOVD\tR0, R1\n" in out


def test_comment(capsys):
    init()
    comment("hello")
    term()
    out = capsys.readouterr().out
    assert "// hello\n" in out


def test_label_named(capsys):
    init()
    lp = Label("my_loop")
    L(lp)
    term()
    out = capsys.readouterr().out
    assert "my_loop:" in out


def test_label_auto(capsys):
    init()
    lp = Label()
    L(lp)
    term()
    out = capsys.readouterr().out
    assert "_label_" in out
    assert ":" in out


def test_label_in_str():
    lp = Label("target")
    assert str(lp) == "target"


# Task 5: Instruction Emitter Functions

def test_movd_reg_reg(capsys):
    init()
    MOVD(R0, R1)
    term()
    assert "\tMOVD\tR0, R1\n" in capsys.readouterr().out

def test_add_three_reg(capsys):
    init()
    ADD(R1, R2, R3)
    term()
    assert "\tADD\tR1, R2, R3\n" in capsys.readouterr().out

def test_movw_imm(capsys):
    init()
    MOVW(0, R12)
    term()
    assert "\tMOVW\t$0, R12\n" in capsys.readouterr().out

def test_add_imm(capsys):
    init()
    ADD(128, RSP, RSP)
    term()
    assert "\tADD\t$128, RSP, RSP\n" in capsys.readouterr().out

def test_sub_imm(capsys):
    init()
    SUB(128, RSP, RSP)
    term()
    assert "\tSUB\t$128, RSP, RSP\n" in capsys.readouterr().out

def test_stp(capsys):
    init()
    STP(R19, R20, RSP.offset(0))
    term()
    assert "\tSTP\t(R19, R20), (RSP)\n" in capsys.readouterr().out

def test_stp_offset(capsys):
    init()
    STP(R14, R15, R7.offset(40))
    term()
    assert "\tSTP\t(R14, R15), 40(R7)\n" in capsys.readouterr().out

def test_ldp(capsys):
    init()
    LDP(R0.offset(24), R24, R17)
    term()
    assert "\tLDP\t24(R0), (R24, R17)\n" in capsys.readouterr().out

def test_ldp_zero_offset(capsys):
    init()
    LDP(RSP.offset(0), R19, R20)
    term()
    assert "\tLDP\t(RSP), (R19, R20)\n" in capsys.readouterr().out

def test_movbu_mem(capsys):
    init()
    MOVBU(R7.offset(-1), R3)
    term()
    assert "\tMOVBU\t-1(R7), R3\n" in capsys.readouterr().out

def test_movbu_indexed(capsys):
    init()
    MOVBU(Mem(R24, R7), R3)
    term()
    assert "\tMOVBU\t(R24)(R7), R3\n" in capsys.readouterr().out

def test_cselw(capsys):
    init()
    CSELW(LO, R7, R0, R0)
    term()
    assert "\tCSELW\tLO, R7, R0, R0\n" in capsys.readouterr().out

def test_beq(capsys):
    init()
    lp = Label("target")
    BEQ(lp)
    term()
    assert "\tBEQ\ttarget\n" in capsys.readouterr().out

def test_cbz(capsys):
    init()
    lp = Label("skip")
    CBZ(R7, lp)
    term()
    assert "\tCBZ\tR7, skip\n" in capsys.readouterr().out

def test_tbz(capsys):
    init()
    lp = Label("skip")
    TBZ(31, R0, lp)
    term()
    assert "\tTBZ\t$31, R0, skip\n" in capsys.readouterr().out

def test_movbu_p(capsys):
    init()
    MOVBU_P(R15.offset(1), R7)
    term()
    assert "\tMOVBU.P\t1(R15), R7\n" in capsys.readouterr().out

def test_andw_shifted(capsys):
    init()
    ANDW(R27.lsl(5), R29, R1)
    term()
    assert "\tANDW\tR27<<5, R29, R1\n" in capsys.readouterr().out

def test_tstw_hex(capsys):
    init()
    TSTW(Imm(0xFF000000, "hex"), R0)
    term()
    assert "\tTSTW\t$0xFF000000, R0\n" in capsys.readouterr().out

def test_ret(capsys):
    init()
    RET()
    term()
    assert "\tRET\n" in capsys.readouterr().out

def test_adcw(capsys):
    init()
    ADCW(ZR, R3, R3)
    term()
    assert "\tADCW\tZR, R3, R3\n" in capsys.readouterr().out

def test_movh_indexed(capsys):
    init()
    MOVH(R2, Mem(R6, R1))
    term()
    assert "\tMOVH\tR2, (R6)(R1)\n" in capsys.readouterr().out

def test_neg(capsys):
    init()
    NEG(R2, R2)
    term()
    assert "\tNEG\tR2, R2\n" in capsys.readouterr().out

def test_subw_asr(capsys):
    init()
    SUBW(R7.asr(5), R2, R2)
    term()
    assert "\tSUBW\tR7->5, R2, R2\n" in capsys.readouterr().out

def test_fp_arg_load(capsys):
    init()
    MOVD(FPArg("lzma", 0), R0)
    term()
    assert "\tMOVD\tlzma+0(FP), R0\n" in capsys.readouterr().out

def test_movhu_w(capsys):
    init()
    MOVHU_W(R1, Mem(R11, R3.lsl(1)))
    term()
    assert "\tMOVHU.W\tR1, (R11)(R3<<1)\n" in capsys.readouterr().out

def test_movw_store_fp(capsys):
    init()
    MOVW(R3, FPArg("ret", 24))
    term()
    assert "\tMOVW\tR3, ret+24(FP)\n" in capsys.readouterr().out

def test_b_unconditional(capsys):
    init()
    lp = Label("loop")
    B(lp)
    term()
    assert "\tB\tloop\n" in capsys.readouterr().out

def test_orrw(capsys):
    init()
    ORRW(R27, R8, R7)
    term()
    assert "\tORRW\tR27, R8, R7\n" in capsys.readouterr().out

def test_eorw(capsys):
    init()
    EORW(32, R13, R13)
    term()
    assert "\tEORW\t$32, R13, R13\n" in capsys.readouterr().out

def test_lslw(capsys):
    init()
    LSLW(R29, R7, R29)
    term()
    assert "\tLSLW\tR29, R7, R29\n" in capsys.readouterr().out

def test_lsrw(capsys):
    init()
    LSRW(11, R0, R7)
    term()
    assert "\tLSRW\t$11, R0, R7\n" in capsys.readouterr().out

def test_mulw(capsys):
    init()
    MULW(R1, R7, R7)
    term()
    assert "\tMULW\tR1, R7, R7\n" in capsys.readouterr().out

def test_cmp(capsys):
    init()
    CMP(R24, R14)
    term()
    assert "\tCMP\tR24, R14\n" in capsys.readouterr().out

def test_cmpw_imm(capsys):
    init()
    CMPW(8, R13)
    term()
    assert "\tCMPW\t$8, R13\n" in capsys.readouterr().out

def test_subsw(capsys):
    init()
    SUBSW(R7, R5, R6)
    term()
    assert "\tSUBSW\tR7, R5, R6\n" in capsys.readouterr().out

def test_csincw(capsys):
    init()
    CSINCW(PL, R3, R3, R3)
    term()
    assert "\tCSINCW\tPL, R3, R3, R3\n" in capsys.readouterr().out

def test_movhu_mem(capsys):
    init()
    MOVHU(R11.offset(2), R1)
    term()
    assert "\tMOVHU\t2(R11), R1\n" in capsys.readouterr().out

def test_movh_store_indexed(capsys):
    init()
    MOVH(R4, R11.offset(2))
    term()
    assert "\tMOVH\tR4, 2(R11)\n" in capsys.readouterr().out


# Task 6: Func Context Manager

def test_func_basic(capsys):
    init()
    with Func("lzmaDecodeReal3", nosplit=True, noframe=True, frame=0, args=28):
        MOVD(R0, R1)
    term()
    out = capsys.readouterr().out
    assert "TEXT ·lzmaDecodeReal3(SB), NOSPLIT|NOFRAME, $0-28" in out
    assert "\tMOVD\tR0, R1\n" in out

def test_func_nosplit_only(capsys):
    init()
    with Func("myFunc", nosplit=True, frame=64, args=16):
        RET()
    term()
    out = capsys.readouterr().out
    assert "TEXT ·myFunc(SB), NOSPLIT, $64-16" in out

def test_func_no_flags(capsys):
    init()
    with Func("myFunc", frame=0, args=0):
        RET()
    term()
    out = capsys.readouterr().out
    assert "TEXT ·myFunc(SB), $0-0" in out


# Task 7: StackFrame Context Manager

def test_stackframe_basic(capsys):
    init()
    with Func("myFunc", nosplit=True, noframe=True, args=24):
        with StackFrame(saves=[R19, R20, R21, R22], frame_extra=0):
            MOVD(R0, R1)
    term()
    out = capsys.readouterr().out
    assert "\tSUB\t$32, RSP, RSP\n" in out
    assert "\tSTP\t(R19, R20), (RSP)\n" in out
    assert "\tSTP\t(R21, R22), 16(RSP)\n" in out
    assert "\tMOVD\tR0, R1\n" in out
    # Epilogue
    assert "\tLDP\t(RSP), (R19, R20)\n" in out
    assert "\tLDP\t16(RSP), (R21, R22)\n" in out
    assert "\tADD\t$32, RSP, RSP\n" in out
    assert "\tRET\n" in out

def test_stackframe_odd_regs(capsys):
    init()
    with Func("myFunc", nosplit=True, noframe=True, args=0):
        with StackFrame(saves=[R19, R20, R21], frame_extra=0):
            pass
    term()
    out = capsys.readouterr().out
    assert "\tSUB\t$32, RSP, RSP\n" in out  # 24 aligned to 32
    assert "\tSTP\t(R19, R20), (RSP)\n" in out
    assert "\tMOVD\tR21, 16(RSP)\n" in out

def test_stackframe_extra(capsys):
    init()
    with Func("myFunc", nosplit=True, noframe=True, args=0):
        with StackFrame(saves=[R19, R20], frame_extra=48):
            pass
    term()
    out = capsys.readouterr().out
    assert "\tSUB\t$64, RSP, RSP\n" in out  # 16 + 48 = 64

def test_stackframe_no_ret(capsys):
    init()
    with Func("myFunc", nosplit=True, noframe=True, args=0):
        with StackFrame(saves=[R19, R20], call_ret=False):
            pass
    term()
    out = capsys.readouterr().out
    assert "\tRET\n" not in out


# Task 8: Inline Comment Support

def test_instruction_with_comment(capsys):
    init()
    MOVD(R0, R1, comment="load arg")
    term()
    out = capsys.readouterr().out
    assert "MOVD\tR0, R1" in out
    assert "// load arg" in out

def test_stp_with_comment(capsys):
    init()
    STP(R19, R20, RSP.offset(0), comment="save regs")
    term()
    out = capsys.readouterr().out
    assert "STP\t(R19, R20), (RSP)" in out
    assert "// save regs" in out

def test_ret_with_comment(capsys):
    init()
    RET(comment="return")
    term()
    out = capsys.readouterr().out
    assert "RET" in out
    assert "// return" in out


# Task 9: Section Comments

def test_section(capsys):
    init()
    section("LITERAL decode")
    term()
    out = capsys.readouterr().out
    assert "// ====" in out
    assert "// LITERAL decode" in out
