#!/bin/bash
PORT="${1:-8765}"
curl -s -m 2 "http://127.0.0.1:${PORT}/health" 2>/dev/null
