// SPDX-License-Identifier: GPL-3.0-or-later
// Envoie la sélection (ou la page) à Scrinium par le lien scrinium://ajouter.
// Rien n'est enregistré sans validation : Scrinium affiche d'abord une fenêtre « Ajouter ».
const api = typeof browser !== "undefined" ? browser : chrome;
const MAX = 20000; // caractères : au-delà, certains systèmes refusent un lien trop long

function installer() {
  api.contextMenus.removeAll(() => {
    api.contextMenus.create({id: "selection", title: api.i18n.getMessage("menuSelection"), contexts: ["selection"]});
    api.contextMenus.create({id: "page", title: api.i18n.getMessage("menuPage"), contexts: ["page"]});
  });
}
api.runtime.onInstalled.addListener(installer);
if (api.runtime.onStartup) api.runtime.onStartup.addListener(installer);

api.contextMenus.onClicked.addListener((info, tab) => {
  const adresse = info.pageUrl || (tab && tab.url) || "";
  const brut = info.menuItemId === "selection" ? (info.selectionText || "") : "";
  const texte = (adresse + (brut ? "\n\n" + brut : "")).slice(0, MAX);
  const lien = "scrinium://ajouter?titre=" + encodeURIComponent((tab && tab.title) || adresse) +
               "&texte=" + encodeURIComponent(texte);
  if (tab && tab.id !== undefined) api.tabs.update(tab.id, {url: lien});
});
