# Git Hooks for Fork Protection

This directory contains git hooks to help prevent accidental pushes to the upstream repository.

## Pre-Push Hook

The `pre-push` hook prevents accidental pushes to the upstream `google-deepmind/mujoco` repository. This is useful for forks to ensure that commits are not accidentally pushed directly to upstream.

### Installation

You have two options to install the hook:

#### Option 1: Symlink (Recommended)

Create a symbolic link from your `.git/hooks` directory to the hook in this directory:

```bash
ln -s ../../hooks/pre-push .git/hooks/pre-push
```

This way, any updates to the hook will automatically be reflected.

#### Option 2: Copy

Copy the hook file to your `.git/hooks` directory:

```bash
cp hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

### How It Works

The pre-push hook checks the URL of the remote you're pushing to. If it matches the upstream repository pattern (`github.com/google-deepmind/mujoco`), the push is blocked with an informative error message.

### Testing the Hook

To verify the hook is working:

1. Install the hook using one of the methods above
2. Try to push to upstream (after adding it as a remote):
   ```bash
   git remote add upstream https://github.com/google-deepmind/mujoco
   git push upstream main
   ```
   This should be blocked by the hook.

3. Push to your fork should work normally:
   ```bash
   git push origin main
   ```

### Bypassing the Hook (Not Recommended)

If you absolutely need to bypass the hook, you can use:

```bash
git push --no-verify
```

**Warning:** This defeats the purpose of the hook and may result in accidental pushes to upstream.

### Customization

If you fork from a different upstream repository, you can edit the `UPSTREAM_PATTERNS` variable in the `pre-push` script to match your upstream repository URL.
