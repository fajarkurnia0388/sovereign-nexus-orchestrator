from setuptools import find_packages, setup

setup(
    name="sno-orchestrator",
    version="2.0.0",
    packages=find_packages(),
    install_requires=[
        "mcp>=1.0.0,<2.0.0",
        "langgraph>=1.2.0,<2.0.0",
        "langgraph-checkpoint>=4.0.0",
        "langgraph-checkpoint-sqlite>=3.0.0",
        "aiosqlite>=0.19.0",
        "pydantic>=2.0.0,<3.0.0",
        "pydantic-settings>=2.0.0,<3.0.0",
        "pyyaml>=6.0",
        "llama-index-core>=0.10.0,<1.0.0",
        "qdrant-client>=1.7.0",
        "neo4j>=5.0.0",
        "networkx>=3.0",
        "redis>=5.0.0",
        "psycopg2-binary>=2.9.0",
        "httpx>=0.25.0",
        "streamlit>=1.35.0",
        "pandas>=2.0.0",
        "nest-asyncio>=1.6.0",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "sno=src.cli:main",
        ]
    },
)
