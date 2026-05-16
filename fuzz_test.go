package golzma

import (
	"bytes"
	"io"
	"testing"
)

func FuzzNewReader(f *testing.F) {
	f.Fuzz(func(t *testing.T, data []byte) {
		r, err := NewReader(bytes.NewReader(data), 0)
		if err != nil {
			return
		}
		io.Copy(io.Discard, r)
	})
}

func FuzzLZMA2Reader(f *testing.F) {
	f.Fuzz(func(t *testing.T, prop byte, data []byte) {
		r, err := NewLZMA2Reader(bytes.NewReader(data), prop, 0)
		if err != nil {
			return
		}
		io.Copy(io.Discard, r)
	})
}
