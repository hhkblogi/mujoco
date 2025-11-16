#!/bin/bash
#
# Setup script to install git hooks for fork protection
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GIT_DIR="$(git rev-parse --git-dir 2>/dev/null)"

if [ -z "$GIT_DIR" ]; then
    echo "Error: Not in a git repository"
    exit 1
fi

HOOKS_DIR="$GIT_DIR/hooks"

echo "Installing git hooks for fork protection..."
echo ""

# Install pre-push hook
if [ -f "$HOOKS_DIR/pre-push" ] && [ ! -L "$HOOKS_DIR/pre-push" ]; then
    echo "Warning: pre-push hook already exists and is not a symlink."
    echo "Current hook: $HOOKS_DIR/pre-push"
    read -p "Do you want to back it up and replace it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        mv "$HOOKS_DIR/pre-push" "$HOOKS_DIR/pre-push.backup"
        echo "Backed up existing hook to $HOOKS_DIR/pre-push.backup"
    else
        echo "Skipping pre-push hook installation"
        exit 0
    fi
fi

# Create symlink
if [ -L "$HOOKS_DIR/pre-push" ]; then
    echo "Removing existing symlink..."
    rm "$HOOKS_DIR/pre-push"
fi

ln -s "../../hooks/pre-push" "$HOOKS_DIR/pre-push"
echo "✓ Installed pre-push hook (symlinked to hooks/pre-push)"
echo ""
echo "The hook will prevent accidental pushes to the upstream repository."
echo "To test it, try: git push upstream main"
echo ""
echo "Installation complete!"
