#!/usr/bin/env python3
"""Generate lzmadec_amd64.s using goasm_amd64 DSL.

Port of LzmaDecOpt.asm (x86-64 MASM) to Go Plan 9 AMD64 assembly.
Original: Igor Pavlov, Public domain.

Usage: python3 gen_lzmadec_amd64.py > lzmadec_amd64.s
"""
from goasm_amd64 import *

# ============================================================
# Constants (matching LzmaDecOpt.asm)
# ============================================================
PSHIFT = 1
PMULT = 1 << PSHIFT        # 2
PMULT_HALF = 1 << (PSHIFT - 1)  # 1
PMULT_2 = 1 << (PSHIFT + 1)     # 4

kNumBitModelTotalBits = 11
kBitModelTotal = 1 << kNumBitModelTotalBits   # 2048
kNumMoveBits = 5
kBitModelOffset = (1 << kNumMoveBits) - 1     # 31
kTopValue = 1 << 24

kMatchSpecLen_Error_Data = 1 << 9  # 512

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

kStartOffset = 1664
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
NUM_BASE_PROBS = Literal + kStartOffset

assert kAlign == 0, f"kAlign must be 0, got {kAlign}"
assert NUM_BASE_PROBS == 1984, f"NUM_BASE_PROBS must be 1984, got {NUM_BASE_PROBS}"

# ============================================================
# Register aliases (MASM -> Plan 9)
# ============================================================
range_     = AX    # x0 = EAX
pbPos      = CX    # x1 = ECX (shift count via CL)
probBranch = DX    # x2 = EDX
cnt        = DX    # alias
cnt_R      = DX    # 64-bit alias for cnt
sym        = BX    # x3 = EBX
sym_R      = BX    # r3 = RBX (64-bit)
cod        = BP    # x5 = EBP
t1         = SI    # x6 = ESI
probs_state = SI   # alias
probs_state_R = SI # 64-bit alias
t0         = DI    # x7 = EDI
prob2      = DI    # alias
state      = R8    # x8 = r8d
state_R    = R8    # 64-bit
match      = R9    # x9
sym2       = R9    # alias
sym2_R     = R9    # 64-bit alias
dist2      = R9    # alias
lpMask_reg = R9    # alias
kBitModelTotal_reg = R10  # constant 2048
probs      = R11   # r11 (64-bit pointer)
dic        = R12   # r12 (64-bit pointer)
offs       = R12   # LITM alias (x12)
offs_R     = R12   # 64-bit
len_temp   = R12   # alias (x12)
processedPos = R13 # x13 = r13d
bit        = R14   # x14 (LITM alias)
bit_R      = R14   # 64-bit
dicPos     = R14   # r14 (64-bit pointer)
buf        = R15   # r15 (64-bit pointer)
prm        = DX    # r2 (LITM lea target)

# ============================================================
# Stack frame layout
# ============================================================
LOC_SAVED_BX     = 0
LOC_SAVED_BP     = 8
LOC_SAVED_R12    = 16
LOC_SAVED_R13    = 24
LOC_SAVED_R14    = 32
LOC_SAVED_R15    = 40
LOC_lzmaPtr      = 48
LOC_dicBufSize   = 56
LOC_probs_Spec   = 64
LOC_dic_Spec     = 72
LOC_limit        = 80
LOC_bufLimit     = 88
LOC_lc2          = 96
LOC_lpMask       = 100
LOC_pbMask       = 104
LOC_checkDicSize = 108
LOC_remainLen    = 112
LOC_pad          = 116
LOC_dicPos_Spec  = 120
LOC_rep0         = 128
LOC_rep1         = 132
LOC_rep2         = 136
LOC_rep3         = 140
LOC_SIZE         = 152  # (152 + 8) % 16 == 0


# Helper: stack-local memory operand
def LOC(offset):
    """Return memory operand for stack-local variable."""
    return SP + offset


# Helper: PLOAD - load 16-bit prob
def PLOAD(dest, mem):
    """Load a 16-bit probability value (zero-extending to 32-bit)."""
    MOVWLZX(mem, dest)


# Helper: PSTORE - store 16-bit prob
def PSTORE(src, mem):
    """Store a 16-bit probability value."""
    MOVW(src, mem)


# ============================================================
# Macro functions
# ============================================================

_norm_counter = 0

def _norm_label():
    global _norm_counter
    _norm_counter += 1
    return Label(f"norm_{_norm_counter}")


def NORM_2():
    """Unconditional byte fetch - CRITICAL: must not use mov cod_L, [buf]
    because Plan 9 MOVB zero-extends. Use MOVBLZX + ORL instead."""
    SHLL(8, cod)
    SHLL(8, range_)
    MOVBLZX(buf + 0, t0)
    ORL(t0, cod)
    INCQ(buf)


def NORM():
    """Conditional normalization."""
    lbl = _norm_label()
    CMPL(range_, kTopValue)
    JCC(lbl)
    NORM_2()
    L(lbl)


def NORM_CALC(prob):
    """NORM + compute range split and cod comparison."""
    NORM()
    MOVL(range_, t0)
    SHRL(kNumBitModelTotalBits, range_)
    IMULL(prob, range_)
    SUBL(range_, t0)
    MOVL(cod, t1)
    SUBL(range_, cod)


def UPDATE_0(probsArray, probOffset, probDisp):
    """Update prob after bit=0 branch taken."""
    MOVL(kBitModelTotal_reg, prob2)
    SUBL(probBranch, prob2)
    SHRL(kNumMoveBits, prob2)
    ADDL(prob2, probBranch)
    PSTORE(probBranch, probsArray + probOffset + probDisp * PMULT)


