# Next Steps for PyPI Publishing

✅ **Repository created and code pushed to GitHub!**

## 1. Set up GitHub Environments

Go to: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/settings/environments

### Create "testpypi" environment:
1. Click "New environment"
2. Name: `testpypi`
3. Add secret:
   - Name: `TEST_PYPI_API_TOKEN`
   - Value: Get from https://test.pypi.org/manage/account/token/
   - Token name suggestion: "uptimesquirrel-agent-github-actions"
   - Scope: Entire account (or specific to uptimesquirrel-agent if it exists)

### Create "pypi" environment:
1. Click "New environment"
2. Name: `pypi`
3. Add secret:
   - Name: `PYPI_API_TOKEN`
   - Value: Get from https://pypi.org/manage/account/token/
   - Token name suggestion: "uptimesquirrel-agent-github-actions"
   - Scope: Entire account (or specific to uptimesquirrel-agent if it exists)
4. Optional: Add protection rule (require approval)

## 2. Test Publishing to TestPyPI

1. Go to: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/actions
2. Click on "Publish to PyPI" workflow
3. Click "Run workflow"
4. Select:
   - Branch: main
   - Environment: testpypi
5. Click "Run workflow"

## 3. Verify TestPyPI Package

Once published to TestPyPI:

```bash
# Install from TestPyPI
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple uptimesquirrel-agent

# Test the command
uptimesquirrel-agent --version
```

## 4. Publish to Production PyPI

### Option A: Via GitHub Release (Recommended)
1. Go to: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/releases/new
2. Create new release:
   - Tag: `v1.2.7`
   - Title: `Release v1.2.7`
   - Description: Initial PyPI release
3. Publish release (this triggers automatic PyPI publish)

### Option B: Manual Workflow
1. Go to Actions → Publish to PyPI
2. Run workflow with environment: `pypi`

## 5. Verify Production Package

```bash
# Install from PyPI
pip install uptimesquirrel-agent

# Verify installation
uptimesquirrel-agent --version
```

## 6. Update Documentation

Once published, update:
- Main UptimeSquirrel README
- Website documentation
- Agent installation guides

## Quick Links

- GitHub Repo: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi
- GitHub Actions: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/actions
- TestPyPI: https://test.pypi.org/project/uptimesquirrel-agent/
- PyPI: https://pypi.org/project/uptimesquirrel-agent/

## Troubleshooting

If the workflow fails:
1. Check Actions tab for error logs
2. Verify API tokens are correctly set
3. Ensure package name is available on PyPI
4. Check that version number isn't already published