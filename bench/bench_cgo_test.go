//go:build clzma

package bench

import (
	"testing"
)

func BenchmarkCMixed(b *testing.B) {
	original, compressed := prepareMixedData(b, 1024*1024)
	props := compressed[:5]
	src := compressed[13:]
	dst := make([]byte, len(original))
	b.SetBytes(int64(len(original)))
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		n, err := CLzmaDecode(props, src, dst)
		if err != nil {
			b.Fatal(err)
		}
		if n != len(original) {
			b.Fatalf("decoded %d bytes, want %d", n, len(original))
		}
	}
}

func BenchmarkC(b *testing.B) {
	for _, size := range []int{1024, 64 * 1024, 1024 * 1024} {
		original, compressed := prepareTestData(b, size)
		props := compressed[:5]
		src := compressed[13:] // skip 5 props + 8 size

		dst := make([]byte, len(original))
		b.Run(formatSize(size), func(b *testing.B) {
			b.SetBytes(int64(len(original)))
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				n, err := CLzmaDecode(props, src, dst)
				if err != nil {
					b.Fatal(err)
				}
				if n != len(original) {
					b.Fatalf("decoded %d bytes, want %d", n, len(original))
				}
			}
		})
	}
}

