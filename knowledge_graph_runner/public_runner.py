from __future__ import annotations

# This carrier is PR-test-only. The main workflow's Notion sync job is disabled
# for pull_request events and this file intentionally performs no external work.

def main() -> None:
    print("PR_TEST_ONLY_NO_NOTION_SYNC")


if __name__ == "__main__":
    main()
