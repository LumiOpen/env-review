cd /testbed
mkdir -p /tmp/gopath/src/github.com/fatih
ln -sf /testbed /tmp/gopath/src/github.com/fatih/gomodifytags
GO111MODULE=off GOPATH=/tmp/gopath go test -v github.com/fatih/gomodifytags