def UPDATE_1(probsArray, probOffset, probDisp):
    """Update prob after bit=1 branch taken."""
    SUBL(range_, prob2)
    SUBL(range_, cod)
    MOVL(prob2, range_)
    MOVL(probBranch, prob2)
    SHRL(kNumMoveBits, probBranch)
    SUBL(probBranch, prob2)
    PSTORE(prob2, probsArray + probOffset + probDisp * PMULT)


def CMP_COD(probsArray, probOffset, probDisp):
    """Load prob, NORM, compute range*prob, compare with cod."""
    PLOAD(probBranch, probsArray + probOffset + probDisp * PMULT)
    NORM()
    MOVL(range_, prob2)
    SHRL(kNumBitModelTotalBits, range_)
    IMULL(probBranch, range_)
    CMPL(cod, range_)


def IF_BIT_1_NOUP(probsArray, probOffset, probDisp, toLabel):
    CMP_COD(probsArray, probOffset, probDisp)
    JCC(toLabel)


def IF_BIT_1(probsArray, probOffset, probDisp, toLabel):
    IF_BIT_1_NOUP(probsArray, probOffset, probDisp, toLabel)
    UPDATE_0(probsArray, probOffset, probDisp)


def IF_BIT_0_NOUP(probsArray, probOffset, probDisp, toLabel):
    CMP_COD(probsArray, probOffset, probDisp)
    JCS(toLabel)


def PUP(prob, probPtr):
    """prob update: t0 = prob + (kBitModelTotal/kBitModelOffset - prob) >> shift"""
    SUBL(prob, t0)
    SARL(kNumMoveBits, t0)
    ADDL(prob, t0)
    PSTORE(t0, probPtr)


def PUP_SUB(prob, probPtr, symSub):
    SBBL(symSub, sym)
    PUP(prob, probPtr)


def PUP_COD(prob, probPtr, symSub):
    MOVL(kBitModelOffset, t0)
    CMOVLCS(t1, cod)
    MOVL(sym, t1)
    CMOVLCS(kBitModelTotal_reg, t0)
    PUP_SUB(prob, probPtr, symSub)


def BIT_0(prob, probNext):
    """First bit decode of unrolled tree. prob=CX, probNext=DX or vice versa."""
    PLOAD(prob, probs + 1 * PMULT)
    PLOAD(probNext, probs + 1 * PMULT_2)
    blank()
    NORM_CALC(prob)
    blank()
    CMOVLCC(t0, range_)
    PLOAD(t0, probs + 1 * PMULT_2 + PMULT)
    CMOVLCC(t0, probNext)
    MOVL(kBitModelOffset, t0)
    CMOVLCS(t1, cod)
    CMOVLCS(kBitModelTotal_reg, t0)
    MOVL(2, sym)
    PUP_SUB(prob, probs + 1 * PMULT, Imm(0 - 1))


def BIT_1(prob, probNext):
    """Middle bit decode. Reads probNext from probs[sym*2], updates old prob."""
    PLOAD(probNext, probs + sym_R * PMULT_2)
    ADDL(sym, sym)
    blank()
    NORM_CALC(prob)
    blank()
    CMOVLCC(t0, range_)
    PLOAD(t0, probs + sym_R * PMULT + PMULT)
    CMOVLCC(t0, probNext)
    PUP_COD(prob, probs + t1 * PMULT_HALF, Imm(0 - 1))


def BIT_2(prob, symSub):
    """Last bit decode."""
    ADDL(sym, sym)
    blank()
    NORM_CALC(prob)
    blank()
    CMOVLCC(t0, range_)
    PUP_COD(prob, probs + t1 * PMULT_HALF, symSub)


# ---------- MATCHED LITERAL ----------

def LITM_0():
    MOVL(256 * PMULT, offs)
    SHLL(PSHIFT + 1, match)
    MOVL(offs, bit)
    ANDL(match, bit)
    PLOAD(pbPos, probs + 256 * PMULT + bit_R * 1 + 1 * PMULT)
    LEAQ(probs + 256 * PMULT + bit_R * 1 + 1 * PMULT, prm)
    XORL(bit, offs)
    ADDL(match, match)
    blank()
    NORM_CALC(pbPos)
    blank()
    CMOVLCC(bit, offs)
    MOVL(match, bit)
    CMOVLCC(t0, range_)
    MOVL(kBitModelOffset, t0)
    CMOVLCS(t1, cod)
    CMOVLCS(kBitModelTotal_reg, t0)
    MOVL(0, sym)
    PUP_SUB(pbPos, prm + 0, Imm(-2 - 1))


def LITM():
    ANDL(offs, bit)
    LEAQ(probs + offs_R * 1, prm)
    ADDQ(bit_R, prm)
    PLOAD(pbPos, prm + sym_R * PMULT)
    XORL(bit, offs)
    ADDL(sym, sym)
    ADDL(match, match)
    blank()
    NORM_CALC(pbPos)
    blank()
    CMOVLCC(bit, offs)
    MOVL(match, bit)
    CMOVLCC(t0, range_)
    PUP_COD(pbPos, prm + t1 * PMULT_HALF, Imm(-1))


def LITM_2():
    ANDL(offs, bit)
    LEAQ(probs + offs_R * 1, prm)
    ADDQ(bit_R, prm)
    PLOAD(pbPos, prm + sym_R * PMULT)
    ADDL(sym, sym)
    blank()
    NORM_CALC(pbPos)
    blank()
    CMOVLCC(t0, range_)
    PUP_COD(pbPos, prm + t1 * PMULT_HALF, Imm(256 - 1))


