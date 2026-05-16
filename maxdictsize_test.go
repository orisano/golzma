package golzma

import (
	"bytes"
	"errors"
	"io"
	"os/exec"
	"testing"
)

func TestNewReader_DictSizeTooLarge(t *testing.T) {
	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader([]byte("hello"))
	compressed, err := cmd.Output()
	if err != nil {
		t.Skipf("lzma command not available: %v", err)
	}

	// Default lzma uses a dict far larger than 1 byte; expect rejection.
	_, err = NewReader(bytes.NewReader(compressed), 1)
	if !errors.Is(err, ErrDictSizeTooLarge) {
		t.Fatalf("got err=%v, want ErrDictSizeTooLarge", err)
	}
}

func TestNewReader_DictSizeWithinLimit(t *testing.T) {
	original := []byte("hello world")
	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader(original)
	compressed, err := cmd.Output()
	if err != nil {
		t.Skipf("lzma command not available: %v", err)
	}

	// 256 MiB easily exceeds any default lzma dict size.
	r, err := NewReader(bytes.NewReader(compressed), 256<<20)
	if err != nil {
		t.Fatalf("NewReader: %v", err)
	}
	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}
	if !bytes.Equal(got, original) {
		t.Errorf("got %q, want %q", got, original)
	}
}

func TestNewLZMA2Reader_DictSizeTooLarge(t *testing.T) {
	// dictProp=0x10 → DictSizeFromLZMA2Prop = (2|0)<<(8+11) = 2<<19 = 1 MiB.
	const dictProp byte = 0x10
	want := DictSizeFromLZMA2Prop(dictProp)
	if want != 1<<20 {
		t.Fatalf("sanity: DictSizeFromLZMA2Prop(0x10)=%d, want %d", want, 1<<20)
	}
	_, err := NewLZMA2Reader(bytes.NewReader(nil), dictProp, want-1)
	if !errors.Is(err, ErrDictSizeTooLarge) {
		t.Fatalf("got err=%v, want ErrDictSizeTooLarge", err)
	}
}

func TestNewLZMA2Reader_DictSizeWithinLimit(t *testing.T) {
	const dictProp byte = 0x10
	want := DictSizeFromLZMA2Prop(dictProp)
	r, err := NewLZMA2Reader(bytes.NewReader(nil), dictProp, want)
	if err != nil {
		t.Fatalf("equal-to-limit should succeed: %v", err)
	}
	if r == nil {
		t.Fatal("reader is nil")
	}
}

func TestNewLZMA2Reader_DictSizeUnlimited(t *testing.T) {
	// Max prop byte gives 0xFFFFFFFF; maxDictSize=0 must accept it (no alloc until Read).
	r, err := NewLZMA2Reader(bytes.NewReader(nil), 40, 0)
	if err != nil {
		t.Fatalf("unlimited should succeed: %v", err)
	}
	if r == nil {
		t.Fatal("reader is nil")
	}
}
