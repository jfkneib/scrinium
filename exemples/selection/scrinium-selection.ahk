; SPDX-License-Identifier: GPL-3.0-or-later
; Windows (AutoHotkey v2) : Ctrl+Alt+S envoie le texte sélectionné à Scrinium (fenêtre « Ajouter », rien n'est
; enregistré sans validation). Enregistrer ce fichier en .ahk et le lancer (ou le mettre dans le dossier Démarrage).
^!s:: {
    ancien := A_Clipboard
    A_Clipboard := ""
    Send "^c"
    if !ClipWait(1) {
        A_Clipboard := ancien
        return
    }
    texte := SubStr(A_Clipboard, 1, 6000)
    A_Clipboard := ancien
    Run "scrinium://ajouter?texte=" . UriEncode(texte)
}
UriEncode(s) {
    out := ""
    buf := Buffer(StrPut(s, "UTF-8"))
    StrPut(s, buf, "UTF-8")
    Loop buf.Size - 1 {
        c := NumGet(buf, A_Index - 1, "UChar")
        out .= (c >= 48 && c <= 57) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c = 45 || c = 46 || c = 95
            ? Chr(c) : Format("%{:02X}", c)
    }
    return out
}
