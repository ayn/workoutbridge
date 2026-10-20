"""Read a prescription from stdin, emit a draft to stdout, never publish."""

import json
import sys

from .parser import parse


def main() -> int:
    draft = parse(sys.stdin.read())
    json.dump(draft.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 2 if draft.unresolved else 0


if __name__ == "__main__":
    raise SystemExit(main())
