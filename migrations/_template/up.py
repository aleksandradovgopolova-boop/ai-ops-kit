#!/usr/bin/env python3
"""Миграция <from> -> <to>: <что делает>. Аргумент: корень child-репозитория."""
import sys
def main(root):
    # идемпотентные преобразования файлов child
    print("template migration: nothing to do")
    return 0
if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
