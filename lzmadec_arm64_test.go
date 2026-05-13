//go:build arm64

package golzma

import (
	"bytes"
	"io"
	"os/exec"
	"testing"
)

func compressWithLzma(t *testing.T, data []byte) []byte {
	t.Helper()
	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader(data)
	out, err := cmd.Output()
	if err != nil {
		t.Skipf("lzma command not available: %v", err)
	}
	return out
}

func TestTryDecodeAsmShort(t *testing.T) {
	original := []byte("Hello, World!")
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("got %q, want %q", got, original)
	}
}

func TestTryDecodeAsmRepetitive(t *testing.T) {
	// Highly repetitive data exercises match/rep paths.
	var buf bytes.Buffer
	for i := 0; i < 10000; i++ {
		buf.WriteString("ABCABC")
	}
	original := buf.Bytes()
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("length: got %d, want %d", len(got), len(original))
	}
}

func TestTryDecodeAsmLargeData(t *testing.T) {
	// Larger data that triggers multiple buffer refills in the asm bridge.
	size := 256 * 1024
	original := make([]byte, size)
	state := uint32(0xDEADBEEF)
	for i := range original {
		state = state*1103515245 + 12345
		original[i] = byte(state >> 16)
	}
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("data mismatch: got %d bytes, want %d bytes", len(got), len(original))
	}
}

func TestTryDecodeAsmMixed(t *testing.T) {
	// Mixed data: text interleaved with pseudo-random bytes.
	// Exercises literal, match, rep, and long-distance paths.
	var buf bytes.Buffer
	phrases := []string{
		"The quick brown fox jumps over the lazy dog. ",
		"Lorem ipsum dolor sit amet. ",
		"Pack my box with five dozen liquor jugs! ",
	}
	state := uint32(42)
	for buf.Len() < 128*1024 {
		state = state*1103515245 + 12345
		if state%3 != 0 {
			buf.WriteString(phrases[int(state>>8)%len(phrases)])
		} else {
			for j := 0; j < 64; j++ {
				state = state*1103515245 + 12345
				buf.WriteByte(byte(state >> 16))
			}
		}
	}
	original := buf.Bytes()
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("data mismatch: got %d bytes, want %d bytes", len(got), len(original))
	}
}

func TestTryDecodeAsmSingleByte(t *testing.T) {
	original := []byte{0x42}
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("got %v, want %v", got, original)
	}
}

func TestTryDecodeAsmAllZeros(t *testing.T) {
	original := make([]byte, 4096)
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("data mismatch: got %d bytes, want %d bytes", len(got), len(original))
	}
}

func TestTryDecodeAsmAllValues(t *testing.T) {
	// All byte values 0-255 repeated.
	original := make([]byte, 256*16)
	for i := range original {
		original[i] = byte(i)
	}
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("data mismatch: got %d bytes, want %d bytes", len(got), len(original))
	}
}

func TestTryDecodeAsmSmallReads(t *testing.T) {
	// Read one byte at a time to stress the outer Read loop
	// and buffer management around asm calls.
	var buf bytes.Buffer
	for i := 0; i < 1000; i++ {
		buf.WriteString("Hello LZMA! ")
	}
	original := buf.Bytes()
	compressed := compressWithLzma(t, original)

	r, err := NewReader(bytes.NewReader(compressed))
	if err != nil {
		t.Fatal(err)
	}

	var result bytes.Buffer
	b := make([]byte, 1)
	for {
		n, err := r.Read(b)
		if n > 0 {
			result.Write(b[:n])
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
	}
	if !bytes.Equal(result.Bytes(), original) {
		t.Errorf("data mismatch: got %d bytes, want %d bytes", result.Len(), len(original))
	}
}

func TestTryDecodeAsmVariousSizes(t *testing.T) {
	// Test multiple sizes to catch boundary issues.
	for _, size := range []int{0, 1, 13, 100, 4095, 4096, 4097, 8192, 65536} {
		t.Run("", func(t *testing.T) {
			original := make([]byte, size)
			for i := range original {
				original[i] = byte(i*7 + 13)
			}
			compressed := compressWithLzma(t, original)

			r, err := NewReader(bytes.NewReader(compressed))
			if err != nil {
				t.Fatal(err)
			}
			got, err := io.ReadAll(r)
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(got, original) {
				t.Errorf("size %d: data mismatch: got %d bytes", size, len(got))
			}
		})
	}
}
