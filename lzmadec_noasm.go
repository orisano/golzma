//go:build !arm64 && !amd64

package golzma

type cLzmaDec struct{}

func (d *decoder) tryDecodeAsm(limit int) (error, bool) {
	return nil, false
}
