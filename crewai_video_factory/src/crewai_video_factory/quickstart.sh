#!/bin/bash
# 🎬 Quick Start Video Factory

echo "🎬 CrewAI Video Factory"
echo "======================="
echo ""

# Check if custom input is provided
if [ -z "$1" ]; then
    echo "Using default inputs..."
    python run.py
else
    echo "Using custom inputs: $1"
    python run.py "$1"
fi
