package golzma

import (
	"bytes"
	"io"
	"os"
	"testing"
)

// 7z LZMA2 streams (from sevenzip's bcj/arm/ppc/sparc/complex testdata) that
// previously broke the arm64 asm decode path: the asm `copy_match_0` (RLE)
// wide STP loop overshot the start of the match by up to 15 bytes,
// corrupting just-decoded literals when match length mod 16 fell into the
// bad range. Now fixed; this test guards against regressions.
//
// Each case compares against the pure-Go reference output to catch silent
// data corruption (not just early ErrData).
func TestLZMA2_7zStreams_AsmBug(t *testing.T) {
	cases := []struct {
		file     string
		dictProp byte
		wantLen  int
	}{
		{"testdata/lzma2-prop03-1986.bin", 0x03, 8549},
		{"testdata/lzma2-packed-prop02-1891.bin", 0x02, 7704},
		{"testdata/lzma2-packed-prop04-1781.bin", 0x04, 12640},
		{"testdata/lzma2-packed-prop09-1874.bin", 0x09, 68340},
	}

	for _, tc := range cases {
		t.Run(tc.file, func(t *testing.T) {
			packed, err := os.ReadFile(tc.file)
			if err != nil {
				t.Fatal(err)
			}

			// Pure-Go reference decode.
			refR, err := NewLZMA2Reader(bytes.NewReader(packed), tc.dictProp, 0)
			if err != nil {
				t.Fatal(err)
			}
			refR.init()
			refR.dec.noAsm = true
			ref, err := io.ReadAll(refR)
			if err != nil {
				t.Fatalf("pure-Go ReadAll: %v (decoded %d bytes)", err, len(ref))
			}
			if len(ref) != tc.wantLen {
				t.Fatalf("pure-Go len = %d, want %d", len(ref), tc.wantLen)
			}

			// asm decode, must byte-for-byte match the pure-Go reference.
			r, err := NewLZMA2Reader(bytes.NewReader(packed), tc.dictProp, 0)
			if err != nil {
				t.Fatal(err)
			}
			r.init()
			r.dec.noAsm = false

			out, err := io.ReadAll(r)
			if err != nil {
				t.Fatalf("asm ReadAll: %v (decoded %d bytes)", err, len(out))
			}
			if len(out) != tc.wantLen {
				t.Fatalf("asm len = %d, want %d", len(out), tc.wantLen)
			}
			if !bytes.Equal(out, ref) {
				for i := range out {
					if out[i] != ref[i] {
						t.Fatalf("first asm/pure mismatch at byte %d: asm=0x%02x ref=0x%02x", i, out[i], ref[i])
					}
				}
			}
		})
	}
}
