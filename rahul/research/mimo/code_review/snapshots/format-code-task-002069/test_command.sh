#!/bin/bash
cd /testbed
bash -lc 'python -m pytest pytago/tests/test_core.py::Test::test_bitwisenot -v'
