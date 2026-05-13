package golzma

import "io"

const inputBufSize = 1 << 16 // 64KB

type rangeDecoder struct {
	r   io.Reader
	buf []byte
	pos int
	end int
	eof bool

	code  uint32
	rng   uint32
	ioErr bool
}

func (rd *rangeDecoder) init() error {
	if err := rd.fill(); err != nil {
		return err
	}
	b, err := rd.readByte()
	if err != nil {
		return err
	}
	if b != 0 {
		return ErrData
	}
	rd.rng = 0xFFFFFFFF
	rd.code = 0
	for i := 0; i < 4; i++ {
		b, err := rd.readByte()
		if err != nil {
			return err
		}
		rd.code = (rd.code << 8) | uint32(b)
	}
	return nil
}

func (rd *rangeDecoder) fill() error {
	if rd.eof {
		return io.ErrUnexpectedEOF
	}
	n, err := rd.r.Read(rd.buf[:])
	rd.pos = 0
	rd.end = n
	if err != nil {
		if err == io.EOF {
			rd.eof = true
			if n == 0 {
				return io.ErrUnexpectedEOF
			}
			return nil
		}
		return err
	}
	return nil
}

func (rd *rangeDecoder) readByte() (byte, error) {
	if rd.pos >= rd.end {
		if err := rd.fill(); err != nil {
			return 0, err
		}
	}
	b := rd.buf[rd.pos]
	rd.pos++
	return b, nil
}

func (rd *rangeDecoder) isFinished() bool {
	return rd.code == 0
}
