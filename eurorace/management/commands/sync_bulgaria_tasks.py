from django.core.management.base import BaseCommand

from eurorace.task_models import Task


BULGARIA_RACE_TASKS = [
    {
        "title": "[BONUS: -25 MIN] Rymowanka o autostopowaniu",
        "description": (
            "Napisz co najmniej 8-wersową rymowankę o autostopowaniu i zaśpiewajcie ją na filmie. "
            "Dowód: nagranie wideo. "
            "Maks. łączna bonifikata na mecie: 5 godzin."
        ),
    },
    {
        "title": "[BONUS: -15 MIN] Recenzja zagranicznego trunku",
        "description": (
            "Nagraj recenzję zagranicznego trunku w stylu vloga – dowolny procent. "
            "Dowód: nagranie wideo."
        ),
    },
    {
        "title": "[BONUS: -20 MIN] Polska piosenka z kierowcą",
        "description": (
            "Zaśpiewaj polską piosenkę (co najmniej refren) wspólnie ze swoim zagranicznym kierowcą. "
            "Dowód: nagranie wideo."
        ),
    },
    {
        "title": "[BONUS: -35 MIN] Poprowadź samochód kierowcy",
        "description": (
            "Poprowadź samochód swojego kierowcy – wystarczy manewr lub 5 metrów na parkingu. "
            "Dowód: nagranie wideo."
        ),
    },
    {
        "title": "[BONUS: -20 MIN] Umyj samochód kierowcy",
        "description": (
            "Umyj samochód swojego kierowcy – np. przednią szybę lub całe auto na stacji. "
            "Dowód: nagranie wideo lub zdjęcie."
        ),
    },
    {
        "title": "[BONUS: -15 MIN] Wspólny posiłek z kierowcą",
        "description": (
            "Zjedz wspólny posiłek ze swoim kierowcą. "
            "Dowód: zdjęcie lub nagranie wideo."
        ),
    },
    {
        "title": "[BONUS: -20 MIN] Złap na stopa TIR-a",
        "description": "Złap na stopa TIR-a. Dowód: zdjęcie ze środka kabiny.",
    },
    {
        "title": "[BONUS: -45 MIN] Odwiedź 5 różnych państw",
        "description": (
            "Szybciej nie znaczy lepiej: odwiedź w trasie co najmniej 5 różnych państw. "
            "Dowód: zdjęcia lub zrzuty ekranu z lokalizacją GPS z każdego państwa."
        ),
    },
    {
        "title": "[BONUS: -45 MIN] Wymiana bezwartościowej rzeczy",
        "description": (
            "Wymień w trakcie trasy bezwartościową rzecz na przedmiot warty co najmniej 10 zł. "
            "Dowód: zdobyty przedmiot do okazania na mecie."
        ),
    },
    {
        "title": "[BONUS: -15 MIN] Łamaniec językowy kierowcy",
        "description": (
            "Naucz się łamańca językowego w języku swojego kierowcy i nagraj próbę jego wymówienia. "
            "Dowód: nagranie wideo."
        ),
    },
    {
        "title": "[BONUS: -20 MIN] Zamiana kierowcami z inną parą",
        "description": (
            "Zamieńcie się na trasie kierowcami/autami z inną parą uczestników wyścigu. "
            "Dowód: zdjęcie."
        ),
    },
    {
        "title": "[BONUS: -15 MIN] Najbardziej absurdalna rzecz z trasy",
        "description": (
            "Przywieź na metę najbardziej losową i absurdalną rzecz znalezioną na trasie – "
            "nie może to być przedmiot z zadania o wymianie. "
            "Dowód: fizyczny przedmiot do weryfikacji."
        ),
    },
    {
        "title": "[BONUS: -10 MIN] Spytaj o drogę i idź w przeciwną",
        "description": (
            "Spytaj kogoś na ulicy lub stacji o drogę, a zaraz po uzyskaniu odpowiedzi "
            "odejdź w kompletnie przeciwnym kierunku. Dowód: nagranie wideo."
        ),
    },
    {
        "title": "[BONUS: -30 MIN] 4 różne środki transportu",
        "description": (
            "Wykorzystaj w trakcie podróży co najmniej 4 różne środki transportu. "
            "Dowód: zdjęcia lub nagrania z każdego środka lokomocji."
        ),
    },
    {
        "title": "[BONUS: -40 MIN] Stop w każdym odwiedzonym państwie",
        "description": (
            "Złap stopa w każdym z odwiedzonych państw z osobna. "
            "Dowód: zdjęcie z łapania lub z auta w każdym kraju."
        ),
    },
    {
        "title": "[BONUS: -10 MIN] 3 ciekawostki o państwach",
        "description": (
            "Opowiedz na mecie 3 ciekawostki o państwach, przez które przejechaliście, "
            "o których kadra nie miała pojęcia. Dowód: weryfikacja ustna na mecie."
        ),
    },
    {
        "title": "[BONUS: -30 MIN] Lokalny produkt z każdego kraju",
        "description": (
            "Przywieź lokalny produkt spożywczy z każdego odwiedzonego po drodze kraju. "
            "Dowód: fizyczne produkty do okazania na mecie."
        ),
    },
    {
        "title": "[BONUS: -20 MIN] Poznaj rodzinę kierowcy",
        "description": (
            "Zapoznaj się z rodziną swojego kierowcy – na żywo lub przez wideorozmowę. "
            "Dowód: nagranie wideo lub zdjęcie podczas rozmowy."
        ),
    },
    {
        "title": "[BONUS: -30 MIN] Zakupy w niesieciowym sklepie",
        "description": (
            "Zrób zakupy w lokalnym, niesieciowym sklepie. "
            "Dowód: zdjęcie ze sklepu lub paragon."
        ),
    },
    {
        "title": "[BONUS: -60 MIN] Matura z matematyki (Rumunia)",
        "description": (
            "Rozwiąż odręcznie na papierze arkusz matury podstawowej z matematyki z Rumunii – "
            "dopuszczalne same obliczenia i odpowiedzi. "
            "Dowód: zapisany papier z rozwiązaniami do oddania na mecie."
        ),
    },
]


class Command(BaseCommand):
    help = (
        "Synchronizuje zadania Eurorace – Wyścig do Bułgarii. "
        "Zadania bez stałej lokalizacji; pinezki powstają z GPS uploadu dowodu."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--replace-all",
            action="store_true",
            help="Usuwa istniejące zadania przed utworzeniem listy Bułgaria.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tylko wypisz plan, bez zapisu do bazy.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        replace_all = options["replace_all"]

        if replace_all:
            existing = Task.objects.count()
            self.stdout.write(f"Usuwanie {existing} istniejących zadań...")
            if not dry_run:
                Task.objects.all().delete()

        created = 0
        updated = 0
        for item in BULGARIA_RACE_TASKS:
            title = item["title"]
            description = item["description"]
            task = Task.objects.filter(title=title).first()
            if task is None:
                self.stdout.write(f"CREATE: {title}")
                if not dry_run:
                    Task.objects.create(
                        title=title,
                        description=description,
                        location=None,
                    )
                created += 1
            else:
                self.stdout.write(f"UPDATE: {title}")
                if not dry_run:
                    task.description = description
                    task.location = None
                    task.save(update_fields=["description", "location", "updated_at"])
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Gotowe. created={created} updated={updated} dry_run={dry_run}"
            )
        )
