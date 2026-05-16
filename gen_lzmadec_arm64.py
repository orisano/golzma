#!/usr/bin/env python3
"""Generate lzmadec_arm64.s using goasm_arm64 DSL.

Structured after LzmaDecOpt.S (Igor Pavlov, Public domain).
Macro structure mirrors the original C-preprocessor/GAS macros
but emits Go Plan 9 ARM64 assembly.

Usage: python3 gen_lzmadec_arm64.py > lzmadec_arm64.s
"""
from goasm_arm64 import *

# ============================================================
# Constants (matching .equ definitions in LzmaDecOpt.S)
# ============================================================
PSHIFT = 1
PMULT = 1 << PSHIFT        # 2
PMULT_2 = 2 << PSHIFT      # 4

kNumBitModelTotalBits = 11
kBitModelTotal = 1 << kNumBitModelTotalBits         # 2048
kNumMoveBits = 5
kBitModelOffset = kBitModelTotal - (1 << kNumMoveBits) + 1  # 2017

kMatchSpecLen_Error_Data = 1 << 9   # 512

kNumPosBitsMax = 4
kNumPosStatesMax = 1 << kNumPosBitsMax
kLenNumLowBits = 3
kLenNumLowSymbols = 1 << kLenNumLowBits
kLenNumHighBits = 8
kLenNumHighSymbols = 1 << kLenNumHighBits
kNumLenProbs = 2 * kLenNumLowSymbols * kNumPosStatesMax + kLenNumHighSymbols

LenLow = 0
LenChoice = LenLow
LenChoice2 = LenLow + kLenNumLowSymbols
LenHigh = LenLow + 2 * kLenNumLowSymbols * kNumPosStatesMax

kNumStates = 12
kNumStates2 = 16
kNumLitStates = 7

kStartPosModelIndex = 4
kEndPosModelIndex = 14
kNumFullDistances = 1 << (kEndPosModelIndex >> 1)

kNumPosSlotBits = 6
kNumLenToPosStates = 4
kNumAlignBits = 4
kAlignTableSize = 1 << kNumAlignBits

kMatchMinLen = 2
kMatchSpecLenStart = kMatchMinLen + kLenNumLowSymbols * 2 + kLenNumHighSymbols

kStartOffset = 0
SpecPos = -kStartOffset
IsRep0Long = SpecPos + kNumFullDistances
RepLenCoder = IsRep0Long + (kNumStates2 << kNumPosBitsMax)
LenCoder = RepLenCoder + kNumLenProbs
IsMatch = LenCoder + kNumLenProbs
kAlign = IsMatch + (kNumStates2 << kNumPosBitsMax)
IsRep = kAlign + kAlignTableSize
IsRepG0 = IsRep + kNumStates
IsRepG1 = IsRepG0 + kNumStates
IsRepG2 = IsRepG1 + kNumStates
PosSlot = IsRepG2 + kNumStates
Literal = PosSlot + (kNumLenToPosStates << kNumPosSlotBits)

assert Literal == 1984

FLAG_STATE_BITS = 4 + PSHIFT  # 5

HEX_FF = Imm(0xFF000000, "hex")

# ============================================================
# Register aliases (matching LzmaDecOpt.S #define names)
# Go remapping: R28 reserved (g), R30 reserved (LR)
#   limit -> stack spill (was R19 in C, but Go needs R19-R27 as callee-saved)
#   checkDicSize -> stack spill (was R27 in C)
#   processedPos -> R27 (was R28 in C, R28 is Go's g)
#   pbMask -> R29 (was R29 in C, saved/restored manually)
#   lc2_lpMask -> R19 (was R30 in C, R30 is LR)
# ============================================================
range_     = R0     # w0
pbPos      = R1     # w1, also prob_reg, litm_prob
prob_reg   = R1
probBranch = R2     # w2, also cnt, prm
cnt        = R2
sym        = R3     # w3, also dist
dist       = R3
t3         = R4     # w4, also bit
bit        = R4
cod        = R5     # w5
t1         = R6     # w6, also probs_state
probs_state = R6
t0         = R7     # w7, also prob2
prob2      = R7
t2         = R8     # w8
match      = R9     # w9, also sym2
sym2       = R9
t4         = R10    # w10, also offs, numBits, probs_PMULT
offs       = R10
numBits    = R10
probs_PMULT = R10
probs      = R11    # r11
len_       = R12    # w12
state      = R13    # w13
dicPos     = R14    # r14
buf        = R15    # r15
bufLimit   = R16    # r16
dicBufSize = R17    # r17
# R18 reserved
lc2_lpMask = R19    # remapped from R30
rep0       = R20    # w20
rep1       = R21    # w21
rep2       = R22    # w22
rep3       = R23    # w23
dic        = R24    # r24
probs_IsMatch = R25  # r25
probs_Spec = R26    # r26
processedPos = R27  # remapped from R28
# R28 reserved (Go g register)
pbMask     = R29    # saved/restored manually
# R30 reserved (LR)

# Stack frame layout (128 bytes):
#   0-72:  callee-saved R19-R27, R29
#  80:     limit (64-bit)
#  88:     checkDicSize (32-bit in 64-bit slot)
#  96:     PARAM_lzma (64-bit)
STACK_FRAME = 128
SPILL_LIMIT = 80
SPILL_CHECK = 88
SPILL_LZMA = 96


# ============================================================
# Macro functions — mirrors LzmaDecOpt.S GAS macros
# ============================================================

_norm_counter = 0

