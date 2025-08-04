#!/bin/bash

# Script to set up GitHub repository for uptimesquirrel-agent-pypi

echo "=== GitHub Repository Setup for UptimeSquirrel Agent PyPI ==="
echo ""
echo "This script will help you set up the GitHub repository for PyPI publishing."
echo ""

# Check if we're in the right directory
if [ ! -f "setup.py" ]; then
    echo "❌ Error: setup.py not found. Please run this from the uptimesquirrel-agent-pypi directory."
    exit 1
fi

echo "📋 Steps to complete:"
echo ""
echo "1. Create GitHub Repository:"
echo "   - Go to: https://github.com/new"
echo "   - Repository name: uptimesquirrel-agent-pypi"
echo "   - Description: Official PyPI package for UptimeSquirrel monitoring agent"
echo "   - Make it PUBLIC (required for PyPI)"
echo "   - Do NOT initialize with README (we have one)"
echo ""
read -p "Press Enter when you've created the repository..."

echo ""
echo "2. Initialize Git and push to GitHub:"
echo ""

# Initialize git if not already done
if [ ! -d ".git" ]; then
    echo "Initializing git repository..."
    git init
    git add .
    git commit -m "Initial commit: UptimeSquirrel Agent PyPI package v1.2.7"
else
    echo "Git repository already initialized."
fi

echo ""
echo "3. Add GitHub remote and push:"
echo "   Run these commands:"
echo ""
echo "   git remote add origin https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi.git"
echo "   git branch -M main"
echo "   git push -u origin main"
echo ""
read -p "Press Enter after you've pushed to GitHub..."

echo ""
echo "4. Set up GitHub Environments:"
echo "   Go to: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/settings/environments"
echo ""
echo "   Create TWO environments:"
echo ""
echo "   a) Environment name: testpypi"
echo "      - Add secret: TEST_PYPI_API_TOKEN"
echo "      - Get token from: https://test.pypi.org/manage/account/token/"
echo ""
echo "   b) Environment name: pypi"
echo "      - Add secret: PYPI_API_TOKEN"
echo "      - Get token from: https://pypi.org/manage/account/token/"
echo "      - Add protection rule: Require approval (optional but recommended)"
echo ""
read -p "Press Enter when you've set up the environments..."

echo ""
echo "5. Test the GitHub Actions workflow:"
echo "   Go to: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/actions"
echo "   - Click on 'Publish to PyPI' workflow"
echo "   - Click 'Run workflow'"
echo "   - Select 'testpypi' as the environment"
echo "   - This will test the publishing process to TestPyPI"
echo ""
read -p "Press Enter when ready to continue..."

echo ""
echo "✅ Setup Complete!"
echo ""
echo "Next steps:"
echo "1. Test publish to TestPyPI using GitHub Actions"
echo "2. Install from TestPyPI to verify: pip install -i https://test.pypi.org/simple/ uptimesquirrel-agent"
echo "3. When ready, create a GitHub release to trigger production PyPI publish"
echo ""
echo "Creating a release:"
echo "   - Go to: https://github.com/Scripted-Ventures-NZ/uptimesquirrel-agent-pypi/releases/new"
echo "   - Tag: v1.2.7"
echo "   - Title: Release v1.2.7"
echo "   - This will automatically publish to PyPI"
echo ""