# ---------- REVERSE BITS ----------

def REV_0(prob, probNext):
    """First alignment bit decode."""
    PLOAD(probNext, sym2_R + 0)
    blank()
    NORM_CALC(prob)
    blank()
    CMOVLCC(t0, range_)
    PLOAD(t0, probs + 3 * PMULT)
    CMOVLCC(t0, probNext)
    CMOVLCS(t1, cod)
    MOVL(kBitModelOffset, t0)
    CMOVLCS(kBitModelTotal_reg, t0)
    LEAQ(probs + 3 * PMULT, t1)
    CMOVQCC(t1, sym2_R)
    PUP(prob, probs + 1 * PMULT)


def REV_1(prob, probNext, step):
    """Middle alignment bit decode."""
    ADDQ(step * PMULT, sym2_R)
    PLOAD(probNext, sym2_R + 0)
    blank()
    NORM_CALC(prob)
    blank()
    CMOVLCC(t0, range_)
    PLOAD(t0, sym2_R + step * PMULT)
    CMOVLCC(t0, probNext)
    CMOVLCS(t1, cod)
    MOVL(kBitModelOffset, t0)
    CMOVLCS(kBitModelTotal_reg, t0)
    LEAQ(sym2_R + step * PMULT, t1)
    CMOVQCC(t1, sym2_R)
    PUP(prob, t1 + (-step * PMULT_2))


def REV_2(prob, step):
    """Last alignment bit decode."""
    SUBQ(probs, sym2_R)
    SHRL(PSHIFT, sym2)
    ORL(sym2, sym)
    blank()
    NORM_CALC(prob)
    blank()
    CMOVLCC(t0, range_)
    LEAL(sym + (-step), t0)
    CMOVLCS(t0, sym)
    CMOVLCS(t1, cod)
    MOVL(kBitModelOffset, t0)
    CMOVLCS(kBitModelTotal_reg, t0)
    PUP(prob, probs + sym2_R * PMULT)


def REV_1_VAR(prob):
    """Variable reverse bit decode for short distances."""
    PLOAD(prob, sym_R + 0)
    MOVQ(sym_R, probs)
    ADDQ(sym2_R, sym_R)
    blank()
    NORM_CALC(prob)
    blank()
    CMOVLCC(t0, range_)
    LEAQ(sym_R + sym2_R * 1, t0)
    CMOVQCC(t0, sym_R)
    MOVL(kBitModelOffset, t0)
    CMOVLCS(t1, cod)
    CMOVLCS(kBitModelTotal_reg, t0)
    ADDL(sym2, sym2)
    PUP(prob, probs + 0)


def LIT_PROBS(lpMaskParam):
    """Compute literal probs pointer.
    prob += 3 * ((((processedPos << 8) + prevByte) & lpMask) << lc)"""
    MOVL(processedPos, t0)
    SHLL(8, t0)
    ADDL(t0, sym)
    ANDL(lpMaskParam, sym)
    ADDQ(pbPos, probs_state_R)
    MOVL(LOC(LOC_lc2), pbPos)
    # lea sym, [sym_R + 2*sym_R]  =>  sym = sym * 3
    LEAL(sym_R + sym_R * 2, sym)
    ADDQ(Literal * PMULT, probs)
    SHLL(CX, sym)   # CL holds lc2
    ADDQ(sym_R, probs)
    UPDATE_0(probs_state_R, 0, IsMatch)
    INCL(processedPos)


def IsMatchBranch_Pre():
    """Prepare IsMatch branch: compute pbPos and probs_state."""
    MOVL(LOC(LOC_pbMask), pbPos)
    ANDL(processedPos, pbPos)
    SHLL(kLenNumLowBits + 1 + PSHIFT, pbPos)
    LEAQ(probs + state_R * 1, probs_state_R)


def CheckLimits(fin_OK):
    """Check buf and dicPos limits."""
    CMPQ(buf, LOC(LOC_bufLimit))
    JCC(fin_OK)
    CMPQ(dicPos, LOC(LOC_limit))
    JCC(fin_OK)


# ============================================================
# Main generation
# ============================================================

