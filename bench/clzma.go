//go:build clzma

package bench

/*
#cgo CFLAGS: -O2 -I${SRCDIR}/../tmp/lzma/C
#include <stdlib.h>

#define Precomp_h
#include "7zTypes.h"
#include "LzmaDec.h"
#include "LzmaDec.c"

static void *my_alloc(ISzAllocPtr p, size_t size) { (void)p; return malloc(size); }
static void my_free(ISzAllocPtr p, void *addr) { (void)p; free(addr); }
static const ISzAlloc g_alloc = { my_alloc, my_free };

static int c_lzma_decode(const unsigned char *src, size_t srcLen,
                  unsigned char *dst, size_t *dstLen,
                  const unsigned char *props, unsigned propsSize) {
    ELzmaStatus status;
    SizeT sl = (SizeT)srcLen;
    SizeT dl = (SizeT)*dstLen;
    SRes res = LzmaDecode(dst, &dl, src, &sl, props, propsSize,
                          LZMA_FINISH_END, &status, (ISzAllocPtr)&g_alloc);
    *dstLen = (size_t)dl;
    return (int)res;
}
*/
import "C"
import (
	"errors"
	"unsafe"
)

var errCDecode = errors.New("clzma: decode error")

// CLzmaDecode decodes LZMA compressed data using the 7z C implementation.
func CLzmaDecode(props []byte, src []byte, dst []byte) (int, error) {
	dstLen := C.size_t(len(dst))
	res := C.c_lzma_decode(
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
