package golzma

import "io"

type decoder struct {
	rc    *rangeDecoder
	probs []uint16

	dic        []byte
	dicBufSize int
	dicPos     int
	readPos    int

	prop         props
	size         int64
	eos          bool
	state        uint32
	reps         [4]uint32
	processedPos uint32
	checkDicSize uint32
	remainLen    uint32
	noAsm        bool
	cdec         cLzmaDec
}

// fillProbs fills p with the initial probability value using a doubling
// copy, which lets the runtime use optimized memcpy for most of the work.
func fillProbs(p []uint16) {
	if len(p) == 0 {
		return
	}
	p[0] = bitModelTotal >> 1
	for n := 1; n < len(p); n *= 2 {
		copy(p[n:], p[:n])
	}
}

// Reset resets the decoder to decompress a new stream, reusing internal buffers
// when possible. This avoids repeated allocation of the large dictionary buffer.
func (d *decoder) Reset(p props, r io.Reader, size int64) {
	dicSize := int(p.dicSize)
	np := int(numProbs(&p))

	// Reuse dic if large enough.
	// Allocate 16 extra bytes as padding so the asm wide-copy path
	// can safely overshoot by up to 15 bytes on the last iteration.
	if cap(d.dic) >= dicSize+16 {
		d.dic = d.dic[:dicSize+16]
	} else {
		d.dic = make([]byte, dicSize+16)
	}

	// Reuse probs if large enough
	if cap(d.probs) >= np {
		d.probs = d.probs[:np]
	} else {
		d.probs = make([]uint16, np)
	}
	fillProbs(d.probs)

	d.dicBufSize = dicSize
	d.dicPos = 0
	d.readPos = 0
	d.prop = p
	d.size = size
	d.eos = false
	d.state = 0
	d.reps = [4]uint32{1, 1, 1, 1}
	d.processedPos = 0
	d.checkDicSize = 0
	d.remainLen = 0

	if d.rc == nil {
		d.rc = &rangeDecoder{r: r, buf: make([]byte, inputBufSize)}
	} else {
		d.rc.r = r
		if d.rc.buf == nil {
			d.rc.buf = make([]byte, inputBufSize)
		}
		d.rc.pos = 0
		d.rc.end = 0
		d.rc.eof = false
		d.rc.code = 0
		d.rc.rng = 0
		d.rc.ioErr = false
	}
}

// writeRem completes a pending match copy. This mirrors LzmaDec_WriteRem in
// the C SDK: after the assembly decode loop exits mid-match, the remaining
// bytes must be written to the dictionary before re-entering the decode loop.
func (d *decoder) writeRem(limit int) {
	curLen := int(d.remainLen)
	rem := limit - d.dicPos
	if curLen > rem {
		curLen = rem
	}
	d.remainLen -= uint32(curLen)
	d.processedPos += uint32(curLen)

	dic := d.dic[:d.dicBufSize]
	dicBufSize := d.dicBufSize
	rep0 := int(d.reps[0])
	dicPos := d.dicPos

	pos := dicPos - rep0
	if pos < 0 {
		pos += dicBufSize
	}
	for i := 0; i < curLen; i++ {
		dic[dicPos] = dic[pos]
		dicPos++
		pos++
		if pos == dicBufSize {
			pos = 0
		}
	}
	d.dicPos = dicPos

	if d.checkDicSize == 0 && d.processedPos >= d.prop.dicSize {
		d.checkDicSize = d.prop.dicSize
	}
}

