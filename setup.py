import setuptools
import os

# Read the long description from README
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Read the version from the agent file
version = "1.2.7"

setuptools.setup(
    name="uptimesquirrel-agent",
    version=version,
    author="UptimeSquirrel",
    author_email="support@uptimesquirrel.com",
    description="System monitoring agent for UptimeSquirrel",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/uptimesquirrel/agent",
    project_urls={
        "Bug Tracker": "https://github.com/uptimesquirrel/agent/issues",
        "Documentation": "https://docs.uptimesquirrel.com/agent",
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Monitoring",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: POSIX :: Linux",
    ],
    packages=["uptimesquirrel_agent"],
    python_requires=">=3.7",
    install_requires=[
        "psutil>=5.8.0",
        "requests>=2.25.0",
        "configparser>=5.0.0",
    ],
    extras_require={
        "snmp": ["pysnmp>=4.4.12"],
    },
    entry_points={
        "console_scripts": [
            "uptimesquirrel-agent=uptimesquirrel_agent.agent:main",
        ],
    },
    include_package_data=True,
    package_data={
        "uptimesquirrel_agent": ["config/*", "systemd/*"],
    },
)