def _norm_label():
    global _norm_counter
    _norm_counter += 1
    return Label(f"norm_{_norm_counter}")


def NORM_2():
    """NORM_2: unconditional byte fetch."""
    MOVBU_P(buf + 1, t0)
    LSLW(8, range_, range_)
    ORRW(cod.lsl(8), t0, cod)


def NORM():
    """NORM: conditional normalization."""
    lbl = _norm_label()
    TSTW(HEX_FF, range_)
    BNE(lbl)
    NORM_2()
    L(lbl)


def NORM_LSR():
    """NORM + lsr t0, range, #kNumBitModelTotalBits."""
    NORM()
    LSRW(kNumBitModelTotalBits, range_, t0)


def RANGE_IMUL(prob):
    MULW(prob, t0, t0)


def COD_RANGE_SUB():
    SUBSW(t0, cod, t1)
    SUBW(t0, range_, range_)


def NORM_CALC(prob):
    NORM_LSR()
    RANGE_IMUL(prob)
    COD_RANGE_SUB()


def CMOV_range():
    CSELW(LO, t0, range_, range_)


def CMOV_code():
    CSELW(HS, t1, cod, cod)


def CMOV_code_Model_Pre(prob):
    SUBW(kBitModelOffset, prob, t0)
    CMOV_code()
    CSELW(HS, prob, t0, t0)


def PUP_BASE_2(prob, dest_reg):
    SUBW(dest_reg.asr(kNumMoveBits), prob, dest_reg)


def PUP(prob, probPtr, mem2):
    PUP_BASE_2(prob, t0)
    MOVH(t0, probPtr + mem2)


def PLOAD(dest, mem):
    MOVHU(mem + 0, dest)


def PLOAD_2(dest, mem1, mem2):
    MOVHU(mem1 + mem2, dest)


def PLOAD_LSL(dest, mem1, mem2):
    MOVHU(mem1 + mem2.lsl(PSHIFT), dest)


def PLOAD_PREINDEXED(dest, mem, offset):
    MOVHU_W(mem + offset, dest)


def PSTORE(src, mem):
    MOVH(src, mem + 0)


def PSTORE_2(src, mem1, mem2):
    MOVH(src, mem1 + mem2)


def PSTORE_LSL(src, mem1, mem2):
    MOVH(src, mem1 + mem2.lsl(PSHIFT))


def PSTORE_LSL_M1(src, mem1, mem2):
    MOVH(src, mem1 + mem2)


# ---------- Branch MACROS ----------

def UPDATE_0__0():
    SUBW(kBitModelOffset, probBranch, prob2)


def UPDATE_0__1():
    SUBW(prob2.asr(kNumMoveBits), probBranch, probBranch)


def UPDATE_0__2(probsArray, probOffset, probDisp):
    if probDisp == 0:
        PSTORE_2(probBranch, probsArray, probOffset)
    elif probOffset == 0:
        PSTORE_2(probBranch, probsArray, probDisp * PMULT)
    else:
        raise ValueError("unsupported")


def UPDATE_0(probsArray, probOffset, probDisp):
    UPDATE_0__0()
    UPDATE_0__1()
    UPDATE_0__2(probsArray, probOffset, probDisp)


def UPDATE_1(probsArray, probOffset, probDisp):
    SUBW(range_, cod, cod)
    SUBW(range_, prob2, range_)
    SUBW(probBranch.asr(kNumMoveBits), probBranch, prob2)
    if probDisp == 0:
        PSTORE_2(prob2, probsArray, probOffset)
    elif probOffset == 0:
        PSTORE_2(prob2, probsArray, probDisp * PMULT)
    else:
        raise ValueError("unsupported")


def CMP_COD_BASE():
    NORM()
    MOVD(range_, prob2)
    LSRW(kNumBitModelTotalBits, range_, range_)
    MULW(probBranch, range_, range_)
    CMPW(range_, cod)


def CMP_COD_1(probsArray):
    PLOAD(probBranch, probsArray)
    CMP_COD_BASE()


def CMP_COD_3(probsArray, probOffset, probDisp):
    if probDisp == 0:
        PLOAD_2(probBranch, probsArray, probOffset)
    elif probOffset == 0:
        PLOAD_2(probBranch, probsArray, probDisp * PMULT)
    else:
        raise ValueError("unsupported")
    CMP_COD_BASE()


def IF_BIT_1_NOUP(probsArray, probOffset, probDisp, toLabel):
    CMP_COD_3(probsArray, probOffset, probDisp)
    BHS(toLabel)


def IF_BIT_1(probsArray, probOffset, probDisp, toLabel):
    IF_BIT_1_NOUP(probsArray, probOffset, probDisp, toLabel)
    UPDATE_0(probsArray, probOffset, probDisp)


def IF_BIT_0_NOUP(probsArray, probOffset, probDisp, toLabel):
    CMP_COD_3(probsArray, probOffset, probDisp)
    BLO(toLabel)


def IF_BIT_0_NOUP_1(probsArray, toLabel):
    CMP_COD_1(probsArray)
    BLO(toLabel)


# ---------- CMOV MACROS ----------

def BIT_01():
    ADD(PMULT, probs, probs_PMULT)


def BIT_0_R(prob):
    PLOAD_2(prob, probs, 1 * PMULT)
    NORM_LSR()
    SUBW(kBitModelOffset, prob, t3)
    RANGE_IMUL(prob)
    PLOAD_2(t2, probs, 1 * PMULT_2)
    COD_RANGE_SUB()
    CMOV_range()
    CSELW(HS, prob, t3, t3)
    PLOAD_2(t0, probs, 1 * PMULT_2 + PMULT)
    PUP_BASE_2(prob, t3)
    CSELW(LO, t2, t0, prob)
    CMOV_code()
    MOVW(2, sym)
    PSTORE_2(t3, probs, 1 * PMULT)
    ADCW(ZR, sym, sym)
    BIT_01()


