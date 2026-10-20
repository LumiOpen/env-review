#!/bin/bash
cd /testbed
dev-switch go 1.24
go test -v -run 'TestJSONEncoding' .