func (d *decoder) Read(p []byte) (int, error) {
	if d.readPos < d.dicPos {
		n := copy(p, d.dic[d.readPos:d.dicPos])
		d.readPos += n
		return n, nil
	}
	if d.eos {
		return 0, io.EOF
	}
	if d.rc.rng == 0 {
		if err := d.rc.init(); err != nil {
			return 0, err
		}
	}

	total := 0
	for len(p) > 0 {
		if d.readPos < d.dicPos {
			n := copy(p, d.dic[d.readPos:d.dicPos])
			d.readPos += n
			p = p[n:]
			total += n
			continue
		}
		if d.eos {
			break
		}
		if d.dicPos == d.dicBufSize {
			d.dicPos = 0
			d.readPos = 0
		}

		limit := d.dicBufSize
		if d.size >= 0 {
			rem := int(d.size)
			if rem <= 0 {
				d.eos = true
				break
			}
			if d.dicPos+rem < limit {
				limit = d.dicPos + rem
			}
		}

		err, used := d.tryDecodeAsm(limit)
		if !used {
			err = d.decodeLoop(limit)
		}
		produced := d.dicPos - d.readPos
		if d.size >= 0 && produced > 0 {
			d.size -= int64(produced)
		}
		if err != nil {
			if err == io.EOF {
				d.eos = true
			} else {
				return total, err
			}
		}
	}
	if total > 0 {
		return total, nil
	}
	if d.eos {
		return 0, io.EOF
	}
	return 0, nil
}

//go:noinline
func rcFillAndNorm(rc *rangeDecoder, rng, code uint32) (uint32, uint32, bool) {
	if rc.pos >= rc.end {
		if rc.fill() != nil {
			return rng, code, false
		}
	}
	rng <<= 8
	code = (code << 8) | uint32(rc.buf[rc.pos])
	rc.pos++
	return rng, code, true
}