def BIT_1_R(prob):
    NORM_LSR()
    ADDW(sym, sym, sym)
    SUBW(kBitModelOffset, prob, t3)
    RANGE_IMUL(prob)
    PLOAD_LSL(t2, probs, sym)
    COD_RANGE_SUB()
    CMOV_range()
    CSELW(HS, prob, t3, t3)
    PLOAD_LSL(t0, probs_PMULT, sym)
    PUP_BASE_2(prob, t3)
    CSELW(LO, t2, t0, prob)
    CMOV_code()
    PSTORE_LSL_M1(t3, probs, sym)
    ADCW(ZR, sym, sym)


def BIT_2_R(prob):
    NORM_LSR()
    ADDW(sym, sym, sym)
    SUBW(kBitModelOffset, prob, t3)
    RANGE_IMUL(prob)
    COD_RANGE_SUB()
    CMOV_range()
    CSELW(HS, prob, t3, t3)
    CMOV_code()
    PUP_BASE_2(prob, t3)
    PSTORE_LSL_M1(t3, probs, sym)
    ADCW(ZR, sym, sym)


# Convenience: BIT_0/1/2 with prob_reg
def BIT_0(): BIT_0_R(prob_reg)
def BIT_1(): BIT_1_R(prob_reg)
def BIT_2(): BIT_2_R(prob_reg)


# ---------- MATCHED LITERAL ----------

def LITM_0():
    LSLW(PSHIFT + 1, match, match)
    ANDW(256 * PMULT, match, bit)
    ADD(256 * PMULT + 1 * PMULT, probs, cnt)
    ADDW(match, match, match)
    ADD(bit, cnt, cnt)
    EORW(256 * PMULT, bit, offs)
    PLOAD(prob_reg, cnt)
    NORM_LSR()
    SUBW(kBitModelOffset, prob_reg, t2)
    RANGE_IMUL(prob_reg)
    COD_RANGE_SUB()
    CSELW(HS, bit, offs, offs)
    CMOV_range()
    ANDW(offs, match, bit)
    CSELW(HS, prob_reg, t2, t2)
    CMOV_code()
    MOVW(2, sym)
    PUP_BASE_2(prob_reg, t2)
    PSTORE(t2, cnt)
    ADD(offs, probs, cnt)
    ADCW(ZR, sym, sym)


def LITM():
    ADD(bit, cnt, cnt)
    EORW(bit, offs, offs)
    PLOAD_LSL(prob_reg, cnt, sym)
    NORM_LSR()
    ADDW(match, match, match)
    SUBW(kBitModelOffset, prob_reg, t2)
    RANGE_IMUL(prob_reg)
    COD_RANGE_SUB()
    CSELW(HS, bit, offs, offs)
    CMOV_range()
    ANDW(offs, match, bit)
    CSELW(HS, prob_reg, t2, t2)
    CMOV_code()
    PUP_BASE_2(prob_reg, t2)
    PSTORE_LSL(t2, cnt, sym)
    ADD(offs, probs, cnt)
    ADCW(sym, sym, sym)


def LITM_2():
    ADD(bit, cnt, cnt)
    PLOAD_LSL(prob_reg, cnt, sym)
    NORM_LSR()
    SUBW(kBitModelOffset, prob_reg, t2)
    RANGE_IMUL(prob_reg)
    COD_RANGE_SUB()
    CMOV_range()
    CSELW(HS, prob_reg, t2, t2)
    CMOV_code()
    PUP_BASE_2(prob_reg, t2)
    PSTORE_LSL(t2, cnt, sym)
    ADCW(sym, sym, sym)


# ---------- REVERSE BITS ----------

def ALIGN_BIT(bit_index, label):
    """Decode one alignment bit using the C SDK's REV_BIT_CONST tree layout.

    Uses sym2 (R9) as byte offset (i*PMULT) into the alignment prob table
    (probs/R11). After decoding, sym2 advances by m*PMULT (bit=0) or
    2*m*PMULT (bit=1), where m = 1 << bit_index, mirroring the linear-index
    pattern of LzmaDec.c so the asm and pure-Go fallback agree on the
    layout. Accumulates the decoded bit into sym (R3) via OR.
    """
    m = 1 << bit_index
    NORM()
    MOVHU(probs + sym2, prob_reg)
    LSRW(kNumBitModelTotalBits, range_, t0)
    RANGE_IMUL(prob_reg)
    COD_RANGE_SUB()
    CMOV_range()
    CMOV_code()
    SUBW(kBitModelOffset, prob_reg, t2)
    CSELW(HS, prob_reg, t2, t2)
    PUP_BASE_2(prob_reg, t2)
    MOVH(t2, probs + sym2)
    # sym2 += m*PMULT (bit=0) or 2*m*PMULT (bit=1)
    MOVW(m * PMULT, t2)
    MOVW(2 * m * PMULT, t3)
    CSELW(HS, t3, t2, t2)
    ADDW(t2, sym2, sym2)
    # distance |= (1 << bit_index) if bit == 1
    ORRW(1 << bit_index, sym, t2)
    CSELW(HS, t2, sym, sym)


