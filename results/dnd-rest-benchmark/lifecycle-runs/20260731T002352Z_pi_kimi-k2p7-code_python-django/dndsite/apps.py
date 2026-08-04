from django.apps import AppConfig


class DndsiteConfig(AppConfig):
    name = "dndsite"
    verbose_name = "D&D Site"

    def ready(self):
        from . import db

        db.init_db()
