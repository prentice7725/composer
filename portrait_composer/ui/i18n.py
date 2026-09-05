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
    "Portrait Composer": "Portrait Composer",
    "Context Workbench": "컨텍스트 작업대",
    "Assembly Tree": "Assembly 트리",
    "Inspector": "인스펙터",
    "Diagnostics": "진단",
    "Diagnostics / Assembly Status": "진단 / Assembly 상태",
    "Workspace": "작업공간",
    "COMPOSE": "조립",
    "RIG PREP": "리그 준비",
    "No recent files": "최근 파일 없음",
    "Clear Recent Files": "최근 파일 지우기",
    "Composition and source authoring": "조합 및 소스 편집",
    "Rig intent and bake preparation": "Rig Intent 및 Bake 준비",
    "Context Workbench · choose a context to continue": "컨텍스트 작업대 · 작업 컨텍스트를 선택하세요",
    "ASSEMBLE Workbench\nSelection remains active while context changes.": "ASSEMBLE 작업대\n컨텍스트를 바꾸는 동안 선택은 유지됩니다.",
    "ASSEMBLE Workbench\nNew Assembly is ready for input.": "ASSEMBLE 작업대\n새 Assembly 입력 준비 완료.",
    "Selection": "선택",
    "Nothing selected": "선택 없음",
    "Identity": "식별자",
    "Asset": "에셋",
    "Semantic": "시맨틱",
    "Slot": "슬롯",
    "Plane": "플레인",
    "Draw order": "그리기 순서",
    "Warnings": "경고",
    "Provenance": "출처",
    "Visible": "표시",
    "Opacity": "불투명도",
    "VisualOps stack": "VisualOps 스택",
    "Add Mask…": "마스크 추가…",
    "Add Quad Warp": "Quad Warp 추가",
    "Add Color": "색상 추가",
    "Invert Selected Mask": "선택 마스크 반전",
    "Reset VisualOps": "VisualOps 초기화",
    "Mask actions": "마스크 동작",
    "Operation": "동작",
    "Mode": "모드",
    "Radius": "반경",
    "Paint on Canvas": "캔버스에 칠하기",
    "Mask Brush": "마스크 브러시",
    "Feather": "페더",
    "Color VisualOp": "색상 VisualOp",
    "Update Color": "색상 갱신",
    "Fit": "맞춤",
    "Fit Width": "너비 맞춤",
    "Fit Height": "높이 맞춤",
    "Fit Box": "박스 맞춤",
    "Anchor": "앵커",
    "Align to Canvas": "캔버스에 정렬",
    "Quad Warp": "Quad Warp",
    "Update Quad Warp": "Quad Warp 갱신",
    "No Assembly Bundle open": "열린 Assembly Bundle 없음",
    "ASSEMBLY STATUS": "ASSEMBLY 상태",
    "DIAGNOSTICS": "진단",
    "[OK] No diagnostics": "[정상] 진단 항목 없음",
    "Sources": "소스",
    "Output Layer Name": "출력 레이어 이름",
    "Edit Source": "소스 편집",
    "Reset": "초기화",
    "Apply": "적용",
    "Profile": "프로필",
    "Bake Selected": "선택 항목 Bake",
    "Bake Plan": "Bake 계획",
    "Create Plan": "계획 생성",
    "Analyze Plan": "계획 분석",
    "Apply Plan": "계획 적용",
    "Saved plans": "저장된 계획",
    "No plan selected": "선택된 계획 없음",
    "Import Donor Image…": "Donor 이미지 가져오기…",
    "Target: none selected": "대상: 선택 없음",
    "Preview": "미리보기",
    "Ghost opacity": "고스트 불투명도",
    "Clear": "지우기",
    "Import": "가져오기",
    "Apply Harvest": "Harvest 적용",
    "Bake Mode": "Bake 모드",
    "Seam Cleanup": "Seam 정리",
    "Expand Under": "아래 레이어 확장",
    "Remove Internal Lines": "내부 선 제거",
    "Ownership Rule": "소유권 규칙",
    "Bake mode": "Bake 모드",
    "Variant Sets": "Variant Set",
    "Expression Presets": "Expression Preset",
    "New Preset…": "새 Preset…",
    "New Assembly": "새 Assembly",
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
