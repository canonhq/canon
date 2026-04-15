# Testing Extensions Locally

A hands-on guide to testing Canon's extension system end-to-end on your local machine.

## Prerequisites

```bash
# Install Canon from source (or ensure canonhq is installed)
uv sync --extra dev

# Verify the extension CLI is available
canon extension --help
```

## 1. Create a Test Extension

Scaffold a new extension with a skill and command:

```bash
canon extension create my-test-ext --skill --command --author "Your Name"
```

This creates:

```
my-test-ext/
├── canon-extension.yml    # Extension manifest
├── README.md
├── skills/
│   └── my-test-ext/
│       └── SKILL.md       # Skill template
└── commands/
    └── my-test-ext.md     # Command template
```

## 2. Validate the Extension

```bash
canon extension validate ./my-test-ext
```

Expected output:

```
Extension: My Test Ext (my-test-ext) v0.1.0
Provides: 1 skill(s), 1 command(s)
Validation passed.
```

Try breaking the manifest to see validation errors:

```bash
# Edit the manifest to reference a nonexistent file
# Then re-validate — it should report the missing file
```

## 3. Install in Dev Mode

Dev mode uses symlinks so edits propagate instantly:

```bash
canon extension add --dev ./my-test-ext
```

Expected output:

```
Installed extension 'my-test-ext' v0.1.0 (dev mode (symlinked))
  Placed 2 file(s):
    .canon/skills/my-test-ext/SKILL.md
    .claude/commands/my-test-ext.md
```

Verify the files are symlinks:

```bash
ls -la .canon/skills/my-test-ext/SKILL.md
# Should show -> /path/to/my-test-ext/skills/my-test-ext/SKILL.md

ls -la .claude/commands/my-test-ext.md
# Should show -> /path/to/my-test-ext/commands/my-test-ext.md
```

## 4. List Installed Extensions

```bash
canon extension list
```

Expected output:

```
  my-test-ext v0.1.0 [enabled] (dev) — 2 file(s)
    Source: /absolute/path/to/my-test-ext
```

## 5. Test Dev Mode Edit Propagation

Edit the source skill file:

```bash
echo "# UPDATED SKILL CONTENT" >> my-test-ext/skills/my-test-ext/SKILL.md
```

Verify the change is visible through the installed path:

```bash
tail -1 .canon/skills/my-test-ext/SKILL.md
# Should show: # UPDATED SKILL CONTENT
```

## 6. Remove the Extension

```bash
canon extension remove my-test-ext
```

Expected output:

```
Removed extension 'my-test-ext'
  Cleaned up 2 file(s)
```

Verify cleanup:

```bash
ls .canon/skills/my-test-ext 2>/dev/null && echo "STILL EXISTS" || echo "Cleaned up"
# Should show: Cleaned up

ls .claude/commands/my-test-ext.md 2>/dev/null && echo "STILL EXISTS" || echo "Cleaned up"
# Should show: Cleaned up
```

## 7. Test Normal Mode (Copy)

Install without `--dev` to test the copy path:

```bash
canon extension add ./my-test-ext
```

Verify files are copies (not symlinks):

```bash
ls -la .canon/skills/my-test-ext/SKILL.md
# Should NOT show a symlink arrow (->)
```

Clean up:

```bash
canon extension remove my-test-ext
```

## 8. Test the First-Party Extensions

### Sprint Planning Extension

```bash
canon extension add --dev extensions/canon-sprint-plan
canon extension validate extensions/canon-sprint-plan
canon extension list
canon extension remove canon-sprint-plan
```

### Slack Extension

```bash
canon extension add --dev extensions/canon-slack
canon extension validate extensions/canon-slack
canon extension list
canon extension remove canon-slack
```

## 9. Test Error Cases

### Duplicate Install

```bash
canon extension add --dev ./my-test-ext
canon extension add --dev ./my-test-ext  # Should fail: "already installed"
canon extension remove my-test-ext
```

### Invalid Manifest

```bash
mkdir bad-ext && echo "not valid yaml {{" > bad-ext/canon-extension.yml
canon extension validate ./bad-ext       # Should fail with YAML error
canon extension add ./bad-ext            # Should fail
rm -rf bad-ext
```

### Reserved Extension ID

```bash
mkdir /tmp/canon-ext && cat > /tmp/canon-ext/canon-extension.yml << 'EOF'
schema_version: "1"
extension:
  id: "canon"
  name: "Reserved"
  version: "0.1.0"
EOF
canon extension validate /tmp/canon-ext  # Should fail: "Reserved extension ID"
rm -rf /tmp/canon-ext
```

### Remove Non-Existent Extension

```bash
canon extension remove nonexistent      # Should fail: "not installed"
```

## 10. Run the Test Suite

```bash
# Extension system tests (manifest, registry, installer, template, facade)
uv run pytest tests/test_extensions/ -v

# Slack tests (verify facade bridge works)
uv run pytest tests/ -k "slack" -q

# Everything together
uv run pytest tests/test_extensions/ tests/test_slack_*.py -q
```

Expected: 306 tests passing, 0 failures.

## Cleanup

```bash
# Remove the test extension directory
rm -rf my-test-ext

# Remove any leftover .canon/extensions state
rm -rf .canon/extensions/.registry.json
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'canon'` | Not running via `uv run` | Use `uv run canon extension ...` |
| `Extension already installed` | Previous install wasn't cleaned up | `canon extension remove <id>` |
| `Extension registry is corrupted` | Interrupted install/uninstall | Delete `.canon/extensions/.registry.json` |
| Skill not showing in IDE | Extension not installed in current project | Run `canon extension add` from the project root |
| `FileExistsError` on install | Another extension uses the same skill/command name | Rename the conflicting component |
