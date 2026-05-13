# golzma

Pure Go LZMA/LZMA2/7z decoder with assembly acceleration on ARM64 and AMD64.

## Install

```
go get github.com/orisano/golzma
```

## Usage

### LZMA (.lzma)

```go
import "github.com/orisano/golzma"

r, err := golzma.NewReader(compressedReader)
// read decompressed data from r
```

### LZMA2

```go
r := golzma.NewLZMA2Reader(compressedReader, dictProp)
// read decompressed data from r
```

### 7z

```go
import "github.com/orisano/golzma/sevenz"

a, err := sevenz.Open("archive.7z")
for _, e := range a.Entries {
    rc, err := a.OpenEntry(e)
    // read from rc
}
```

## Benchmark

The `bench/` directory contains benchmarks comparing the Go decoder against the 7z C implementation.

### Go-only benchmarks

Requires the `lzma` command for generating test data.

```
go test -bench=. ./bench/
```

### C implementation benchmarks

Requires the LZMA SDK C source in `./tmp/lzma/` (from the [LZMA SDK](https://7-zip.org/sdk.html)).

```
go test -tags clzma -bench=. ./bench/
```

### C implementation with assembly benchmarks

Additionally requires building the platform-specific assembly library into `/tmp/libLzmaDecOpt.a`.

For ARM64, build from `tmp/lzma/Asm/arm64/LzmaDecOpt.S`. For AMD64, use [asmc](https://github.com/nidud/asmc) to assemble `tmp/lzma/Asm/x86/LzmaDecOpt.asm`:

```
asmc64 -c -elf64 -DABI_LINUX -Fo/tmp/LzmaDecOpt.o tmp/lzma/Asm/x86/LzmaDecOpt.asm
ar rcs /tmp/libLzmaDecOpt.a /tmp/LzmaDecOpt.o
go test -tags clzma -bench=. ./bench/
```

## Acknowledgements

The assembly generators (`goasm_arm64.py`, `goasm_amd64.py`) are inspired by [s_xbyak](https://github.com/herumi/s_xbyak) by @herumi.

The LZMA decode loop is ported from [LZMA SDK](https://7-zip.org/sdk.html) by Igor Pavlov (public domain).

## License

MIT
