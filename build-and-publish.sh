#!/bin/bash

# Build and publish UptimeSquirrel Agent to PyPI

set -e

echo "Building UptimeSquirrel Agent package..."

# Clean previous builds
rm -rf build/ dist/ *.egg-info

# Build the package
python3 -m build

echo "Build complete. Files in dist/:"
ls -la dist/

echo ""
echo "To upload to PyPI:"
echo "1. Test upload to TestPyPI first:"
echo "   python3 -m twine upload --repository testpypi dist/*"
echo ""
echo "2. Test installation from TestPyPI:"
echo "   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple uptimesquirrel-agent"
echo ""
echo "3. Upload to PyPI:"
echo "   python3 -m twine upload dist/*"
echo ""
echo "Note: You'll need to configure ~/.pypirc with your PyPI credentials"