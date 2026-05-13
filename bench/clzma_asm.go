//go:build clzma && (arm64 || amd64)

package bench

/*
#cgo CFLAGS: -O2 -DZ7_LZMA_DEC_OPT -I${SRCDIR}/../tmp/lzma/C
#cgo arm64 CFLAGS: -I${SRCDIR}/../tmp/lzma/Asm/arm64
#cgo LDFLAGS: -L/tmp -lLzmaDecOpt

#include <stdlib.h>

#define Precomp_h
#include "7zTypes.h"
#include "LzmaDec.h"

// Rename all public symbols to avoid collision with the non-asm version in clzma.go.
#define LzmaDecode LzmaDecode_Asm
#define LzmaDec_Allocate LzmaDec_Allocate_Asm
#define LzmaDec_AllocateProbs LzmaDec_AllocateProbs_Asm
#define LzmaDec_DecodeToBuf LzmaDec_DecodeToBuf_Asm
#define LzmaDec_DecodeToDic LzmaDec_DecodeToDic_Asm
#define LzmaDec_Free LzmaDec_Free_Asm
#define LzmaDec_FreeProbs LzmaDec_FreeProbs_Asm
#define LzmaDec_Init LzmaDec_Init_Asm
#define LzmaDec_InitDicAndState LzmaDec_InitDicAndState_Asm
#define LzmaProps_Decode LzmaProps_Decode_Asm

#include "LzmaDec.c"

static void *asm_alloc(ISzAllocPtr p, size_t size) { (void)p; return malloc(size); }
static void asm_free(ISzAllocPtr p, void *addr) { (void)p; free(addr); }
static const ISzAlloc g_asm_alloc = { asm_alloc, asm_free };

static int c_lzma_decode_asm(const unsigned char *src, size_t srcLen,
                  unsigned char *dst, size_t *dstLen,
                  const unsigned char *props, unsigned propsSize) {
    ELzmaStatus status;
    SizeT sl = (SizeT)srcLen;
    SizeT dl = (SizeT)*dstLen;
    SRes res = LzmaDecode_Asm(dst, &dl, src, &sl, props, propsSize,
                          LZMA_FINISH_END, &status, (ISzAllocPtr)&g_asm_alloc);
    *dstLen = (size_t)dl;
    return (int)res;
}
*/
import "C"
import "unsafe"

// CLzmaDecodeAsm decodes LZMA compressed data using the 7z C implementation
// with hand-written assembly for the inner decode loop.
func CLzmaDecodeAsm(props []byte, src []byte, dst []byte) (int, error) {
	dstLen := C.size_t(len(dst))
	res := C.c_lzma_decode_asm(
		(*C.uchar)(unsafe.Pointer(&src[0])),
		C.size_t(len(src)),
		(*C.uchar)(unsafe.Pointer(&dst[0])),
		&dstLen,
		(*C.uchar)(unsafe.Pointer(&props[0])),
		C.uint(len(props)),
	)
	if res != 0 {
		return 0, errCDecode
	}
	return int(dstLen), nil
}
