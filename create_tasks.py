#!/usr/bin/env python
"""Wygodny wrapper: python create_tasks.py [--replace-all] [--dry-run]"""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from django.core.management import call_command


if __name__ == "__main__":
    call_command("sync_bulgaria_tasks", *sys.argv[1:])
