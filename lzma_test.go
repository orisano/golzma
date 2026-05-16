package golzma

import (
	"bytes"
	"io"
	"os"
	"os/exec"
	"testing"
)

func TestNewReader(t *testing.T) {
	original := "Hello, World! This is a test of LZMA compression in Go. The quick brown fox jumps over the lazy dog.\n"

	// Compress using lzma command
	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader([]byte(original))
	compressed, err := cmd.Output()
	if err != nil {
		t.Skipf("lzma command not available: %v", err)
	}

	r, err := NewReader(bytes.NewReader(compressed), 0)
	if err != nil {
		t.Fatalf("NewReader: %v", err)
	}

	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}

	if string(got) != original {
		t.Errorf("got %q, want %q", got, original)
	}
}

func TestNewReaderLarger(t *testing.T) {
	// Generate larger test data with repetition (good for LZMA)
	var buf bytes.Buffer
	for i := 0; i < 1000; i++ {
		buf.WriteString("The quick brown fox jumps over the lazy dog. ")
	}
	original := buf.Bytes()

	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader(original)
	compressed, err := cmd.Output()
	if err != nil {
		t.Skipf("lzma command not available: %v", err)
	}

	r, err := NewReader(bytes.NewReader(compressed), 0)
	if err != nil {
		t.Fatalf("NewReader: %v", err)
	}

	got, err := io.ReadAll(r)
	if err != nil {
		t.Fatalf("ReadAll: %v", err)
	}

	if !bytes.Equal(got, original) {
		t.Errorf("decompressed data mismatch: got %d bytes, want %d bytes", len(got), len(original))
	}
}

func TestNewReaderKnownSize(t *testing.T) {
	// Test with known-size LZMA stream
	original := []byte("ABCABCABCABC")
	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader(original)
	compressed, err := cmd.Output()
	if err != nil {
		t.Skipf("lzma command not available: %v", err)
	}

	r, err := NewReader(bytes.NewReader(compressed), 0)
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

func BenchmarkDecode(b *testing.B) {
	var buf bytes.Buffer
	for i := 0; i < 1000; i++ {
		buf.WriteString("The quick brown fox jumps over the lazy dog. ")
	}
	original := buf.Bytes()

	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader(original)
	compressed, err := cmd.Output()
	if err != nil {
		b.Skipf("lzma command not available: %v", err)
	}

	for _, noAsm := range []bool{false, true} {
		name := "Asm"
		if noAsm {
			name = "PureGo"
		}
		b.Run(name, func(b *testing.B) {
			b.SetBytes(int64(len(original)))
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				r, err := NewReader(bytes.NewReader(compressed), 0)
				if err != nil {
					b.Fatal(err)
				}
				r.(*decoder).noAsm = noAsm
				_, err = io.Copy(io.Discard, r)
				if err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}

func TestNewReaderFile(t *testing.T) {
	// Create a temp file, compress it, and decompress
	original := []byte("Test data for file-based LZMA decompression\n")

	tmp, err := os.CreateTemp("", "golzma-test-*.lzma")
	if err != nil {
		t.Fatal(err)
	}
	defer os.Remove(tmp.Name())

	// Compress
	cmd := exec.Command("lzma", "-c")
	cmd.Stdin = bytes.NewReader(original)
	cmd.Stdout = tmp
	if err := cmd.Run(); err != nil {
		t.Skipf("lzma command not available: %v", err)
	}
	tmp.Close()

	f, err := os.Open(tmp.Name())
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()

	r, err := NewReader(f, 0)
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
