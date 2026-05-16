package bench

import (
	"bytes"
	"io"
	"os/exec"
	"testing"

	"github.com/orisano/golzma"
)

func compressLZMA(tb testing.TB, data []byte) []byte {
	tb.Helper()
	lzmaPath, err := exec.LookPath("lzma")
	if err != nil {
		tb.Skipf("lzma command not available: %v", err)
	}
	cmd := exec.Command(lzmaPath, "-c")
	cmd.Stdin = bytes.NewReader(data)
	out, err := cmd.Output()
	if err != nil {
		tb.Fatalf("lzma compression failed: %v", err)
	}
	return out
}

func prepareTestData(b *testing.B, size int) (original []byte, compressed []byte) {
	b.Helper()
	var buf bytes.Buffer
	line := "The quick brown fox jumps over the lazy dog. "
	for buf.Len() < size {
		buf.WriteString(line)
	}
	original = buf.Bytes()[:size]
	compressed = compressLZMA(b, original)
	return
}

func prepareMixedData(b *testing.B, size int) (original []byte, compressed []byte) {
	b.Helper()
	// Less repetitive: mix of text, pseudo-random, and partial repeats
	src := make([]byte, size)
	state := uint32(0x12345678)
	phrases := []string{
		"The quick brown fox jumps over the lazy dog. ",
		"Lorem ipsum dolor sit amet, consectetur adipiscing elit. ",
		"Pack my box with five dozen liquor jugs. ",
		"How vexingly quick daft zebras jump! ",
	}
	pos := 0
	for pos < size {
		// Alternate between text and pseudo-random bytes
		if state%3 != 0 {
			p := phrases[int(state>>8)%len(phrases)]
			n := copy(src[pos:], p)
			pos += n
		} else {
			for j := 0; j < 32 && pos < size; j++ {
				state = state*1103515245 + 12345
				src[pos] = byte(state >> 16)
				pos++
			}
		}
		state = state*1103515245 + 12345
	}
	original = src
	compressed = compressLZMA(b, original)
	return
}

func BenchmarkGo(b *testing.B) {
	for _, size := range []int{1024, 64 * 1024, 1024 * 1024} {
		original, compressed := prepareTestData(b, size)
		b.Run(formatSize(size), func(b *testing.B) {
			var dec golzma.Decoder
			b.SetBytes(int64(len(original)))
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				r, err := golzma.NewReaderWithDecoder(bytes.NewReader(compressed), 0, &dec)
				if err != nil {
					b.Fatal(err)
				}
				n, err := io.Copy(io.Discard, r)
				if err != nil {
					b.Fatal(err)
				}
				if int(n) != len(original) {
					b.Fatalf("decoded %d bytes, want %d", n, len(original))
				}
			}
		})
	}
}

func BenchmarkGoMixed(b *testing.B) {
	original, compressed := prepareMixedData(b, 1024*1024)
	var dec golzma.Decoder
	b.SetBytes(int64(len(original)))
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		r, err := golzma.NewReaderWithDecoder(bytes.NewReader(compressed), 0, &dec)
		if err != nil {
			b.Fatal(err)
		}
		n, err := io.Copy(io.Discard, r)
		if err != nil {
			b.Fatal(err)
		}
		if int(n) != len(original) {
			b.Fatalf("decoded %d bytes, want %d", n, len(original))
		}
	}
}

func formatSize(n int) string {
	switch {
	case n >= 1024*1024:
		return itoa(n/(1024*1024)) + "MB"
	case n >= 1024:
		return itoa(n/1024) + "KB"
	default:
		return itoa(n) + "B"
	}
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	buf := [20]byte{}
	i := len(buf)
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	return string(buf[i:])
}
