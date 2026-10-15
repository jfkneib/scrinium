"""Example Scrinium extension. Copy this folder to <data folder>/plugins/ and enable it in Extensions > Manage extensions."""
from scrinium.core.plugins import Plugin


class HelloPlugin(Plugin):
    api = 1   # API version this extension targets

    def activer(self, ctx):
        self.ctx = ctx
        self.ouvertes = ctx.reglages.get("ouvertes", 0)
        ctx.on("fiche_ouverte", self.on_ouverte)          # events: see docs/plugins.md
        if ctx.ui is not None:                            # None when running without a window
            ctx.ui.ajouter_action("Count my notes", self.compter, "view-pim-notes")
            ctx.ui.ajouter_bouton("Count", self.compter)

    def desactiver(self):
        pass   # menu entries, buttons, panels and timers added through ctx.ui are removed automatically

    def compter(self):
        nb = len(self.ctx.fiches())
        self.ctx.ui.notifier("Hello", f"{nb} notes in {len(self.ctx.themes())} topics. Opened so far: {self.ouvertes}.")

    def on_ouverte(self, fiche):
        self.ouvertes += 1
        self.ctx.reglages.set("ouvertes", self.ouvertes)    # per-extension settings, saved in settings.json
