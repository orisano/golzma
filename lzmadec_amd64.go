//go:build amd64

package golzma

import (
	"io"
	"unsafe"
)

type cLzmaDec struct {
	lc           byte
	lp           byte
	pb           byte
	_pad         byte
	dicSize      uint32
	probs        unsafe.Pointer
	probs1664    unsafe.Pointer // probs + kStartOffset * PMULT (kStartOffset=1664, PMULT=2)
	dic          unsafe.Pointer
	dicBufSize   uintptr
	dicPos       uintptr
	buf          unsafe.Pointer
	rng          uint32
	code         uint32
	processedPos uint32
	checkDicSize uint32
	rep0         uint32
	rep1         uint32
	rep2         uint32
	rep3         uint32
	state        uint32
	remainLen    uint32
}

// lzmaDecodeReal3 is the AMD64 assembly implementation of the LZMA decode loop.
// It operates on a cLzmaDec struct that matches the CLzmaDec_Asm layout.
//
//go:nosplit
func lzmaDecodeReal3(lzma *cLzmaDec, limit uintptr, bufLimit unsafe.Pointer) int32

func (d *decoder) tryDecodeAsm(limit int) (error, bool) {
	if d.noAsm {
		return nil, false
	}
	rc := d.rc
	startDicPos := d.dicPos

	if d.remainLen > 0 && d.remainLen < matchSpecLenStart {
		d.writeRem(limit)
		if d.dicPos >= limit {
			return nil, true
		}
	}

	for d.dicPos < limit && d.remainLen < matchSpecLenStart {
		avail := rc.end - rc.pos
		if avail < requiredInputMax {
			if rc.eof {
				break
			}
			// Compact remaining bytes to the front and refill.
			n := copy(rc.buf, rc.buf[rc.pos:rc.end])
			rc.pos = 0
			rc.end = n
			nn, err := rc.r.Read(rc.buf[n:])
			rc.end += nn
			if err != nil {
				if err == io.EOF {
					rc.eof = true
				} else {
					return err, true
				}
			}
			avail = rc.end - rc.pos
			if avail < requiredInputMax {
				break
			}
		}

		// Clamp limit so the asm doesn't cross the checkDicSize boundary
		// (matches C SDK's LzmaDec_DecodeReal2 pattern).
		limit2 := limit
		if d.checkDicSize == 0 {
			rem := int(d.prop.dicSize - d.processedPos)
			if limit-d.dicPos > rem {
				limit2 = d.dicPos + rem
			}
		}

		cdec := &d.cdec
		cdec.lc = d.prop.lc
		cdec.lp = d.prop.lp
		cdec.pb = d.prop.pb
		cdec.dicSize = d.prop.dicSize
		cdec.probs = unsafe.Pointer(&d.probs[0])
		cdec.probs1664 = unsafe.Add(cdec.probs, 1664*2) // kStartOffset * PMULT
		cdec.dic = unsafe.Pointer(&d.dic[0])
		cdec.dicBufSize = uintptr(d.dicBufSize)
		cdec.dicPos = uintptr(d.dicPos)
		cdec.buf = unsafe.Pointer(&rc.buf[rc.pos])
		cdec.rng = rc.rng
		cdec.code = rc.code
		cdec.processedPos = d.processedPos
		cdec.checkDicSize = d.checkDicSize
		cdec.rep0 = d.reps[0]
		cdec.rep1 = d.reps[1]
		cdec.rep2 = d.reps[2]
		cdec.rep3 = d.reps[3]
		cdec.state = d.state
		cdec.remainLen = 0

		bufLimit := unsafe.Pointer(&rc.buf[rc.end-requiredInputMax])
		ret := lzmaDecodeReal3(cdec, uintptr(limit2), bufLimit)

		d.dicPos = int(cdec.dicPos)
		rc.pos = int(uintptr(cdec.buf) - uintptr(unsafe.Pointer(&rc.buf[0])))
		rc.rng = cdec.rng
		rc.code = cdec.code
		d.processedPos = cdec.processedPos
		d.reps = [4]uint32{cdec.rep0, cdec.rep1, cdec.rep2, cdec.rep3}
		d.state = cdec.state
		d.remainLen = cdec.remainLen

		if d.checkDicSize == 0 && d.processedPos >= d.prop.dicSize {
			d.checkDicSize = d.prop.dicSize
		}

		if ret != 0 {
			return ErrData, true
		}

		if d.remainLen == matchSpecLenStart {
			if !rc.isFinished() {
				return ErrData, true
			}
			return io.EOF, true
		}

		d.writeRem(limit)
	}

	if d.dicPos > startDicPos {
		return nil, true
	}
	return nil, false
}
