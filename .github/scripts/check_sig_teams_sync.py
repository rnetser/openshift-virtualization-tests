#!/usr/bin/env python3
# Generated with Claude Code

"""
Check that all users in tests/*/OWNERS files are present in SIG_TEAMS.
Exits with error if users are missing, outputs details for GitHub Actions.
"""

import sys
from pathlib import Path

import yaml
from simple_logger.logger import get_logger

LOGGER = get_logger(name="sig-teams-sync")


# SIG folder to SIG_TEAMS key mapping
# Some folders belong to parent SIGs
SIG_FOLDER_MAPPING = {
    "chaos": "chaos_scale",
    "scale": "chaos_scale",
    "data_protection": "storage",
    "observability": "install_upgrade_operators",
    "infrastructure": "infrastructure",
    "install_upgrade_operators": "install_upgrade_operators",
    "network": "network",
    "storage": "storage",
    "virt": "virt",
}


def load_sig_teams(sig_teams_path: Path) -> dict[str, set[str]]:
    """Load SIG_TEAMS file and return dict of sig -> set of users."""
    with open(sig_teams_path) as f:
        data = yaml.safe_load(f)

    sig_users = {}
    for sig, config in data.items():
        users = set()
        if isinstance(config, dict):
            for role in ["approvers", "reviewers"]:
                if role in config and config[role]:
                    users.update(config[role])
        elif isinstance(config, list):
            # Simple list format
            users.update(config)
        sig_users[sig] = users

    return sig_users


def load_owners_files(tests_dir: Path) -> dict[str, set[str]]:
    """Load top-level OWNERS files from tests/ and return dict of folder -> set of users."""
    owners_users: dict[str, set[str]] = {}

    # Only check direct subdirectories of tests/ (not nested)
    for subdir in tests_dir.iterdir():
        if not subdir.is_dir():
            continue

        owners_file = subdir / "OWNERS"
        if not owners_file.exists():
            continue

        folder_name = subdir.name

        with open(owners_file) as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError:
                LOGGER.warning(f"Could not parse {owners_file}")
                continue

        if not data:
            continue

        users = set()
        for role in ["approvers", "reviewers"]:
            if role in data and data[role]:
                users.update(data[role])

        if folder_name not in owners_users:
            owners_users[folder_name] = set()
        owners_users[folder_name].update(users)

    return owners_users


def main() -> int:
    repo_root = Path(__file__).parent.parent.parent  # noqa: FCN001
    sig_teams_path = repo_root / "SIG_TEAMS"
    tests_dir = repo_root / "tests"

    if not sig_teams_path.exists():
        LOGGER.error("SIG_TEAMS file not found at repository root")
        return 1

    if not tests_dir.exists():
        LOGGER.error("tests/ directory not found")
        return 1

    # Load both sources
    sig_teams = load_sig_teams(sig_teams_path=sig_teams_path)
    owners_users = load_owners_files(tests_dir=tests_dir)

    # Find missing users
    missing = {}
    for sig_folder, users in owners_users.items():
        # Get the mapped SIG team name
        sig_team = SIG_FOLDER_MAPPING.get(sig_folder)

        if sig_team is None:
            # Unknown folder, warn but don't fail
            LOGGER.warning(f"Unknown SIG folder '{sig_folder}', no mapping defined")
            continue

        if sig_team not in sig_teams:
            missing[sig_folder] = {"sig_missing": True, "users": users, "expected_sig": sig_team}
        else:
            missing_users = users - sig_teams[sig_team]
            if missing_users:
                missing[sig_folder] = {"sig_missing": False, "users": missing_users, "expected_sig": sig_team}

    if missing:
        LOGGER.error("SIG_TEAMS is out of sync with OWNERS files")
        LOGGER.error("The following users were found in OWNERS files but are missing from SIG_TEAMS:")

        for sig_folder, info in sorted(missing.items()):
            sig_team_name: str = str(info["expected_sig"])
            user_list: set[str] = info["users"]  # type: ignore[assignment]
            users_str = ", ".join(sorted(user_list))
            if info["sig_missing"]:
                LOGGER.error(f"  - Folder: tests/{sig_folder}/OWNERS")
                LOGGER.error(f"    SIG team '{sig_team_name}' not found in SIG_TEAMS")
                LOGGER.error(f"    Users to add: {users_str}")
            else:
                LOGGER.error(f"  - Folder: tests/{sig_folder}/OWNERS")
                LOGGER.error(f"    SIG team: {sig_team_name}")
                LOGGER.error(f"    Missing users: {users_str}")
            LOGGER.error("")

        LOGGER.error("HOW TO FIX:")
        LOGGER.error("1. Open the SIG_TEAMS file in the repository root")
        LOGGER.error("2. Find the appropriate SIG section (listed above)")
        LOGGER.error("3. Add the missing users to that section")
        return 1

    LOGGER.info("All users in OWNERS files are present in SIG_TEAMS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
