#!/bin/bash
# 故障注入：将 output/ 目录设为只读
chmod 444 "$PWD/output" 2>/dev/null || true
