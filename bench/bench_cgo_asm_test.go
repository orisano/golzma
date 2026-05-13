//go:build clzma && (arm64 || amd64)

package bench

import (
	"testing"
)

func BenchmarkCAsm(b *testing.B) {
	for _, size := range []int{1024, 64 * 1024, 1024 * 1024} {
		original, compressed := prepareTestData(b, size)
		props := compressed[:5]
		src := compressed[13:]

		dst := make([]byte, len(original))
		b.Run(formatSize(size), func(b *testing.B) {
			b.SetBytes(int64(len(original)))
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				n, err := CLzmaDecodeAsm(props, src, dst)
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

func BenchmarkCAsmMixed(b *testing.B) {
	original, compressed := prepareMixedData(b, 1024*1024)
	props := compressed[:5]
	src := compressed[13:]
	dst := make([]byte, len(original))
	b.SetBytes(int64(len(original)))
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		n, err := CLzmaDecodeAsm(props, src, dst)
		if err != nil {
			b.Fatal(err)
		}
		if n != len(original) {
			b.Fatalf("decoded %d bytes, want %d", n, len(original))
		}
	}
}