func (d *decoder) decodeLoop(limit int) error {
	// Complete any pending match from a previous call (e.g., when the
	// dictionary wrapped mid-match).
	if d.remainLen > 0 && d.remainLen < matchSpecLenStart {
		d.writeRem(limit)
		if d.dicPos >= limit {
			return nil
		}
	}
	dic := d.dic[:d.dicBufSize]
	dicBufSize := d.dicBufSize
	dicPos := d.dicPos
	processedPos := d.processedPos
	checkDicSize := d.checkDicSize
	state := d.state
	rep0, rep1, rep2, rep3 := d.reps[0], d.reps[1], d.reps[2], d.reps[3]

	probs := d.probs
	pbMask := uint32(1<<d.prop.pb) - 1
	lc := d.prop.lc
	lpMask := (uint32(0x100) << d.prop.lp) - (uint32(0x100) >> lc)
	rc := d.rc
	rng := rc.rng
	code := rc.code

	var remainLen uint32
	var ioErr bool

	decodeBit := func(prob *uint16) int {
		if rng < topValue {
			var ok bool
			rng, code, ok = rcFillAndNorm(rc, rng, code)
			if !ok {
				ioErr = true
				return 0
			}
		}
		ttt := uint32(*prob)
		bound := (rng >> numBitModelTotalBits) * ttt
		if code < bound {
			rng = bound
			*prob = uint16(ttt + ((bitModelTotal - ttt) >> numMoveBits))
			return 0
		}
		rng -= bound
		code -= bound
		*prob = uint16(ttt - (ttt >> numMoveBits))
		return 1
	}

	for dicPos < limit {
		if ioErr {
			break
		}

		posState := (processedPos & pbMask) << 4

		bit := decodeBit(&probs[probIsMatch+int(posState+state)])

		if bit == 0 {
			probIdx := probLiteral
			if processedPos != 0 || checkDicSize != 0 {
				prevByte := uint32(dic[(dicPos-1+dicBufSize)%dicBufSize])
				probIdx += int(3 * (((processedPos<<8 + prevByte) & lpMask) << lc))
			}
			prob := probs[probIdx:]
			processedPos++

			if state < numLitStates {
				if state < 4 {
					state = 0
				} else {
					state -= 3
				}
				symbol := uint32(1)
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				symbol = (symbol << 1) | uint32(decodeBit(&prob[symbol]))
				dic[dicPos] = byte(symbol)
				dicPos++
			} else {
				matchByte := uint32(dic[(dicPos-int(rep0)+dicBufSize)%dicBufSize])
				offs := uint32(0x100)
				if state < 10 {
					state -= 3
				} else {
					state -= 6
				}
				symbol := uint32(1)
				for symbol < 0x100 {
					matchByte <<= 1
					mbit := offs
					offs &= matchByte
					b := decodeBit(&prob[offs+mbit+symbol])
					symbol = (symbol << 1) | uint32(b)
					if b == 0 {
						offs ^= mbit
					}
				}
				dic[dicPos] = byte(symbol)
				dicPos++
			}
			continue
		}

		// Match or rep
		var length uint32
		var probLen []uint16

		bit = decodeBit(&probs[probIsRep+int(state)])

		if bit == 0 {
			state += numStates
			probLen = probs[probLenCoder:]
		} else {
			bit = decodeBit(&probs[probIsRepG0+int(state)])
			if bit == 0 {
				bit = decodeBit(&probs[probIsRep0Long+int(posState+state)])
				if bit == 0 {
					if checkDicSize == 0 && processedPos == 0 {
						ioErr = true
						break
					}
					dic[dicPos] = dic[(dicPos-int(rep0)+dicBufSize)%dicBufSize]
					dicPos++
					processedPos++
					if state < numLitStates {
						state = 9
					} else {
						state = 11
					}
					continue
				}
			} else {
				bit = decodeBit(&probs[probIsRepG1+int(state)])
				if bit == 0 {
					rep0, rep1 = rep1, rep0
				} else {
					bit = decodeBit(&probs[probIsRepG2+int(state)])
					if bit == 0 {
						rep0, rep1, rep2 = rep2, rep0, rep1
					} else {
						rep0, rep1, rep2, rep3 = rep3, rep0, rep1, rep2
					}
				}
			}
			if state < numLitStates {
				state = 8
			} else {
				state = 11
			}
			probLen = probs[probRepLenCoder:]
		}

		// Decode length (unrolled)
		if decodeBit(&probLen[lenChoice]) == 0 {
			m := uint32(1)
			pl := probLen[lenLow+int(posState):]
			m = (m << 1) | uint32(decodeBit(&pl[m]))
			m = (m << 1) | uint32(decodeBit(&pl[m]))
			m = (m << 1) | uint32(decodeBit(&pl[m]))
			length = m - (1 << numLenLowBits)
		} else if decodeBit(&probLen[lenChoice2]) == 0 {
			m := uint32(1)
			pl := probLen[lenLow+int(posState)+(1<<numLenLowBits):]
			m = (m << 1) | uint32(decodeBit(&pl[m]))
			m = (m << 1) | uint32(decodeBit(&pl[m]))
			m = (m << 1) | uint32(decodeBit(&pl[m]))
			length = m - (1 << numLenLowBits) + numLenLowSymbols
		} else {
			m := uint32(1)
			pl := probLen[lenHigh:]
			for i := 0; i < numLenHighBits; i++ {
				m = (m << 1) | uint32(decodeBit(&pl[m]))
			}
			length = m - (1 << numLenHighBits) + numLenLowSymbols*2
		}

		if state >= numStates {
			var distance uint32
			lenState := length
			if lenState >= numLenToPosStates {
				lenState = numLenToPosStates - 1
			}

			{
				m := uint32(1)
				pSlot := probs[probPosSlot+int(lenState<<numPosSlotBits):]
				m = (m << 1) | uint32(decodeBit(&pSlot[m]))
				m = (m << 1) | uint32(decodeBit(&pSlot[m]))
				m = (m << 1) | uint32(decodeBit(&pSlot[m]))
				m = (m << 1) | uint32(decodeBit(&pSlot[m]))
				m = (m << 1) | uint32(decodeBit(&pSlot[m]))
				m = (m << 1) | uint32(decodeBit(&pSlot[m]))
				distance = m - (1 << numPosSlotBits)
			}

			if distance >= startPosModelIndex {
				posSlotVal := distance
				numDirectBits := (distance >> 1) - 1
				distance = 2 | (distance & 1)

				if posSlotVal < endPosModelIndex {
					distance <<= numDirectBits
					pSpec := probs[probSpecPos:]
					m := uint32(1)
					distance++
					for numDirectBits > 0 {
						numDirectBits--
						bit := decodeBit(&pSpec[distance])
						if bit == 0 {
							distance += m
							m <<= 1
						} else {
							m <<= 1
							distance += m
						}
					}
					distance -= m
				} else {
					numDirectBits -= numAlignBits
					var direct uint32
					ndBits := numDirectBits
					for ndBits > 0 {
						ndBits--
						if rng < topValue {
							var ok bool
							rng, code, ok = rcFillAndNorm(rc, rng, code)
							if !ok {
								ioErr = true
								break
							}
						}
						rng >>= 1
						code -= rng
						t := uint32(0) - (code >> 31)
						code += rng & t
						direct = (direct << 1) + t + 1
					}
					distance = (distance << numDirectBits) | direct
					distance <<= numAlignBits

					pAlign := probs[probAlign:]
					ai := uint32(1)
					b0 := decodeBit(&pAlign[ai])
					if b0 == 0 {
						ai <<= 1
					} else {
						distance |= 1
						ai = (ai << 1) | 1
					}
					b1 := decodeBit(&pAlign[ai])
					if b1 == 0 {
						ai <<= 1
					} else {
						distance |= 2
						ai = (ai << 1) | 1
					}
					b2 := decodeBit(&pAlign[ai])
					if b2 == 0 {
						ai <<= 1
					} else {
						distance |= 4
						ai = (ai << 1) | 1
					}
					if decodeBit(&pAlign[ai]) != 0 {
						distance |= 8
					}

					if distance == 0xFFFFFFFF {
						remainLen = matchSpecLenStart
						state -= numStates
						break
					}
				}
			}

			rep3 = rep2
			rep2 = rep1
			rep1 = rep0
			rep0 = distance + 1

			if state < numStates+numLitStates {
				state = numLitStates
			} else {
				state = numLitStates + 3
			}

			distLimit := checkDicSize
			if distLimit == 0 {
				distLimit = processedPos
			}
			if rep0 > distLimit {
				ioErr = true
				break
			}
		}

		length += matchMinLen

		if checkDicSize == 0 && d.prop.dicSize-processedPos <= length {
			checkDicSize = d.prop.dicSize
		}

		curLen := int(length)
		rem := limit - dicPos
		if curLen > rem {
			curLen = rem
			remainLen = length - uint32(curLen)
		}
		processedPos += uint32(curLen)

		// Fast match copy
		pos := dicPos - int(rep0)
		if pos < 0 {
			pos += dicBufSize
		}
		if curLen <= dicBufSize-pos && int(rep0) <= dicBufSize-pos {
			dd := dic[dicPos : dicPos+curLen]
			dicPos += curLen
			// Doubling copy: seed with rep0 bytes, then double.
			// Handles all cases: RLE (rep0==1), overlapping, and
			// non-overlapping (rep0>=curLen) via a single pattern.
			n := copy(dd, dic[pos:pos+int(rep0)])
			for n < len(dd) {
				n += copy(dd[n:], dd[:n])
			}
		} else {
			for curLen > 0 {
				dic[dicPos] = dic[pos]
				dicPos++
				pos++
				if pos == dicBufSize {
					pos = 0
				}
				curLen--
			}
		}

		if remainLen > 0 {
			break
		}
	}

	d.dicPos = dicPos
	d.processedPos = processedPos
	d.checkDicSize = checkDicSize
	d.state = state
	d.reps = [4]uint32{rep0, rep1, rep2, rep3}
	d.remainLen = remainLen
	rc.rng = rng
	rc.code = code

	if ioErr {
		return ErrData
	}
	if remainLen == matchSpecLenStart {
		if !rc.isFinished() {
			return ErrData
		}
		return io.EOF
	}
	return nil
}
