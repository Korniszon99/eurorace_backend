from django.core.management.base import BaseCommand

from eurorace.management.commands.sync_bulgaria_tasks import Command as SyncCommand


class Command(SyncCommand):
    help = "Alias: tworzy/aktualizuje zadania Wyścigu do Bułgarii (patrz sync_bulgaria_tasks)."
