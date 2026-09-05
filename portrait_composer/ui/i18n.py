"""Qt-native language switching foundation (C6-B).

Qt Linguist ``.qm`` files are preferred when packaged.  The small built-in
catalog keeps source checkouts usable before a release build runs ``lrelease``
and still uses QTranslator/QCoreApplication rather than a document-side
locale manager.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTranslator

LOCALES = {"en": "English", "ko": "한국어"}

_KO = {
    "File": "파일",
    "Edit": "편집",
    "View": "보기",
    "Language": "언어",
    "New Assembly": "새 Assembly",
    "Import Portrait Bundle…": "Portrait Bundle 가져오기…",
    "Import Portrait Runs…": "Portrait Runs 가져오기…",
    "Open Assembly Bundle…": "Assembly Bundle 열기…",
    "Save": "저장",
    "Save As…": "다른 이름으로 저장…",
    "Export Rig Bundle…": "Rig Bundle 내보내기…",
    "Exit": "종료",
    "Undo": "실행 취소",
    "Redo": "다시 실행",
    "Fit Canvas": "캔버스 맞춤",
    "Fit Selection": "선택 영역 맞춤",
    "Focus Tree Search": "트리 검색으로 이동",
    "Harvest": "수확",
    "Donor Align": "Donor 정렬",
    "Rig Intent": "Rig Intent",
    "Bake": "Bake",
    "ASSEMBLE": "조립",
    "HARVEST": "수확",
    "VARIANTS": "변형",
    "DONOR": "Donor",
    "RIG INTENT": "Rig Intent",
    "BAKE": "Bake",
}


class BuiltinTranslator(QTranslator):
    def __init__(self, locale: str, parent=None):
        super().__init__(parent)
        self.locale = locale

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if self.locale == "ko":
            return _KO.get(source_text, source_text)
        return source_text


def install_translator(app, locale: str, *, base_dir: Path | None = None):
    """Return a QTranslator loaded from packaged QM or the source fallback."""
    locale = locale if locale in LOCALES else "en"
    translator = QTranslator(app)
    if base_dir is None:
        base_dir = Path(__file__).with_name("translations")
    qm_path = Path(base_dir) / f"portrait_composer_{locale}.qm"
    if not qm_path.exists() or not translator.load(str(qm_path)):
        translator = BuiltinTranslator(locale, app)
    app.installTranslator(translator)
    return translator

