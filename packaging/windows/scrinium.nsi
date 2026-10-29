; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 Jean-François Kneib
;
; ==================================================================================================================
; INSTALLATEUR WINDOWS DE SCRINIUM (script NSIS)
; ==================================================================================================================
; À quoi ça sert
;   Le dossier produit par PyInstaller (dist\scrinium\) contient scrinium.exe et ses fichiers. Un utilisateur ne veut
;   pas « extraire une archive et chercher le bon .exe » : il veut UN fichier Scrinium-X.Y.Z-setup.exe sur lequel il
;   double-clique, comme pour n'importe quel programme. C'est ce que fabrique ce script avec NSIS.
;
; Ce que fait l'installateur, étape par étape
;   1. Il pose des questions (licence, dossier d'installation) dans des fenêtres standard de Windows.
;   2. Il copie le dossier dist\scrinium\ dans le dossier d'installation.
;   3. Il crée un raccourci dans le menu Démarrer (et, si on le demande, sur le bureau).
;   4. Il s'inscrit dans « Paramètres > Applications » de Windows : c'est ce qui permet de le désinstaller
;      proprement, et qui affiche son nom, sa version et sa taille.
;   5. Il écrit un petit programme de désinstallation (uninstall.exe) que Windows sait appeler.
;
; Choix important : installation « pour l'utilisateur » (sans droits administrateur)
;   Le programme va dans  %LOCALAPPDATA%\Programs\Scrinium  et les inscriptions se font dans HKEY_CURRENT_USER.
;   Avantage : aucune fenêtre « Voulez-vous autoriser cette application à apporter des modifications ? », aucun mot de
;   passe administrateur, et on ne peut rien casser dans le reste du système. C'est ce que font VS Code, Discord, etc.
;   Inconvénient : l'installation ne concerne que l'utilisateur qui l'a faite (pas tous les comptes de l'ordinateur).
;
; Les fiches de l'utilisateur ne sont JAMAIS touchées par l'installation, la mise à jour ni la désinstallation : elles
; vivent dans %APPDATA%\scrinium, un autre dossier que le programme.
;
; Comment le fabriquer (sur une machine Windows ; c'est ce que fait .github\workflows\windows.yml) :
;     makensis /DVERSION=0.4.0 packaging\windows\scrinium.nsi
; Résultat : packaging\windows\Scrinium-0.4.0-setup.exe
;
; Lecture du script : les lignes qui commencent par ; sont des commentaires. « !define » crée une constante,
; « Section » est un bloc d'actions, « $INSTDIR » est le dossier choisi pour l'installation, « $SMPROGRAMS » le menu
; Démarrer, « $DESKTOP » le bureau. Ces noms avec $ sont fournis par NSIS.
; ==================================================================================================================

Unicode true                                  ; noms accentués corrects (Jean-François, Éteindre…)

; --- Constantes -----------------------------------------------------------------------------------------------------
!ifndef VERSION
  !define VERSION "0.0.0"                     ; normalement donnée par la ligne de commande : /DVERSION=0.4.0
!endif
!define NOM         "Scrinium"
!define EDITEUR     "Jean-François Kneib"
!define SITE        "https://github.com/jfkneib/scrinium"
; Dossier produit par PyInstaller, relatif à CE fichier (packaging\windows\) : on remonte à la racine du dépôt.
!define DOSSIER_PROGRAMME "..\..\dist\scrinium"
; Clé du registre où Windows range la liste des « Applications installées » (pour l'utilisateur courant).
!define CLE_DESINSTALL "Software\Microsoft\Windows\CurrentVersion\Uninstall\${NOM}"
; Clé du registre où Scrinium (case « Lancer au démarrage ») inscrit son démarrage automatique : voir core\autostart.py.
!define CLE_DEMARRAGE "Software\Microsoft\Windows\CurrentVersion\Run"

; --- Réglages généraux ----------------------------------------------------------------------------------------------
Name "${NOM} ${VERSION}"                      ; titre des fenêtres
OutFile "Scrinium-${VERSION}-setup.exe"       ; le fichier fabriqué
InstallDir "$LOCALAPPDATA\Programs\${NOM}"    ; dossier proposé par défaut (modifiable par l'utilisateur)
InstallDirRegKey HKCU "Software\${NOM}" "Dossier"   ; si Scrinium est déjà installé, on propose le même dossier (mise à jour)
RequestExecutionLevel user                    ; « user » = sans droits administrateur (voir plus haut)
SetCompressor /SOLID lzma                     ; compression maximale : le setup est bien plus petit que le dossier
BrandingText "${NOM} ${VERSION}"

; --- Fenêtres de l'installateur (Modern UI, le style standard de NSIS) ----------------------------------------------
!include "MUI2.nsh"
; Outil NSIS pour calculer la taille d'un dossier (affichée dans « Applications installées »).
!include "FileFunc.nsh"
!insertmacro GetSize

!define MUI_ABORTWARNING                      ; demande confirmation si on ferme l'installateur en cours de route
; Icône du setup : fabriquée par faire_icone.py ; si elle manque, NSIS utilise son icône par défaut (sinon la
; construction s'arrêterait sur une erreur).
!if /FileExists "scrinium.ico"
  !define MUI_ICON   "scrinium.ico"
  !define MUI_UNICON "scrinium.ico"
!endif

!insertmacro MUI_PAGE_WELCOME                 ; « Bienvenue dans l'assistant d'installation »
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE" ; la licence GPL (texte du fichier LICENSE du dépôt)
!insertmacro MUI_PAGE_DIRECTORY               ; choix du dossier
!insertmacro MUI_PAGE_COMPONENTS              ; case « raccourci sur le bureau »
!insertmacro MUI_PAGE_INSTFILES               ; la barre de progression
; Dernière page : proposer de lancer Scrinium tout de suite
!define MUI_FINISHPAGE_RUN "$INSTDIR\scrinium.exe"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM               ; pages du désinstalleur
!insertmacro MUI_UNPAGE_INSTFILES

; Langues : la première est celle proposée si la langue de Windows n'est ni l'une ni l'autre.
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "English"

; Textes qui dépendent de la langue (LangString) : un par langue, choisi automatiquement selon Windows.
LangString TXT_PROGRAMME ${LANG_FRENCH}  "Scrinium (obligatoire)"
LangString TXT_PROGRAMME ${LANG_ENGLISH} "Scrinium (required)"
LangString TXT_BUREAU    ${LANG_FRENCH}  "Raccourci sur le bureau"
LangString TXT_BUREAU    ${LANG_ENGLISH} "Desktop shortcut"
LangString TXT_FERME     ${LANG_FRENCH}  "Scrinium est en cours d'utilisation. Fermez-le (clic droit sur son icône près de l'horloge, puis Quitter), puis relancez l'installation."
LangString TXT_FERME     ${LANG_ENGLISH} "Scrinium is running. Close it (right-click its icon near the clock, then Quit), then run the setup again."
LangString TXT_FICHES    ${LANG_FRENCH}  "Vos fiches (dossier %APPDATA%\scrinium) n'ont PAS été supprimées."
LangString TXT_FICHES    ${LANG_ENGLISH} "Your notes (folder %APPDATA%\scrinium) have NOT been deleted."

; --- Installation ---------------------------------------------------------------------------------------------------
; Une « Section » est un bloc d'actions. Celle-ci est obligatoire (SectionIn RO = lecture seule, case grisée).
Section "$(TXT_PROGRAMME)" SecProgramme
  SectionIn RO

  ; Si Scrinium tourne encore, ses fichiers sont verrouillés par Windows : un programme en cours d'exécution ne peut
  ; pas être supprimé. On essaie donc de supprimer l'ancien scrinium.exe (il va être remplacé de toute façon) ; si
  ; Windows refuse, c'est qu'il tourne : on le dit à l'utilisateur et on s'arrête SANS avoir rien copié.
  IfFileExists "$INSTDIR\scrinium.exe" 0 pas_de_version_installee
    ClearErrors
    Delete "$INSTDIR\scrinium.exe"
    IfErrors 0 pas_de_version_installee
      MessageBox MB_OK|MB_ICONEXCLAMATION "$(TXT_FERME)"
      Abort                                   ; arrête l'installation sans rien casser
  pas_de_version_installee:

  SetOutPath "$INSTDIR"                       ; dossier de destination des « File » qui suivent
  ; Tout le contenu de dist\scrinium\ (le .exe, _internal\ avec Python, Qt, les extensions…), sous-dossiers compris.
  File /r "${DOSSIER_PROGRAMME}\*.*"

  ; Programme de désinstallation, appelé plus tard par Windows (Paramètres > Applications).
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Raccourci du menu Démarrer : « Scrinium » → scrinium.exe
  CreateDirectory "$SMPROGRAMS\${NOM}"
  CreateShortcut  "$SMPROGRAMS\${NOM}\${NOM}.lnk" "$INSTDIR\scrinium.exe"
  CreateShortcut  "$SMPROGRAMS\${NOM}\Désinstaller ${NOM}.lnk" "$INSTDIR\uninstall.exe"

  ; Liens scrinium://… (invitations de partage) : ouverts par scrinium.exe, sans droits administrateur (HKCU).
  WriteRegStr HKCU "Software\Classes\scrinium" "" "URL:Scrinium"
  WriteRegStr HKCU "Software\Classes\scrinium" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\scrinium\shell\open\command" "" '"$INSTDIR\scrinium.exe" "%1"'

  ; Mémorise le dossier choisi (pour proposer le même lors d'une mise à jour).
  WriteRegStr HKCU "Software\${NOM}" "Dossier" "$INSTDIR"

  ; Inscription dans « Applications installées » de Windows.
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "DisplayName"     "${NOM}"
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "Publisher"       "${EDITEUR}"
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "URLInfoAbout"    "${SITE}"
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "DisplayIcon"     "$INSTDIR\scrinium.exe"
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr   HKCU "${CLE_DESINSTALL}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKCU "${CLE_DESINSTALL}" "NoModify" 1        ; pas de bouton « Modifier »
  WriteRegDWORD HKCU "${CLE_DESINSTALL}" "NoRepair" 1        ; pas de bouton « Réparer »
  ; Taille affichée dans la liste (en Ko) : NSIS la calcule d'après les fichiers copiés.
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${CLE_DESINSTALL}" "EstimatedSize" "$0"
SectionEnd

; Section facultative (case à cocher dans la page « composants »).
Section /o "$(TXT_BUREAU)" SecBureau
  CreateShortcut "$DESKTOP\${NOM}.lnk" "$INSTDIR\scrinium.exe"
SectionEnd

; --- Désinstallation ------------------------------------------------------------------------------------------------
Section "Uninstall"
  ; Supprime le programme. /r = tout le contenu. Les fiches de l'utilisateur sont ailleurs (%APPDATA%) : intactes.
  RMDir /r "$INSTDIR"

  ; Raccourcis
  Delete "$SMPROGRAMS\${NOM}\${NOM}.lnk"
  Delete "$SMPROGRAMS\${NOM}\Désinstaller ${NOM}.lnk"
  RMDir  "$SMPROGRAMS\${NOM}"
  Delete "$DESKTOP\${NOM}.lnk"

  ; Inscriptions du registre : « Applications installées », dossier mémorisé, et démarrage automatique éventuel
  ; (la valeur « scrinium » de la clé Run, écrite par la case « Lancer au démarrage de la session » de Scrinium :
  ; sans cela, Windows tenterait de lancer un programme qui n'existe plus à chaque ouverture de session).
  DeleteRegKey HKCU "${CLE_DESINSTALL}"
  DeleteRegKey HKCU "Software\${NOM}"
  DeleteRegKey HKCU "Software\Classes\scrinium"
  DeleteRegValue HKCU "${CLE_DEMARRAGE}" "scrinium"

  ; Rappelle (sauf en mode silencieux) que les fiches sont conservées.
  MessageBox MB_OK|MB_ICONINFORMATION "$(TXT_FICHES)" /SD IDOK
SectionEnd
