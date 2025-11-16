#!/bin/bash
#
# Test script for the pre-push hook
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SCRIPT="$SCRIPT_DIR/pre-push"

echo "Testing pre-push hook..."
echo ""

# Test 1: Should block push to upstream (HTTPS)
echo "Test 1: Blocking push to upstream (HTTPS)..."
output=$("$HOOK_SCRIPT" "upstream" "https://github.com/google-deepmind/mujoco.git" 2>&1) && result=$? || result=$?
if [ $result -eq 1 ]; then
    echo "✓ PASS: Hook correctly blocked push to upstream HTTPS URL"
else
    echo "✗ FAIL: Hook should have blocked push to upstream"
    exit 1
fi

# Test 2: Should block push to upstream (SSH)
echo "Test 2: Blocking push to upstream (SSH)..."
output=$("$HOOK_SCRIPT" "upstream" "git@github.com:google-deepmind/mujoco.git" 2>&1) && result=$? || result=$?
if [ $result -eq 1 ]; then
    echo "✓ PASS: Hook correctly blocked push to upstream SSH URL"
else
    echo "✗ FAIL: Hook should have blocked push to upstream"
    exit 1
fi

# Test 3: Should allow push to fork
echo "Test 3: Allowing push to fork..."
output=$("$HOOK_SCRIPT" "origin" "https://github.com/hhkblogi/mujoco.git" 2>&1) && result=$? || result=$?
if [ $result -eq 0 ]; then
    echo "✓ PASS: Hook correctly allowed push to fork"
else
    echo "✗ FAIL: Hook should have allowed push to fork"
    exit 1
fi

# Test 4: Should allow push to other repositories
echo "Test 4: Allowing push to other repository..."
output=$("$HOOK_SCRIPT" "other" "https://github.com/someuser/someproject.git" 2>&1) && result=$? || result=$?
if [ $result -eq 0 ]; then
    echo "✓ PASS: Hook correctly allowed push to other repository"
else
    echo "✗ FAIL: Hook should have allowed push to other repository"
    exit 1
fi

echo ""
echo "All tests passed! ✓"
