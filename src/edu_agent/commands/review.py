"""Writing and confirming one of the three input documents.

The drift check lives here too: a document edited by hand and a document produced
by answering questions have to be reconciled before either is trusted, and the
student is the one who decides which wins.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent import ui
from edu_agent.commands import context
from edu_agent.i18n import t
from edu_agent.project import Project
from edu_agent.project.layout import DOC_FILES, INPUT_DOCS, DocSlot


def run_review(
    project: Project,
    slot: DocSlot,
    *,
    no_llm: bool,
    mock: bool,
    source: Path | None = None,
) -> None:
    from edu_agent.documents.io import detect_drift, load_document
    from edu_agent.questionnaire import educational as q_edu
    from edu_agent.questionnaire import principles as q_pri
    from edu_agent.questionnaire import technical as q_tec
    from edu_agent.schemas.common import DocumentStatus

    path = project.doc_path(slot)
    if path.exists():
        model, body = load_document(path, slot.model)
        if detect_drift(model, body):
            ui.warn(t("review.drift_detected"))
            keep = ui.ask_choice(
                "어떻게 할까요?",
                [
                    ui.Choice("1", "질문에 다시 답해서 구조를 갱신하겠습니다", "redo"),
                    ui.Choice("2", "본문 수정만 인정하고 그대로 두겠습니다", "keep"),
                ],
                default="1",
                allow_later=False,
            )
            if keep == "keep":
                from edu_agent.documents.io import save_document

                model.meta.status = DocumentStatus.CONFIRMED
                save_document(path, model, body)
                ui.ok(t("common.saved", path=path.name))
                return
    else:
        model = slot.model.new(language=project.config.language)

    provider = None
    if slot.key == "principles":
        # Writing the document is the part that works before a key arrives.
        provider = context.provider(project, no_llm=no_llm, mock=mock, optional=True)
        if provider is None:
            ui.warn(t("review.no_llm"))

    try:
        if slot.key == "educational":
            model = q_edu.run_educational(model, tasks_dir=project.tasks_dir)  # type: ignore[arg-type]
            summary = q_edu.summarize(model)  # type: ignore[arg-type]
        elif slot.key == "principles":
            model = q_pri.run_principles(  # type: ignore[arg-type]
                model, provider=provider, source=source
            )
            summary = q_pri.summarize(model)  # type: ignore[arg-type]
        else:
            users = None
            if project.exists(DOC_FILES[0]):
                ed, _ = load_document(project.doc_path(DOC_FILES[0]), DOC_FILES[0].model)
                users = ed.context.expected_users  # type: ignore[attr-defined]
            model = q_tec.run_technical(model, expected_users=users)  # type: ignore[arg-type]
            summary = q_tec.summarize(model)  # type: ignore[arg-type]
    except ui.UserAbort:
        context.write_doc(project, slot, model)
        ui.say()
        ui.info(t("common.cancelled"))
        ui.note(f"이어서 하려면: edu-agent review {slot.index:02d}")
        return

    action = ui.confirm_summary(t("review.summary_title"), summary)
    if action == "confirm":
        model.meta.status = DocumentStatus.CONFIRMED
    elif action in {"edit", "add"}:
        ui.note(
            f"{slot.filename} 파일을 직접 열어 수정한 뒤 "
            f"'edu-agent review {slot.index:02d}' 를 다시 실행하세요."
        )

    missing = model.missing_required()
    saved = context.write_doc(project, slot, model)
    ui.say()
    ui.ok(t("common.saved", path=saved.name))

    if missing:
        ui.warn(f"{t('review.missing_title')}: {', '.join(missing)}")

    nxt = next((s for s in INPUT_DOCS if s.index > slot.index), None)
    ui.say()
    if nxt is not None:
        ui.info(f"{t('common.next_step')}: edu-agent review {nxt.index:02d}")
    else:
        ui.info(f"{t('common.next_step')}: edu-agent compile")

