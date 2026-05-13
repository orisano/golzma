package golzma

import (
	"encoding/binary"
	"errors"
	"io"
)

// DictSizeFromLZMA2Prop converts an LZMA2 dictionary size property byte
// to the dictionary size in bytes.
func DictSizeFromLZMA2Prop(b byte) uint32 {
	if b >= 40 {
		return 0xFFFFFFFF
	}
	return (2 | uint32(b)&1) << (uint32(b)/2 + 11)
}

// LZMA2Reader decompresses an LZMA2 stream.
type LZMA2Reader struct {
	r       io.Reader
	dec     decoder
	dicSize uint32
	inited  bool

	propByte byte
	propSet  bool
	eof      bool

	// current chunk tracking
	chunkRemain int       // unpack bytes remaining in current chunk
	chunkR      io.Reader // limited reader for current LZMA chunk's packed data
	inLZMA      bool      // currently in an LZMA chunk
	inUncomp    bool      // currently in an uncompressed chunk
}

// NewLZMA2Reader creates a new LZMA2 decompressing reader.
// dictProp is the LZMA2 dictionary size property byte.
func NewLZMA2Reader(r io.Reader, dictProp byte) *LZMA2Reader {
	return &LZMA2Reader{
		r:       r,
		dicSize: DictSizeFromLZMA2Prop(dictProp),
	}
}

func (lr *LZMA2Reader) init() {
	if lr.inited {
		return
	}
	lr.inited = true
	dicSize := int(lr.dicSize)
	d := &lr.dec
	d.dic = make([]byte, dicSize+16) // 16 bytes padding for asm wide-copy overshoot
	d.dicBufSize = dicSize
	d.rc = &rangeDecoder{buf: make([]byte, inputBufSize)}
	d.reps = [4]uint32{1, 1, 1, 1}
}

func (lr *LZMA2Reader) Read(p []byte) (int, error) {
	if lr.eof {
		return 0, io.EOF
	}
	lr.init()

	d := &lr.dec
	total := 0

	for len(p) > 0 {
		// Return buffered output from dictionary
		if d.readPos < d.dicPos {
			n := copy(p, d.dic[d.readPos:d.dicPos])
			d.readPos += n
			p = p[n:]
			total += n
			continue
		}

		if lr.eof {
			break
		}

		// Handle dictionary wrap
		if d.dicPos == d.dicBufSize {
			d.dicPos = 0
			d.readPos = 0
		}

		// Continue current LZMA chunk
		if lr.inLZMA && lr.chunkRemain > 0 {
			limit := d.dicPos + lr.chunkRemain
			if limit > d.dicBufSize {
				limit = d.dicBufSize
			}

			if d.remainLen > 0 && d.remainLen < matchSpecLenStart {
				d.writeRem(limit)
			}
			if d.dicPos < limit {
				err, used := d.tryDecodeAsm(limit)
				if !used {
					err = d.decodeLoop(limit)
				}
				if err != nil && err != io.EOF {
					return total, err
				}
			}

			produced := d.dicPos - d.readPos
			lr.chunkRemain -= produced
			if lr.chunkRemain <= 0 {
				lr.inLZMA = false
				// Drain remaining packed data
				io.Copy(io.Discard, lr.chunkR)
			}
			continue
		}
		lr.inLZMA = false

		// Continue current uncompressed chunk
		if lr.inUncomp && lr.chunkRemain > 0 {
			space := d.dicBufSize - d.dicPos
			toRead := lr.chunkRemain
			if toRead > space {
				toRead = space
			}
			n, err := io.ReadFull(lr.r, d.dic[d.dicPos:d.dicPos+toRead])
			d.dicPos += n
			d.processedPos += uint32(n)
			lr.chunkRemain -= n
			if d.checkDicSize == 0 && d.processedPos >= d.prop.dicSize {
				d.checkDicSize = d.prop.dicSize
			}
			if lr.chunkRemain <= 0 {
				lr.inUncomp = false
			}
			if err != nil {
				return total, err
			}
			continue
		}
		lr.inUncomp = false

		// Read next chunk header
		var ctrlBuf [1]byte
		if _, err := io.ReadFull(lr.r, ctrlBuf[:]); err != nil {
			if total > 0 {
				return total, nil
			}
			return 0, err
		}
		control := ctrlBuf[0]

		if control == 0x00 {
			lr.eof = true
			break
		}

		if control <= 0x02 {
			// Uncompressed chunk
			var szBuf [2]byte
			if _, err := io.ReadFull(lr.r, szBuf[:]); err != nil {
				return total, err
			}
			dataSize := int(binary.BigEndian.Uint16(szBuf[:])) + 1

			if control == 0x01 {
				// Reset dictionary
				d.dicPos = 0
				d.readPos = 0
				d.processedPos = 0
				d.checkDicSize = 0
			}

			lr.chunkRemain = dataSize
			lr.inUncomp = true
			continue
		}

		if control < 0x80 {
			return total, errors.New("lzma2: invalid control byte")
		}

		// LZMA compressed chunk
		var chunkHdr [4]byte
		if _, err := io.ReadFull(lr.r, chunkHdr[:]); err != nil {
			return total, err
		}

		unpackSize := ((int(control&0x1F) << 16) | (int(chunkHdr[0]) << 8) | int(chunkHdr[1])) + 1
		packSize := ((int(chunkHdr[2]) << 8) | int(chunkHdr[3])) + 1

		resetDict := control >= 0xE0
		resetState := control >= 0xA0
		resetProps := control >= 0xC0

		if resetProps {
			var pb [1]byte
			if _, err := io.ReadFull(lr.r, pb[:]); err != nil {
				return total, err
			}
			lr.propByte = pb[0]
			lr.propSet = true

			var propData [5]byte
			propData[0] = lr.propByte
			binary.LittleEndian.PutUint32(propData[1:], lr.dicSize)

			prop, err := decodeProps(propData[:])
			if err != nil {
				return total, err
			}
			d.prop = prop

			np := int(numProbs(&prop))
			if cap(d.probs) >= np {
				d.probs = d.probs[:np]
			} else {
				d.probs = make([]uint16, np)
			}
		}

		if !lr.propSet {
			return total, errors.New("lzma2: LZMA properties not set")
		}

		if resetDict {
			d.dicPos = 0
			d.readPos = 0
			d.processedPos = 0
			d.checkDicSize = 0
		}

		if resetState {
			fillProbs(d.probs)
			d.state = 0
			d.reps = [4]uint32{1, 1, 1, 1}
			d.remainLen = 0
		}

		// Set up limited reader for packed data
		lr.chunkR = io.LimitReader(lr.r, int64(packSize))

		// Re-init range coder
		d.rc.r = lr.chunkR
		d.rc.pos = 0
		d.rc.end = 0
		d.rc.eof = false
		d.rc.ioErr = false

		if err := d.rc.init(); err != nil {
			return total, err
		}

		d.eos = false
		lr.chunkRemain = unpackSize
		lr.inLZMA = true
	}

	if total > 0 {
		return total, nil
	}
	if lr.eof {
		return 0, io.EOF
	}
	return 0, nil
}
