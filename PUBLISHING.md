# Publishing UptimeSquirrel Agent to PyPI

## Prerequisites

1. Create accounts on:
   - [PyPI](https://pypi.org/account/register/)
   - [TestPyPI](https://test.pypi.org/account/register/)

2. Install required tools:
   ```bash
   pip install build twine
   ```

3. Configure PyPI credentials in `~/.pypirc`:
   ```ini
   [distutils]
   index-servers =
       pypi
       testpypi

   [pypi]
   username = __token__
   password = pypi-YOUR-API-TOKEN-HERE

   [testpypi]
   username = __token__
   password = pypi-YOUR-TEST-API-TOKEN-HERE
   ```

## Publishing Process

### 1. Update Version

Edit `uptimesquirrel_agent/__init__.py` and `setup.py` to update the version number.

### 2. Build the Package

```bash
./build-and-publish.sh
```

This will create wheel and source distributions in the `dist/` directory.

### 3. Test on TestPyPI

Upload to TestPyPI first:
```bash
python3 -m twine upload --repository testpypi dist/*
```

Test installation:
```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple uptimesquirrel-agent
```

### 4. Publish to PyPI

Once tested, publish to the real PyPI:
```bash
python3 -m twine upload dist/*
```

### 5. Verify Installation

```bash
pip install uptimesquirrel-agent
```

## Automated Publishing (GitHub Actions)

Create `.github/workflows/publish.yml`:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.9'
    - name: Install dependencies
      run: |
        pip install build twine
    - name: Build package
      run: python -m build
    - name: Publish to PyPI
      env:
        TWINE_USERNAME: __token__
        TWINE_PASSWORD: ${{ secrets.PYPI_API_TOKEN }}
      run: |
        twine upload dist/*
```

Add your PyPI API token as a GitHub secret named `PYPI_API_TOKEN`.

## Version Management

Follow semantic versioning:
- MAJOR.MINOR.PATCH (e.g., 1.2.7)
- MAJOR: Breaking changes
- MINOR: New features, backward compatible
- PATCH: Bug fixes

## Checklist Before Publishing

- [ ] Update version number
- [ ] Update CHANGELOG
- [ ] Test locally
- [ ] Build package
- [ ] Upload to TestPyPI
- [ ] Test installation from TestPyPI
- [ ] Upload to PyPI
- [ ] Create GitHub release
- [ ] Update documentation