def ALIGN_BIT_LAST(bit_index):
    """Decode the last alignment bit (no tree index update needed)."""
    NORM()
    MOVHU(probs + sym2, prob_reg)
    LSRW(kNumBitModelTotalBits, range_, t0)
    RANGE_IMUL(prob_reg)
    COD_RANGE_SUB()
    CMOV_range()
    CMOV_code()
    SUBW(kBitModelOffset, prob_reg, t2)
    CSELW(HS, prob_reg, t2, t2)
    PUP_BASE_2(prob_reg, t2)
    MOVH(t2, probs + sym2)
    ORRW(1 << bit_index, sym, t2)
    CSELW(HS, t2, sym, sym)


def REV_1_VAR(prob):
    PLOAD(prob, sym)
    MOVD(sym, probs)
    ADD(sym2, sym, sym)
    NORM_LSR()
    ADD(sym2, sym, t2)
    RANGE_IMUL(prob)
    COD_RANGE_SUB()
    CSEL(HS, t2, sym, sym)
    CMOV_range()
    CMOV_code_Model_Pre(prob)
    ADDW(sym2, sym2, sym2)
    PUP(prob, probs, 0)


def SET_probs(offset):
    v = (offset - IsMatch) * PMULT
    if v >= 0:
        ADD(v, probs_IsMatch, probs)
    else:
        SUB(-v, probs_IsMatch, probs)


def LIT_PROBS():
    ADDW(processedPos.lsl(8), sym, sym)
    ADDW(1, processedPos, processedPos)
    UPDATE_0__0()
    LSLW(lc2_lpMask, sym, sym)
    SET_probs(Literal)
    ANDW(lc2_lpMask, sym, sym)
    ADD(sym, probs, probs)
    UPDATE_0__1()
    ADD(sym.lsl(1), probs, probs)
    UPDATE_0__2(probs_state, pbPos, 0)


def IsMatchBranch_Pre():
    ANDW(processedPos.lsl(kLenNumLowBits + 1 + PSHIFT), pbMask, pbPos)
    ADD(state, probs_IsMatch, probs_state)


def CheckLimits(fin_OK):
    CMP(bufLimit, buf)
    BHS(fin_OK)
    MOVD(RSP + SPILL_LIMIT, t0)
    CMP(t0, dicPos)
    BHS(fin_OK)


def DIRECT_1_emit(end_label):
    LSRW(1, range_, range_)
    SUBSW(range_, cod, t0)
    ADDW(sym, sym, sym)
    CSELW(PL, t0, cod, cod)
    CSINCW(MI, sym, sym, sym)
    SUBSW(1, numBits, numBits)
    BEQ(end_label)


def DIRECT_2_emit(unroll_label, end_label):
    TSTW(HEX_FF, range_)
    BEQ(unroll_label)
    DIRECT_1_emit(end_label)


def STATE_UPDATE_FOR_MATCH():
    CMPW(kNumLitStates * PMULT + (1 << FLAG_STATE_BITS), state)
    MOVW(kNumLitStates * PMULT, state)
    MOVW((kNumLitStates + 3) * PMULT, t0)
    CSELW(HS, t0, state, state)


# ============================================================
# Main generation
# ============================================================

