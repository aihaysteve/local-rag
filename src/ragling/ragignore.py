"""Ragignore template management.

Generates and manages ~/.ragling/ragignore files for user-configurable
exclusion patterns during indexing.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

RAGIGNORE_TEMPLATE = """\
# Ragling ignore file — .gitignore syntax
# Patterns here exclude files/directories from indexing.
# This file is loaded globally; per-directory .ragignore files
# are also supported for finer-grained control.
#
# See also: ~/.ragling/ragignore.default for upstream defaults.

# Large generated/vendored directories
node_modules/
vendor/
dist/
build/

# Virtual environments
.venv/
.env/
venv/
env/

# IDE/editor files
.idea/
.vscode/
*.swp
*.swo
*~

# OS files
.DS_Store
Thumbs.db

# Lock files
package-lock.json
yarn.lock
pnpm-lock.yaml
Cargo.lock
poetry.lock
uv.lock
go.sum

# Build artifacts
__pycache__/
*.pyc
*.pyo
.mypy_cache/
.pytest_cache/
.tox/
*.egg-info/
cdk.out/
.terraform/
"""


def ensure_ragignore(config_dir: Path) -> None:
    """Ensure ragignore files exist in the config directory.

    Creates ~/.ragling/ragignore from template if it doesn't exist.
    Always writes/updates ~/.ragling/ragignore.default as reference.

    Args:
        config_dir: The ragling config directory (e.g. ~/.ragling).
    """
    config_dir.mkdir(parents=True, exist_ok=True)

    user_file = config_dir / "ragignore"
    default_file = config_dir / "ragignore.default"

    # Always update the reference copy
    default_file.write_text(RAGIGNORE_TEMPLATE)

    # Only create user file if it doesn't exist
    if not user_file.exists():
        user_file.write_text(RAGIGNORE_TEMPLATE)
        logger.info("Created %s", user_file)
