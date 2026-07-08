#!/usr/bin/env python3
"""Rollback миграции <from> -> <to>. Аргумент: корень child-репозитория."""
import sys
def main(root):
    print("template rollback: nothing to do")
    return 0
if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
