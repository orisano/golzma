package golzma

import (
	"errors"
	"io"
)

var (
	ErrData             = errors.New("lzma: data error")
	ErrUnsupported      = errors.New("lzma: unsupported properties")
	ErrDictSizeTooLarge = errors.New("lzma: dictionary size exceeds limit")
)

const (
	propsSize = 5

	numBitModelTotalBits = 11
	bitModelTotal        = 1 << numBitModelTotalBits
	numMoveBits          = 5

	numPosBitsMax   = 4
	numPosStatesMax = 1 << numPosBitsMax

	numLenLowBits     = 3
	numLenLowSymbols  = 1 << numLenLowBits
	numLenHighBits    = 8
	numLenHighSymbols = 1 << numLenHighBits

	lenLow  = 0
	lenHigh = lenLow + 2*(numPosStatesMax<<numLenLowBits)

	lenChoice  = lenLow
	lenChoice2 = lenLow + (1 << numLenLowBits)

	numStates    = 12
	numStates2   = 16
	numLitStates = 7

	startPosModelIndex = 4
	endPosModelIndex   = 14
	numFullDistances   = 1 << (endPosModelIndex >> 1)

	numPosSlotBits    = 6
	numLenToPosStates = 4

	numAlignBits   = 4
	alignTableSize = 1 << numAlignBits

	matchMinLen       = 2
	matchSpecLenStart = matchMinLen + numLenLowSymbols*2 + numLenHighSymbols

	litSize = 0x300

	probSpecPos     = 0
	probIsRep0Long  = probSpecPos + numFullDistances
	probRepLenCoder = probIsRep0Long + (numStates2 << numPosBitsMax)
	probLenCoder    = probRepLenCoder + (lenHigh + numLenHighSymbols)
	probIsMatch     = probLenCoder + (lenHigh + numLenHighSymbols)
	probAlign       = probIsMatch + (numStates2 << numPosBitsMax)
	probIsRep       = probAlign + alignTableSize
	probIsRepG0     = probIsRep + numStates
	probIsRepG1     = probIsRepG0 + numStates
	probIsRepG2     = probIsRepG1 + numStates
	probPosSlot     = probIsRepG2 + numStates
	probLiteral     = probPosSlot + (numLenToPosStates << numPosSlotBits)
	numBaseProbs    = probLiteral

	dicMin = 1 << 12

	topValue = 1 << 24

	requiredInputMax = 20
)

type props struct {
	lc      byte
	lp      byte
	pb      byte
	dicSize uint32
}

func decodeProps(data []byte) (props, error) {
	if len(data) < propsSize {
		return props{}, ErrUnsupported
	}
	var p props
	p.dicSize = uint32(data[1]) | uint32(data[2])<<8 | uint32(data[3])<<16 | uint32(data[4])<<24
	if p.dicSize < dicMin {
		p.dicSize = dicMin
	}
	d := data[0]
	if d >= 9*5*5 {
		return props{}, ErrUnsupported
	}
	p.lc = d % 9
	d /= 9
	p.pb = d / 5
	p.lp = d % 5
	return p, nil
}

func numProbs(p *props) uint32 {
	return numBaseProbs + uint32(litSize)<<(p.lc+p.lp)
}

const headerSize = propsSize + 8

// Decoder is an LZMA decompressor. It implements io.Reader.
// A Decoder may be reused by calling Reset, which avoids re-allocating
// the internal dictionary buffer.
type Decoder = decoder

// NewRawReader creates an LZMA decompressing reader from a raw LZMA stream
// (without the 13-byte .lzma header). propData must be exactly 5 bytes
// (1 byte lc/lp/pb + 4 bytes dictionary size). size is the uncompressed size
// or -1 if unknown. maxDictSize bounds the dictionary size in bytes;
// streams exceeding it are rejected with ErrDictSizeTooLarge. 0 disables
// the check. If dec is non-nil, its internal buffers are reused.
func NewRawReader(r io.Reader, propData []byte, size int64, maxDictSize uint32, dec *Decoder) (*Decoder, error) {
	p, err := decodeProps(propData)
	if err != nil {
		return nil, err
	}
	if maxDictSize != 0 && p.dicSize > maxDictSize {
		return nil, ErrDictSizeTooLarge
	}
	if dec == nil {
		dec = new(Decoder)
	}
	dec.Reset(p, r, size)
	return dec, nil
}

// NewReader creates an LZMA decompressing reader from a .lzma format stream.
// It reads the 13-byte header (5 bytes properties + 8 bytes uncompressed size).
// maxDictSize bounds the dictionary size in bytes; streams exceeding it are
// rejected with ErrDictSizeTooLarge. 0 disables the check.
func NewReader(r io.Reader, maxDictSize uint32) (io.Reader, error) {
	return NewReaderWithDecoder(r, maxDictSize, nil)
}

// NewReaderWithDecoder is like NewReader but reuses the given Decoder's internal
// buffers. Pass a previously used *Decoder to avoid re-allocating the dictionary.
// If dec is nil, a new Decoder is allocated.
func NewReaderWithDecoder(r io.Reader, maxDictSize uint32, dec *Decoder) (*Decoder, error) {
	var hdr [headerSize]byte
	if _, err := io.ReadFull(r, hdr[:]); err != nil {
		return nil, err
	}
	p, err := decodeProps(hdr[:propsSize])
	if err != nil {
		return nil, err
	}
	if maxDictSize != 0 && p.dicSize > maxDictSize {
		return nil, ErrDictSizeTooLarge
	}
	size := int64(0)
	for i := 0; i < 8; i++ {
		size |= int64(hdr[propsSize+i]) << (8 * i)
	}
	if uint64(size) == 0xFFFFFFFFFFFFFFFF {
		size = -1
	}
	if dec == nil {
		dec = new(Decoder)
	}
	dec.Reset(p, r, size)
	return dec, nil
}