def main():
    init("go_asm.h")

    comment("LzmaDecOpt_amd64.s -- Go AMD64 assembly version of LzmaDec_DecodeReal_3()")
    comment("Generated by gen_lzmadec_amd64.py from LzmaDecOpt.asm")
    comment("Original: Igor Pavlov, Public domain")
    comment("Configuration: PSHIFT=1 (16-bit probs), unrolled, kStartOffset=1664")
    blank()

    # Labels
    lit_start       = Label("lit_start")
    lit_start_2     = Label("lit_start_2")
    lit_end         = Label("lit_end")
    lit_matched_end = Label("lit_matched_end")
    lz_end          = Label("lz_end")
    lz_end_match    = Label("lz_end_match")
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
    copy_common     = Label("copy_common")
    copy_loop       = Label("copy_loop")
    copy_match_cross = Label("copy_match_cross")
    copy_cross_loop = Label("copy_cross_loop")
    copy_no_wrap_byte = Label("copy_no_wrap_byte")
    copy_wide_loop  = Label("copy_wide_loop")
    copy_wide_tail  = Label("copy_wide_tail")
    copy_wide_done  = Label("copy_wide_done")
    copy_match_0    = Label("copy_match_0")
    copy_match_0_wide = Label("copy_match_0_wide")
    copy_match_0_small = Label("copy_match_0_small")
    copy_word_align = Label("copy_word_align")
    copy_word_loop  = Label("copy_word_loop")
    short_dist      = Label("short_dist")
    spec_loop       = Label("spec_loop")
    direct_loop     = Label("direct_loop")
    direct_norm     = Label("direct_norm")
    direct_end      = Label("direct_end")
    decode_dist_end = Label("decode_dist_end")
    end_of_payload  = Label("end_of_payload")
    fin             = Label("fin")
    fin_OK          = Label("fin_OK")
    fin_ERROR       = Label("fin_ERROR_MATCH_DIST")
    fin_dicPos_LIMIT = Label("fin_dicPos_LIMIT")
    init_skip_prev  = Label("init_skip_prev")
    copy_fast_nowr  = Label("copy_fast_nowr")

    section("Function entry")

    # Go ABI0: args on stack at FP offsets
    # func lzmaDecodeReal3(lzma *cLzmaDec, limit uintptr, bufLimit unsafe.Pointer) int32
    # lzma+0(FP), limit+8(FP), bufLimit+16(FP), ret+24(FP)
    with Func("lzmaDecodeReal3", nosplit=True, noframe=True, frame=0, args=28):

        comment("Save callee-saved registers to our stack frame")
        comment("Go ABI0: BX, BP, R12-R15 are callee-saved")
        comment("We first load args, then save regs & allocate stack")
        blank()

        comment("Load arguments from FP before touching SP")
        MOVQ(FPArg("lzma", 0), sym_R)       # sym_R = RBX = lzma ptr (temp)
        MOVQ(FPArg("limit", 8), t1)         # t1 = RSI = limit
        MOVQ(FPArg("bufLimit", 16), t0)     # t0 = RDI = bufLimit
        blank()

        comment("Allocate stack frame")
        SUBQ(LOC_SIZE, SP)
        blank()

        comment("Save callee-saved registers")
        MOVQ(BX, LOC(LOC_SAVED_BX))
        MOVQ(BP, LOC(LOC_SAVED_BP))
        MOVQ(R12, LOC(LOC_SAVED_R12))
        MOVQ(R13, LOC(LOC_SAVED_R13))
        MOVQ(R14, LOC(LOC_SAVED_R14))
        MOVQ(R15, LOC(LOC_SAVED_R15))
        blank()

        comment("Store lzma pointer and bufLimit")
        MOVQ(sym_R, LOC(LOC_lzmaPtr))       # save lzma pointer
        MOVQ(t0, LOC(LOC_bufLimit))          # save bufLimit
        blank()

        MOVL(0, LOC(LOC_remainLen))          # remainLen must be ZERO
        blank()

        comment("Load struct fields from cLzmaDec")
        # sym_R (RBX) still holds lzma ptr
        # Load dic
        MOVQ(sym_R + "cLzmaDec_dic", dic)
        # limit = limit + dic
        ADDQ(dic, t1)
        MOVQ(t1, LOC(LOC_limit))
        blank()

        # Copy rep0-rep3 to stack
        MOVL(sym_R + "cLzmaDec_rep0", t0)
        MOVL(t0, LOC(LOC_rep0))
        MOVL(sym_R + "cLzmaDec_rep1", t0)
        MOVL(t0, LOC(LOC_rep1))
        MOVL(sym_R + "cLzmaDec_rep2", t0)
        MOVL(t0, LOC(LOC_rep2))
        MOVL(sym_R + "cLzmaDec_rep3", t0)
        MOVL(t0, LOC(LOC_rep3))
        blank()

        # dicPos = dicPos_Spec + dic
        MOVQ(sym_R + "cLzmaDec_dicPos", dicPos)
        ADDQ(dic, dicPos)
        MOVQ(dicPos, LOC(LOC_dicPos_Spec))
        MOVQ(dic, LOC(LOC_dic_Spec))
        blank()

        # pbMask = (1 << pb) - 1
        MOVBLZX(sym_R + "cLzmaDec_pb", pbPos)
        MOVL(1, t0)
        SHLL(CX, t0)       # CL = pbPos = pb
        DECL(t0)
        MOVL(t0, LOC(LOC_pbMask))
        blank()

        # lc2 = lc + PSHIFT; lpMask = (0x100 << lp) - (0x100 >> lc)
        MOVBLZX(sym_R + "cLzmaDec_lc", pbPos)    # x1 = lc
        MOVL(0x100, probBranch)                    # x2 = 256
        MOVL(probBranch, t0)                       # t0 = 256
        SHRL(CX, probBranch)                       # x2 = 256 >> lc
        ADDL(PSHIFT, pbPos)                        # x1 = lc + PSHIFT
        MOVL(pbPos, LOC(LOC_lc2))
        MOVBLZX(sym_R + "cLzmaDec_lp", pbPos)     # x1 = lp
        SHLL(CX, t0)                              # t0 = 256 << lp
        SUBL(probBranch, t0)                       # t0 = lpMask
        MOVL(t0, LOC(LOC_lpMask))
        MOVL(t0, lpMask_reg)
        blank()

        # probs = probs_1664
        MOVQ(sym_R + "cLzmaDec_probs1664", probs)
        MOVQ(probs, LOC(LOC_probs_Spec))
        blank()

        # dicBufSize
        MOVQ(sym_R + "cLzmaDec_dicBufSize", t0)
        MOVQ(t0, LOC(LOC_dicBufSize))
        blank()

        # checkDicSize
        MOVL(sym_R + "cLzmaDec_checkDicSize", pbPos)
        MOVL(pbPos, LOC(LOC_checkDicSize))
        blank()

        # processedPos, state, buf, range, cod
        MOVL(sym_R + "cLzmaDec_processedPos", processedPos)
        MOVL(sym_R + "cLzmaDec_state", state)
        SHLL(PSHIFT, state)
        MOVQ(sym_R + "cLzmaDec_buf", buf)
        MOVL(sym_R + "cLzmaDec_rng", range_)
        MOVL(sym_R + "cLzmaDec_code", cod)
        MOVL(kBitModelTotal, kBitModelTotal_reg)
        XORL(sym, sym)
        blank()

        comment("if (processedPos != 0 || checkDicSize != 0)")
        ORL(processedPos, pbPos)
        JEQ(init_skip_prev)
        # t0_R still has dicBufSize? No, reload.
        MOVQ(LOC(LOC_dicBufSize), t0)
        ADDQ(dic, t0)
        CMPQ(dicPos, dic)
        CMOVQNE(dicPos, t0)
        MOVBLZX(t0 + (-1), sym)
        L(init_skip_prev)
        blank()

        IsMatchBranch_Pre()
        CMPL(4 * PMULT, state)
        JCS(lit_end)
        CMPL(kNumLitStates * PMULT, state)
        JCS(lit_matched_end)
        JMP(lz_end)
        blank()

        # ==================== LITERAL ====================
        section("LITERAL")
        L(lit_start)
        XORL(state, state)
        L(lit_start_2)
        LIT_PROBS(lpMask_reg)
        blank()

        comment("Unrolled 8-bit literal tree decode")
        BIT_0(pbPos, probBranch)
        BIT_1(probBranch, pbPos)
        BIT_1(pbPos, probBranch)
        BIT_1(probBranch, pbPos)
        BIT_1(pbPos, probBranch)
        BIT_1(probBranch, pbPos)
        BIT_1(pbPos, probBranch)
        blank()
        BIT_2(probBranch, Imm(256 - 1))
        blank()

        MOVQ(LOC(LOC_probs_Spec), probs)
        IsMatchBranch_Pre()
        MOVB(sym, dicPos + 0)
        INCQ(dicPos)
        blank()
        CheckLimits(fin_OK)
        L(lit_end)
        IF_BIT_0_NOUP(probs_state_R, pbPos, IsMatch, lit_start)
        blank()

        # ==================== MATCHES ====================
        section("MATCHES")
        L(IsMatch_label)
        UPDATE_1(probs_state_R, pbPos, IsMatch)
        IF_BIT_1(probs_state_R, 0, IsRep, IsRep_label)
        blank()
        ADDQ(LenCoder * PMULT, probs)
        ADDL(kNumStates * PMULT, state)
        blank()

        # ==================== LEN DECODE ====================
        section("LEN DECODE")
        L(len_decode)
        MOVL(8 - 1 - kMatchMinLen, len_temp)
        IF_BIT_0_NOUP(probs, 0, 0, len_mid_0)
        UPDATE_1(probs, 0, 0)
        ADDQ(1 << (kLenNumLowBits + PSHIFT), probs)
        MOVL(-1 - kMatchMinLen, len_temp)
        IF_BIT_0_NOUP(probs, 0, 0, len_mid_0)
        UPDATE_1(probs, 0, 0)
        ADDQ(LenHigh * PMULT - (1 << (kLenNumLowBits + PSHIFT)), probs)
        MOVL(1, sym)
        PLOAD(pbPos, probs + 1 * PMULT)
        blank()

        L(len8_loop)
        BIT_1(pbPos, probBranch)
        MOVL(probBranch, pbPos)
        CMPL(64, sym)
        JCS(len8_loop)
        blank()

        MOVL((kLenNumHighSymbols - kLenNumLowSymbols * 2) - 1 - kMatchMinLen, len_temp)
        JMP(len_mid_2)
        blank()

        L(len_mid_0)
        UPDATE_0(probs, 0, 0)
        ADDQ(pbPos, probs)
        BIT_0(probBranch, pbPos)
        L(len_mid_2)
        BIT_1(pbPos, probBranch)
        BIT_2(probBranch, len_temp)
        MOVQ(LOC(LOC_probs_Spec), probs)
        CMPL(kNumStates * PMULT, state)
        JCS(copy_match)
        blank()

        # ==================== DECODE DISTANCE ====================
        section("DECODE DISTANCE")
        comment("PosSlot tree decode")
        MOVL(3 + kMatchMinLen, t0)
        CMPL(3 + kMatchMinLen, sym)
        CMOVLCS(sym, t0)
        ADDQ(PosSlot * PMULT - (kMatchMinLen << (kNumPosSlotBits + PSHIFT)), probs)
        SHLL(kNumPosSlotBits + PSHIFT, t0)
        ADDQ(t0, probs)
        blank()

        MOVL(sym, len_temp)
        blank()

        comment("Unrolled 6-bit PosSlot tree")
        BIT_0(pbPos, probBranch)
        BIT_1(probBranch, pbPos)
        BIT_1(pbPos, probBranch)
        BIT_1(probBranch, pbPos)
        BIT_1(pbPos, probBranch)
        blank()

        MOVL(sym, pbPos)
        BIT_2(probBranch, Imm(64 - 1))
        blank()

        ANDL(3, sym)
        MOVQ(LOC(LOC_probs_Spec), probs)
        CMPL(32 + kEndPosModelIndex // 2, pbPos)
        JCS(short_dist)
        blank()

        comment("Long distance: direct bits + alignment")
        SUBL(32 + 1 + kNumAlignBits, pbPos)
        ORL(2, sym)
        PLOAD(probBranch, probs + 1 * PMULT)
        SHLL(kNumAlignBits + 1, sym)
        LEAQ(probs + 2 * PMULT, sym2_R)
        blank()
        JMP(direct_norm)
        blank()

        # ==================== DIRECT DISTANCE ====================
        section("DIRECT DISTANCE")
        L(direct_loop)
        SHRL(1, range_)
        MOVL(cod, t0)
        SUBL(range_, cod)
        CMOVLMI(t0, cod)
        CMOVLPL(t1, sym)
        blank()
        DECL(pbPos)
        JEQ(direct_end)
        blank()
        ADDL(sym, sym)
        L(direct_norm)
        LEAL(sym_R + (1 << kNumAlignBits), t1)
        CMPL(kTopValue, range_)
        JCC(direct_loop)
        NORM_2()
        JMP(direct_loop)
        blank()

        L(direct_end)
        comment("Alignment bit decode: REV_0, REV_1, REV_1, REV_2")
        REV_0(probBranch, pbPos)
        REV_1(pbPos, probBranch, 2)
        REV_1(probBranch, pbPos, 4)
        REV_2(pbPos, 8)
        blank()

        L(decode_dist_end)
        comment("Check distance validity")
        MOVL(LOC(LOC_rep0), t1)
        MOVL(LOC(LOC_rep1), pbPos)
        MOVL(LOC(LOC_rep2), probBranch)
        blank()
        MOVL(LOC(LOC_checkDicSize), t0)
        TESTL(t0, t0)
        CMOVLEQ(processedPos, t0)
        CMPL(sym, t0)
        JCC(end_of_payload)
        blank()

        comment("rep3=rep2; rep2=rep1; rep1=rep0; rep0=distance+1")
        INCL(sym)
        MOVL(sym, LOC(LOC_rep0))
        MOVL(len_temp, sym)
        MOVL(t1, LOC(LOC_rep1))
        MOVL(pbPos, LOC(LOC_rep2))
        MOVL(probBranch, LOC(LOC_rep3))
        blank()

        comment("state = (state < (kNumStates+kNumLitStates)*PMULT) ? kNumLitStates*PMULT : (kNumLitStates+3)*PMULT")
        CMPL((kNumStates + kNumLitStates) * PMULT, state)
        MOVL(kNumLitStates * PMULT, state)
        MOVL((kNumLitStates + 3) * PMULT, t0)
        CMOVLCC(t0, state)
        blank()

        # ==================== COPY MATCH ====================
        section("COPY MATCH")
        L(copy_match)
        MOVQ(LOC(LOC_limit), cnt_R)
        SUBQ(dicPos, cnt_R)
        JEQ(fin_dicPos_LIMIT)
        blank()

        # curLen = min(rem, len)
        CMPQ(cnt_R, sym_R)       # cnt_R - sym_R
        CMOVLCC(sym, cnt)       # if cnt_R >= sym_R: cnt = sym
        blank()

        MOVQ(LOC(LOC_dic_Spec), dic)
        MOVL(LOC(LOC_rep0), pbPos)
        blank()

        MOVQ(dicPos, t0)
        ADDQ(cnt_R, dicPos)
        ADDL(cnt, processedPos)
        SUBL(cnt, sym)
        MOVL(sym, LOC(LOC_remainLen))
        blank()

        SUBQ(dic, t0)
        blank()

        comment("pos = dicPos - rep0 + (dicPos < rep0 ? dicBufSize : 0)")
        SUBQ(pbPos, t0)
        JCC(copy_fast_nowr)
        blank()

        MOVQ(LOC(LOC_dicBufSize), pbPos)
        ADDQ(pbPos, t0)
        SUBQ(t0, pbPos)
        CMPQ(cnt_R, pbPos)
        JHI(copy_match_cross)
        L(copy_fast_nowr)
        blank()

        comment("Fast copy path")
        ADDQ(dic, t0)
        blank()

        comment("Wide copy path: non-overlapping (rep0 >= curLen) and curLen >= 16")
        CMPL(cnt, LOC(LOC_rep0))
        JHI(copy_no_wrap_byte)
        CMPL(cnt, 16)
        JCS(copy_no_wrap_byte)
        blank()

        comment("16-byte MOVOU copy loop")
        SUBQ(cnt_R, dicPos)     # match = dicPos - cnt = dest start
        MOVQ(cnt_R, sym_R)
        ANDQ(-16, sym_R)        # sym_R = cnt rounded down to 16
        L(copy_wide_loop)
        MOVOU(t0 + 0, X0)
        MOVOU(X0, dicPos + 0)
        ADDQ(16, t0)
        ADDQ(16, dicPos)
        SUBQ(16, sym_R)
        JNE(copy_wide_loop)
        ANDL(15, cnt)
        JEQ(copy_wide_done)
        L(copy_wide_tail)
        MOVBLZX(t0 + 0, sym)
        MOVB(sym, dicPos + 0)
        INCQ(t0)
        INCQ(dicPos)
        DECL(cnt)
        JNE(copy_wide_tail)
        L(copy_wide_done)
        MOVBLZX(dicPos - 1, sym)
        IsMatchBranch_Pre()
        JMP(Label("lz_check_limits"))
        blank()

        L(copy_no_wrap_byte)
        MOVBLZX(t0 + 0, sym)
        ADDQ(cnt_R, t0)
        NEGQ(cnt_R)
        L(copy_common)
        DECQ(dicPos)
        blank()

        IsMatchBranch_Pre()
        INCQ(cnt_R)
        JEQ(copy_end)
        L(copy_loop)
        MOVB(sym, dicPos + cnt_R * 1)
        MOVBLZX(t0 + cnt_R * 1, sym)
        INCQ(cnt_R)
        JEQ(copy_end)
        blank()

        MOVB(sym, dicPos + cnt_R * 1)
        MOVBLZX(t0 + cnt_R * 1, sym)
        INCQ(cnt_R)
        JNE(copy_loop)
        blank()

        L(copy_end)
        L(lz_end_match)
        MOVB(sym, dicPos + 0)
        INCQ(dicPos)
        blank()

        L(Label("lz_check_limits"))
        CheckLimits(fin_OK)
        L(lz_end)
        IF_BIT_1_NOUP(probs_state_R, pbPos, IsMatch, IsMatch_label)
        blank()

        # ==================== LITERAL MATCHED ====================
        section("LITERAL MATCHED")
        LIT_PROBS(LOC(LOC_lpMask))
        blank()

        comment("matchByte = dic[dicPos - rep0 + (dicPos < rep0 ? dicBufSize : 0)]")
        MOVL(LOC(LOC_rep0), pbPos)
        MOVQ(dicPos, LOC(LOC_dicPos_Spec))
        blank()

        comment("state -= (state < 10) ? 3 : 6")
        LEAL(state_R + (-6 * PMULT), t0)
        SUBL(3 * PMULT, state)
        CMPL(7 * PMULT, state)
        CMOVLCC(t0, state)
        blank()

        SUBQ(dic, dicPos)
        SUBQ(pbPos, dicPos)
        JCC(Label("litm_no_wrap"))
        ADDQ(LOC(LOC_dicBufSize), dicPos)
        L(Label("litm_no_wrap"))
        blank()

        MOVBLZX(dic + dicPos * 1, match)
        blank()

        comment("Unrolled 8-bit matched literal decode")
        LITM_0()
        blank()
        LITM()
        LITM()
        LITM()
        LITM()
        LITM()
        LITM()
        LITM_2()
        blank()

        MOVQ(LOC(LOC_probs_Spec), probs)
        IsMatchBranch_Pre()
        MOVQ(LOC(LOC_dicPos_Spec), dicPos)
        MOVB(sym, dicPos + 0)
        INCQ(dicPos)
        blank()

        CheckLimits(fin_OK)
        L(lit_matched_end)
        IF_BIT_1_NOUP(probs_state_R, pbPos, IsMatch, IsMatch_label)
        MOVL(LOC(LOC_lpMask), lpMask_reg)
        SUBL(3 * PMULT, state)
        JMP(lit_start_2)
        blank()

        # ==================== REP 0 SHORT ====================
        section("REP 0 SHORT")
        L(IsRep0Short_label)
        UPDATE_0(probs_state_R, pbPos, IsRep0Long)
        blank()

        MOVQ(LOC(LOC_dic_Spec), dic)
        MOVQ(dicPos, t0)
        MOVL(LOC(LOC_rep0), probBranch)
        SUBQ(dic, t0)
        blank()

        SUBQ(RepLenCoder * PMULT, probs)
        blank()

        ORL(1 * PMULT, state)
        blank()

        INCL(processedPos)
        IsMatchBranch_Pre()
        blank()

        SUBQ(probBranch, t0)
        JCC(Label("rep0short_no_wrap"))
        ADDQ(LOC(LOC_dicBufSize), t0)
        L(Label("rep0short_no_wrap"))
        MOVBLZX(dic + t0 * 1, sym)
        JMP(lz_end_match)
        blank()

        # ==================== REP ====================
        section("REP")
        L(IsRep_label)
        UPDATE_1(probs_state_R, 0, IsRep)
        blank()

        CMPL(kNumLitStates * PMULT, state)
        MOVL(8 * PMULT, state)
        MOVL(11 * PMULT, probBranch)
        CMOVLCC(probBranch, state)
        blank()

        ADDQ(RepLenCoder * PMULT, probs)
        blank()

        IF_BIT_1(probs_state_R, 0, IsRepG0, IsRepG0_label)
        IF_BIT_0_NOUP(probs_state_R, pbPos, IsRep0Long, IsRep0Short_label)
        UPDATE_1(probs_state_R, pbPos, IsRep0Long)
        JMP(len_decode)
        blank()

        L(IsRepG0_label)
        UPDATE_1(probs_state_R, 0, IsRepG0)
        MOVL(LOC(LOC_rep0), dist2)
        MOVL(LOC(LOC_rep1), sym)
        MOVL(dist2, LOC(LOC_rep1))
        blank()

        IF_BIT_1(probs_state_R, 0, IsRepG1, IsRepG1_label)
        MOVL(sym, LOC(LOC_rep0))
        JMP(len_decode)
        blank()

        L(IsRepG1_label)
        UPDATE_1(probs_state_R, 0, IsRepG1)
        MOVL(LOC(LOC_rep2), dist2)
        MOVL(sym, LOC(LOC_rep2))
        blank()

        IF_BIT_1(probs_state_R, 0, IsRepG2, IsRepG2_label)
        MOVL(dist2, LOC(LOC_rep0))
        JMP(len_decode)
        blank()

        L(IsRepG2_label)
        UPDATE_1(probs_state_R, 0, IsRepG2)
        MOVL(LOC(LOC_rep3), sym)
        MOVL(dist2, LOC(LOC_rep3))
        MOVL(sym, LOC(LOC_rep0))
        JMP(len_decode)
        blank()

        # ==================== SHORT DISTANCE ====================
        section("SHORT DISTANCE")
        L(short_dist)
        SUBL(32 + 1, pbPos)
        JLS(decode_dist_end)
        ORL(2, sym)
        SHLL(CX, sym)       # CL = x1 = numBits
        LEAQ(probs + sym_R * PMULT + SpecPos * PMULT + 1 * PMULT, sym_R)
        MOVL(PMULT, sym2)
        L(spec_loop)
        REV_1_VAR(probBranch)
        DECL(pbPos)
        JNE(spec_loop)
        blank()

        MOVQ(LOC(LOC_probs_Spec), probs)
        SUBL(sym2, sym)
        SUBL(SpecPos * PMULT, sym)
        SUBQ(probs, sym_R)
        SHRL(PSHIFT, sym)
        blank()
        JMP(decode_dist_end)
        blank()

        # ==================== COPY MATCH CROSS ====================
        section("COPY MATCH CROSS")
        L(copy_match_cross)
        comment("t0 = srcPos, pbPos(r1) = remaining to dicBufSize end, cnt_R = total len")
        MOVQ(t0, t1)          # t1 = srcPos
        MOVQ(dic, t0)         # t0 = dic
        MOVQ(LOC(LOC_dicBufSize), pbPos)
        NEGQ(cnt_R)
        L(copy_cross_loop)
        MOVBLZX(t0 + t1 * 1, sym)
        INCQ(t1)
        MOVB(sym, dicPos + cnt_R * 1)
        INCQ(cnt_R)
        CMPQ(t1, pbPos)
        JNE(copy_cross_loop)
        blank()

        MOVBLZX(t0 + 0, sym)
        SUBQ(cnt_R, t0)
        JMP(copy_common)
        blank()

        # ==================== FIN ====================
        section("FIN")

        L(fin_dicPos_LIMIT)
        MOVL(sym, LOC(LOC_remainLen))
        JMP(fin_OK)
        blank()

        L(fin_ERROR)
        comment("fin_ERROR_MATCH_DIST")
        ADDL(kMatchSpecLen_Error_Data, len_temp)
        MOVL(len_temp, LOC(LOC_remainLen))
        blank()
        MOVL(sym, LOC(LOC_rep0))
        MOVL(t1, LOC(LOC_rep1))
        MOVL(pbPos, LOC(LOC_rep2))
        MOVL(probBranch, LOC(LOC_rep3))
        blank()

        CMPL((kNumStates + kNumLitStates) * PMULT, state)
        MOVL(kNumLitStates * PMULT, state)
        MOVL((kNumLitStates + 3) * PMULT, t0)
        CMOVLCC(t0, state)
        blank()

        MOVL(1, sym)
        JMP(fin)
        blank()

        L(end_of_payload)
        INCL(sym)
        JNE(fin_ERROR)
        blank()

        MOVL(kMatchSpecLenStart, LOC(LOC_remainLen))
        SUBL(kNumStates * PMULT, state)
        blank()

        L(fin_OK)
        XORL(sym, sym)
        blank()

        L(fin)
        NORM()
        blank()

        comment("Store results back to struct")
        MOVQ(LOC(LOC_lzmaPtr), pbPos)   # r1 = lzma pointer
        blank()

        SUBQ(LOC(LOC_dic_Spec), dicPos)
        MOVQ(dicPos, pbPos + "cLzmaDec_dicPos")
        MOVQ(buf, pbPos + "cLzmaDec_buf")
        MOVL(range_, pbPos + "cLzmaDec_rng")
        MOVL(cod, pbPos + "cLzmaDec_code")
        SHRL(PSHIFT, state)
        MOVL(state, pbPos + "cLzmaDec_state")
        MOVL(processedPos, pbPos + "cLzmaDec_processedPos")
        blank()

        # RESTORE_VARs: remainLen, rep0-3
        MOVL(LOC(LOC_remainLen), t0)
        MOVL(t0, pbPos + "cLzmaDec_remainLen")
        MOVL(LOC(LOC_rep0), t0)
        MOVL(t0, pbPos + "cLzmaDec_rep0")
        MOVL(LOC(LOC_rep1), t0)
        MOVL(t0, pbPos + "cLzmaDec_rep1")
        MOVL(LOC(LOC_rep2), t0)
        MOVL(t0, pbPos + "cLzmaDec_rep2")
        MOVL(LOC(LOC_rep3), t0)
        MOVL(t0, pbPos + "cLzmaDec_rep3")
        blank()

        comment("Return value")
        MOVL(sym, t0)    # sym holds return (0=ok, 1=error)
        blank()

        comment("Restore callee-saved registers")
        MOVQ(LOC(LOC_SAVED_BX), BX)
        MOVQ(LOC(LOC_SAVED_BP), BP)
        MOVQ(LOC(LOC_SAVED_R12), R12)
        MOVQ(LOC(LOC_SAVED_R13), R13)
        MOVQ(LOC(LOC_SAVED_R14), R14)
        MOVQ(LOC(LOC_SAVED_R15), R15)
        blank()

        ADDQ(LOC_SIZE, SP)
        blank()

        MOVL(t0, FPArg("ret", 24))
        RET()

    term()


if __name__ == "__main__":
    main()