def main():
    init("go_asm.h")

    comment("LzmaDecOpt_arm64.s -- Go ARM64 assembly version of LzmaDec_DecodeReal_3()")
    comment("Generated by gen_lzmadec_arm64.py from LzmaDecOpt.S structure")
    comment("Original: Igor Pavlov, Public domain")
    comment("Configuration: PSHIFT=1 (16-bit probs), unrolled, LZMA_USE_4BYTES_FILL=1")
    blank()

    # Labels
    lit_start       = Label("lit_start")
    lit_start_2     = Label("lit_start_2")
    lit_end         = Label("lit_end")
    lit_matched_end = Label("lit_matched_end")
    lz_end          = Label("lz_end")
    lz_end_match    = Label("lz_end_match")
    lz_check_limits = Label("lz_check_limits")
    IsMatch_label   = Label("IsMatch_label")
    IsRep_label     = Label("IsRep_label")
    IsRep0Short_label = Label("IsRep0Short_label")
    IsRepG0_label   = Label("IsRepG0_label")
    IsRepG1_label   = Label("IsRepG1_label")
    IsRepG2_label   = Label("IsRepG2_label")
    len_decode      = Label("len_decode")
    len_mid_0       = Label("len_mid_0")
    len_mid_2       = Label("len_mid_2")
    len8_loop       = Label("len8_loop")
    copy_match      = Label("copy_match")
    copy_end        = Label("copy_end")
    copy_no_wrap    = Label("copy_no_wrap")
    copy_no_wrap_byte = Label("copy_no_wrap_byte")
    copy_common     = Label("copy_common")
    copy_byte_loop  = Label("copy_byte_loop")
    copy_word_align = Label("copy_word_align")
    copy_word_loop  = Label("copy_word_loop")
    copy_match_0    = Label("copy_match_0")
    copy_match_0_small = Label("copy_match_0_small")
    copy_wide_loop  = Label("copy_wide_loop")
    copy_wide_tail  = Label("copy_wide_tail")
    copy_wide_done  = Label("copy_wide_done")
    copy_match_cross = Label("copy_match_cross")
    copy_cross_loop = Label("copy_cross_loop")
    short_dist      = Label("short_dist")
    spec_loop       = Label("spec_loop")
    direct_unroll   = Label("direct_unroll")
    direct_end      = Label("direct_end")
    decode_dist_end = Label("decode_dist_end")
    rep0short_no_wrap = Label("rep0short_no_wrap")
    litm_no_wrap    = Label("litm_no_wrap")
    fin             = Label("fin")
    fin_OK          = Label("fin_OK")
    fin_ERROR       = Label("fin_ERROR_MATCH_DIST")
    end_of_payload  = Label("end_of_payload")
    init_skip_prev  = Label("init_skip_prev")

    section("Function entry")

    with Func("lzmaDecodeReal3", nosplit=True, noframe=True, frame=0, args=28):
        comment("Load arguments before adjusting RSP (ABI0: args on stack)")
        MOVD(FPArg("lzma", 0), R0)
        MOVD(FPArg("limit", 8), R1)
        MOVD(FPArg("bufLimit", 16), R2)
        blank()

        comment("Allocate stack frame")
        SUB(STACK_FRAME, RSP, RSP)
        blank()

        comment("Save callee-saved registers")
        STP(R19, R20, RSP + 0)
        STP(R21, R22, RSP + 16)
        STP(R23, R24, RSP + 32)
        STP(R25, R26, RSP + 48)
        MOVD(R27, RSP + 64)
        MOVD(R29, RSP + 72)
        blank()

        comment("Save PARAM_lzma")
        MOVD(R0, RSP + SPILL_LZMA)
        blank()

        MOVD(R2, bufLimit)
        MOVD(R1, RSP + SPILL_LIMIT)
        blank()

        comment("Load struct fields")
        LDP(R0 + "cLzmaDec_dic", dic, dicBufSize)
        LDP(R0 + "cLzmaDec_dicPos", dicPos, buf)
        MOVW(R0 + "cLzmaDec_rep0", rep0)
        MOVW(R0 + "cLzmaDec_rep1", rep1)
        MOVW(R0 + "cLzmaDec_rep2", rep2)
        MOVW(R0 + "cLzmaDec_rep3", rep3)
        blank()

        MOVW(1 << (kLenNumLowBits + 1 + PSHIFT), t0)
        MOVBU(R0 + "cLzmaDec_pb", pbMask)
        MOVD(RSP + SPILL_LIMIT, R1)
        ADD(dic, R1, R1)
        MOVD(R1, RSP + SPILL_LIMIT)
        MOVW(0, len_)
        LSLW(pbMask, t0, pbMask)
        ADD(dic, dicPos, dicPos)
        SUBW(t0, pbMask, pbMask)
        blank()

        MOVBU(R0 + "cLzmaDec_lc", lc2_lpMask)
        MOVW(256 << PSHIFT, t0)
        MOVBU(R0 + "cLzmaDec_lp", t1)
        ADDW(lc2_lpMask, t1, t1)
        SUBW((256 << PSHIFT) - PSHIFT, lc2_lpMask, lc2_lpMask)
        LSLW(t1, t0, t0)
        ADDW(t0, lc2_lpMask, lc2_lpMask)
        blank()

        MOVD(R0 + "cLzmaDec_probs", probs_Spec)
        MOVW(R0 + "cLzmaDec_checkDicSize", t2)
        MOVW(t2, RSP + SPILL_CHECK)
        MOVW(R0 + "cLzmaDec_processedPos", processedPos)
        MOVW(R0 + "cLzmaDec_state", state)
        MOVW(R0 + "cLzmaDec_code", cod)
        MOVW(R0 + "cLzmaDec_rng", range_)
        MOVW(0, sym)
        LSLW(PSHIFT, state, state)
        blank()

        ADD((IsMatch - SpecPos) * PMULT, probs_Spec, probs_IsMatch)
        blank()

        comment("if (processedPos != 0 || checkDicSize != 0)")
        MOVW(RSP + SPILL_CHECK, t2)
        ORRW(processedPos, t2, t0)
        CBZ(t0, init_skip_prev)
        ADD(dicBufSize, dic, t0)
        CMP(dic, dicPos)
        CSEL(NE, dicPos, t0, t0)
        MOVBU(t0 + -1, sym)
        L(init_skip_prev)
        blank()

        IsMatchBranch_Pre()
        CMPW(4 * PMULT, state)
        BLO(lit_end)
        CMPW(kNumLitStates * PMULT, state)
        BLO(lit_matched_end)
        B(lz_end)
        blank()

        # ==================== LITERAL ====================
        section("LITERAL")
        L(lit_start)
        MOVW(0, state)
        L(lit_start_2)
        LIT_PROBS()
        blank()
        BIT_0()
        for i in range(6):
            BIT_1()
        blank()
        BIT_2()
        IsMatchBranch_Pre()
        MOVB(sym, dicPos + 0)
        ADD(1, dicPos, dicPos)
        ANDW(255, sym, sym)
        blank()
        CheckLimits(fin_OK)
        L(lit_end)
        IF_BIT_0_NOUP(probs_state, pbPos, 0, lit_start)
        blank()

        # ==================== MATCHES ====================
        section("MATCHES")
        L(IsMatch_label)
        UPDATE_1(probs_state, pbPos, 0)
        IF_BIT_1(probs_state, 0, IsRep - IsMatch, IsRep_label)
        blank()
        SET_probs(LenCoder)
        ORRW(1 << FLAG_STATE_BITS, state, state)
        blank()

        # ==================== LEN DECODE ====================
        section("LEN DECODE")
        L(len_decode)
        MOVW(8 - kMatchMinLen, len_)
        IF_BIT_0_NOUP_1(probs, len_mid_0)
        UPDATE_1(probs, 0, 0)
        ADD(1 << (kLenNumLowBits + PSHIFT), probs, probs)
        MOVW(0 - kMatchMinLen, len_)
        IF_BIT_0_NOUP_1(probs, len_mid_0)
        UPDATE_1(probs, 0, 0)
        ADD(LenHigh * PMULT - (1 << (kLenNumLowBits + PSHIFT)), probs, probs)
        blank()

        PLOAD_2(prob_reg, probs, 1 * PMULT)
        MOVW(1, sym)
        BIT_01()
        L(len8_loop)
        BIT_1()
        TBZ(6, sym, len8_loop)
        blank()
        MOVW((kLenNumHighSymbols - kLenNumLowSymbols * 2) - kMatchMinLen, len_)
        B(len_mid_2)
        blank()

        L(len_mid_0)
        UPDATE_0(probs, 0, 0)
        ADD(pbPos, probs, probs)
        BIT_0()
        L(len_mid_2)
        BIT_1()
        BIT_2()
        SUBW(len_, sym, len_)
        TBZ(FLAG_STATE_BITS, state, copy_match)
        blank()

        # ==================== DECODE DISTANCE ====================
        section("DECODE DISTANCE")
        MOVW(3 + kMatchMinLen, t0)
        CMPW(3 + kMatchMinLen, len_)
        CSELW(LO, len_, t0, t0)
        SET_probs(PosSlot - (kMatchMinLen << kNumPosSlotBits))
        ADD(t0.lsl(kNumPosSlotBits + PSHIFT), probs, probs)
        blank()

        BIT_0()
        for i in range(4):
            BIT_1()
        blank()

        MOVD(sym, numBits)
        BIT_2()
        ANDW(3, sym, sym)
        CMPW(32 + kEndPosModelIndex // 2, numBits)
        BLO(short_dist)
        blank()

        SET_probs(kAlign)
        SUBW(32 + 1 + kNumAlignBits, numBits, numBits)
        ORRW(2, sym, sym)
        blank()

        # ==================== DIRECT DISTANCE ====================
        section("DIRECT DISTANCE")
        for _ in range(8):
            DIRECT_2_emit(direct_unroll, direct_end)
        blank()
        L(direct_unroll)
        NORM_2()
        for i in range(8):
            DIRECT_1_emit(direct_end)
        B(direct_unroll)
        blank()

        L(direct_end)
        LSLW(kNumAlignBits, sym, sym)
        # Alignment bit decoding using standard binary tree traversal.
        # sym2 tracks byte offset (ai*2) into the alignment prob table.
        MOVW(1 * PMULT, sym2)
        align_labels = [Label(f"align_norm_{i}") for i in range(kNumAlignBits)]
        for i in range(kNumAlignBits - 1):
            comment(f"Alignment bit {i} (distance |= {1 << i})")
            ALIGN_BIT(i, align_labels[i])
        comment(f"Alignment bit {kNumAlignBits - 1} (distance |= {1 << (kNumAlignBits - 1)})")
        ALIGN_BIT_LAST(kNumAlignBits - 1)
        blank()

        L(decode_dist_end)
        MOVW(RSP + SPILL_CHECK, t2)
        TSTW(t2, t2)
        CSELW(EQ, processedPos, t2, t0)
        CMPW(t0, sym)
        BHS(end_of_payload)
        blank()

        MOVD(rep2, rep3)
        MOVD(rep1, rep2)
        MOVD(rep0, rep1)
        ADDW(1, sym, rep0)
        STATE_UPDATE_FOR_MATCH()
        blank()

        # ==================== COPY MATCH ====================
        section("COPY MATCH")
        L(copy_match)
        MOVD(RSP + SPILL_LIMIT, t0)
        SUBS(dicPos, t0, cnt)
        BEQ(fin_OK)
        blank()

        CMP(len_, cnt)
        CSEL(HS, len_, cnt, cnt)
        blank()

        SUB(dic, dicPos, t0)
        ADD(cnt, dicPos, dicPos)
        ADDW(cnt, processedPos, processedPos)
        SUBW(cnt, len_, len_)
        blank()

        SUBS(rep0, t0, t0)
        BHS(copy_no_wrap)
        blank()

        CMN(cnt, t0)
        ADD(dicBufSize, t0, t0)
        BHI(copy_match_cross)
        blank()

        L(copy_no_wrap)
        ADD(dic, t0, t0)
        blank()

        comment("Wide copy path: non-overlapping (rep0 >= curLen) and curLen >= 16")
        CMP(cnt, rep0)
        BLO(copy_no_wrap_byte)
        CMP(16, cnt)
        BLO(copy_no_wrap_byte)
        blank()

        SUB(cnt, dicPos, match)
        AND(-16, cnt, t2)
        L(copy_wide_loop)
        LDP(t0 + 0, t3, t4)
        STP(t3, t4, match + 0)
        ADD(16, t0, t0)
        ADD(16, match, match)
        SUBS(16, t2, t2)
        BNE(copy_wide_loop)
        AND(15, cnt, t2)
        CBZ(t2, copy_wide_done)
        L(copy_wide_tail)
        MOVBU(t0 + 0, t3)
        MOVB(t3, match + 0)
        ADD(1, t0, t0)
        ADD(1, match, match)
        SUBS(1, t2, t2)
        BNE(copy_wide_tail)
        L(copy_wide_done)
        MOVBU(match + -1, sym)
        IsMatchBranch_Pre()
        B(lz_check_limits)
        blank()

        L(copy_no_wrap_byte)
        MOVBU(t0 + 0, sym)
        ADD(cnt, t0, t0)
        NEG(cnt, cnt)
        blank()

        L(copy_common)
        SUB(1, dicPos, dicPos)
        blank()

        IsMatchBranch_Pre()
        blank()

        ADDS(1, cnt, cnt)
        BEQ(copy_end)
        blank()

        CMPW(1, rep0)
        BEQ(copy_match_0)
        blank()

        comment("4-byte copy when rep0 >= 4 and count >= 4")
        CMPW(4, rep0)
        BLO(copy_byte_loop)
        CMN(4, cnt)
        BHI(copy_byte_loop)
        blank()

        comment("Flush pending R3 byte from pipelined load, then switch to")
        comment("non-pipelined access for word-aligned copies.")
        MOVB(sym, dicPos + cnt)
        ADDS(1, cnt, cnt)
        BEQ(copy_end)
        SUB(1, t0, t0)
        blank()

        comment("Byte alignment until R2 is a multiple of 4")
        L(copy_word_align)
        TSTW(3, cnt)
        BEQ(copy_word_loop)
        MOVBU(t0 + cnt, sym)
        MOVB(sym, dicPos + cnt)
        ADDS(1, cnt, cnt)
        BNE(copy_word_align)
        MOVBU(t0 + 0, sym)
        B(copy_end)
        blank()

        L(copy_word_loop)
        MOVWU(t0 + cnt, t3)
        MOVW(t3, dicPos + cnt)
        ADDS(4, cnt, cnt)
        BNE(copy_word_loop)
        MOVBU(t0 + 0, sym)
        B(copy_end)
        blank()

        L(copy_byte_loop)
        MOVB(sym, dicPos + cnt)
        MOVBU(t0 + cnt, sym)
        ADDS(1, cnt, cnt)
        BEQ(copy_end)
        blank()

        MOVB(sym, dicPos + cnt)
        MOVBU(t0 + cnt, sym)
        ADDS(1, cnt, cnt)
        BNE(copy_byte_loop)
        blank()

        L(copy_end)
        L(lz_end_match)
        MOVB(sym, dicPos + 0)
        ADD(1, dicPos, dicPos)
        blank()

        L(lz_check_limits)
        CheckLimits(fin_OK)
        L(lz_end)
        IF_BIT_1_NOUP(probs_state, pbPos, 0, IsMatch_label)
        blank()

        # ==================== LITERAL MATCHED ====================
        section("LITERAL MATCHED")
        LIT_PROBS()
        blank()

        SUB(dic, dicPos, t0)
        SUBS(rep0, t0, t0)
        BHS(litm_no_wrap)
        ADD(dicBufSize, t0, t0)
        L(litm_no_wrap)
        MOVBU(dic + t0, match)
        blank()

        comment("state -= (state < 10) ? 3 : 6")
        SUBW(6 * PMULT, state, sym)
        CMPW(10 * PMULT, state)
        SUBW(3 * PMULT, state, state)
        CSELW(HS, sym, state, state)
        blank()

        LITM_0()
        for _ in range(6):
            LITM()
        LITM_2()
        blank()

        IsMatchBranch_Pre()
        MOVB(sym, dicPos + 0)
        ADD(1, dicPos, dicPos)
        ANDW(255, sym, sym)
        blank()

        CheckLimits(fin_OK)
        L(lit_matched_end)
        IF_BIT_1_NOUP(probs_state, pbPos, 0, IsMatch_label)
        SUBW(3 * PMULT, state, state)
        B(lit_start_2)
        blank()

        # ==================== REP 0 SHORT ====================
        section("REP 0 SHORT")
        L(IsRep0Short_label)
        UPDATE_0(probs_state, pbPos, 0)
        blank()

        SUB(dic, dicPos, t0)
        ORRW(1 * PMULT, state, state)
        ADDW(1, processedPos, processedPos)
        IsMatchBranch_Pre()
        SUBS(rep0, t0, t0)
        BHS(rep0short_no_wrap)
        ADD(dicBufSize, t0, t0)
        L(rep0short_no_wrap)
        MOVBU(dic + t0, sym)
        B(lz_end_match)
        blank()

        # ==================== REP ====================
        section("REP")
        L(IsRep_label)
        UPDATE_1(probs_state, 0, IsRep - IsMatch)
        blank()

        CMPW(kNumLitStates * PMULT, state)
        MOVW(8 * PMULT, state)
        MOVW(11 * PMULT, probBranch)
        CSELW(HS, probBranch, state, state)
        blank()

        SET_probs(RepLenCoder)
        blank()

        IF_BIT_1(probs_state, 0, IsRepG0 - IsMatch, IsRepG0_label)
        SUB((IsMatch - IsRep0Long) * PMULT, probs_state, probs_state)
        IF_BIT_0_NOUP(probs_state, pbPos, 0, IsRep0Short_label)
        UPDATE_1(probs_state, pbPos, 0)
        B(len_decode)
        blank()

        L(IsRepG0_label)
        UPDATE_1(probs_state, 0, IsRepG0 - IsMatch)
        IF_BIT_1(probs_state, 0, IsRepG1 - IsMatch, IsRepG1_label)
        MOVD(rep1, dist)
        MOVD(rep0, rep1)
        MOVD(dist, rep0)
        B(len_decode)
        blank()

        L(IsRepG1_label)
        UPDATE_1(probs_state, 0, IsRepG1 - IsMatch)
        IF_BIT_1(probs_state, 0, IsRepG2 - IsMatch, IsRepG2_label)
        MOVD(rep2, dist)
        MOVD(rep1, rep2)
        MOVD(rep0, rep1)
        MOVD(dist, rep0)
        B(len_decode)
        blank()

        L(IsRepG2_label)
        UPDATE_1(probs_state, 0, IsRepG2 - IsMatch)
        MOVD(rep3, dist)
        MOVD(rep2, rep3)
        MOVD(rep1, rep2)
        MOVD(rep0, rep1)
        MOVD(dist, rep0)
        B(len_decode)
        blank()

        # ==================== SHORT DISTANCE ====================
        section("SHORT DISTANCE")
        L(short_dist)
        SUBSW(32 + 1, numBits, numBits)
        BLS(decode_dist_end)
        ORRW(2, sym, sym)
        LSLW(numBits, sym, sym)
        ADD(sym.lsl(PSHIFT), probs_Spec, sym)
        ADD(SpecPos * PMULT + 1 * PMULT, sym, sym)
        MOVW(PMULT, sym2)
        L(spec_loop)
        REV_1_VAR(prob_reg)
        SUBSW(1, numBits, numBits)
        BNE(spec_loop)
        blank()

        ADD(probs_Spec, sym2, sym2)
        SUB(sym2, sym, sym)
        LSRW(PSHIFT, sym, sym)
        B(decode_dist_end)
        blank()

        # ==================== COPY MATCH 0 ====================
        # RLE (rep0=1) match copy. Mirrors the reference SDK
        # LzmaDecOpt.S `copy_match_0`: 3 single-byte stores followed by a
        # 4-byte store loop. AND -4 rounds cnt (negative) more negative so
        # the first 4-byte store can overlap (and rewrite with the same RLE
        # byte) the trailing 1-3 bytes from the 3 single stores. That keeps
        # the loop strictly within [dicPos, dicPos+cnt).
        #
        # Do NOT add a wider 16-byte STP loop here: 16-byte alignment of cnt
        # would round it 1-15 bytes more negative than -4 already does, and
        # those bytes are BEFORE dicPos -- not the RLE byte, so overwriting
        # corrupts prior dictionary content (e.g. just-decoded literals).
        section("COPY MATCH 0")
        L(copy_match_0)
        for _ in range(3):
            MOVB(sym, dicPos + cnt)
            ADDS(1, cnt, cnt)
            BEQ(copy_end)
            blank()

        ORRW(sym.lsl(8), sym, t3)
        AND(-4, cnt, cnt)
        ORRW(t3.lsl(16), t3, t3)
        blank()

        L(copy_match_0_small)
        MOVW(t3, dicPos + cnt)
        ADDS(4, cnt, cnt)
        BNE(copy_match_0_small)
        B(copy_end)
        blank()

        # ==================== COPY MATCH CROSS ====================
        section("COPY MATCH CROSS")
        L(copy_match_cross)
        NEG(cnt, cnt)
        blank()

        L(copy_cross_loop)
        MOVBU(dic + t0, sym)
        ADD(1, t0, t0)
        MOVB(sym, dicPos + cnt)
        ADD(1, cnt, cnt)
        CMP(dicBufSize, t0)
        BNE(copy_cross_loop)
        blank()

        MOVBU(dic + 0, sym)
        SUB(cnt, dic, t0)
        B(copy_common)
        blank()

        # ==================== FIN ====================
        section("ERROR / END OF PAYLOAD")
        L(fin_ERROR)
        ADDW(kMatchSpecLen_Error_Data, len_, len_)
        MOVD(rep2, rep3)
        MOVD(rep1, rep2)
        MOVD(rep0, rep1)
        MOVD(sym, rep0)
        STATE_UPDATE_FOR_MATCH()
        MOVW(1, sym)
        B(fin)
        blank()

        L(end_of_payload)
        ADDSW(1, sym, sym)
        BNE(fin_ERROR)
        blank()

        MOVW(kMatchSpecLenStart, len_)
        EORW(1 << FLAG_STATE_BITS, state, state)
        B(fin_OK)
        blank()

        L(fin_OK)
        MOVW(0, sym)
        blank()

        L(fin)
        NORM()
        blank()

        comment("Store results back to struct")
        MOVD(RSP + SPILL_LZMA, t0)
        SUB(dic, dicPos, dicPos)
        LSRW(PSHIFT, state, state)
        blank()

        STP(dicPos, buf, t0 + "cLzmaDec_dicPos")
        MOVW(range_, t0 + "cLzmaDec_rng")
        MOVW(cod, t0 + "cLzmaDec_code")
        MOVW(processedPos, t0 + "cLzmaDec_processedPos")
        MOVW(rep0, t0 + "cLzmaDec_rep0")
        MOVW(rep1, t0 + "cLzmaDec_rep1")
        MOVW(rep2, t0 + "cLzmaDec_rep2")
        MOVW(rep3, t0 + "cLzmaDec_rep3")
        MOVW(state, t0 + "cLzmaDec_state")
        MOVW(len_, t0 + "cLzmaDec_remainLen")
        blank()

        comment("Restore callee-saved registers")
        LDP(RSP + 0, R19, R20)
        LDP(RSP + 16, R21, R22)
        LDP(RSP + 32, R23, R24)
        LDP(RSP + 48, R25, R26)
        MOVD(RSP + 64, R27)
        MOVD(RSP + 72, R29)
        blank()

        ADD(STACK_FRAME, RSP, RSP)
        blank()

        MOVW(sym, FPArg("ret", 24))
        RET()

    term()


if __name__ == "__main__":
    main()
