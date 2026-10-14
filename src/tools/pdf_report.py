"""Generate downloadable Chinese PDF reports for the ops agent."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
import uuid
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = Path(
    os.getenv("REPORT_OUTPUT_DIR", str(PROJECT_ROOT / "var" / "reports")),
).expanduser().resolve()
REPORT_TTL_SECONDS = max(300, int(os.getenv("REPORT_DOWNLOAD_TTL_SECONDS", "86400")))
CJK_FONT = "STSong-Light"

# ReportLab's built-in CID font supports Simplified Chinese without bundling a font file.
pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))


def _signing_secret() -> str:
    """Use a dedicated report secret; fall back to the existing API key for compatibility."""
    secret = os.getenv("REPORT_DOWNLOAD_SECRET", "").strip()
    if secret:
        return secret

    try:
        from conf.model import API_KEY  # Existing project configuration.

        if API_KEY:
            return str(API_KEY)
    except Exception:
        pass

    raise RuntimeError(
        "请配置 REPORT_DOWNLOAD_SECRET，或确保 conf.model.API_KEY 已设置，"
        "以便签发 PDF 下载链接。",
    )


def _signature(filename: str, expires: int) -> str:
    payload = f"{filename}:{expires}".encode("utf-8")
    return hmac.new(_signing_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def create_download_token(filename: str, expires: int) -> str:
    """Create a time-limited signature for a report download URL."""
    return _signature(filename, expires)


def verify_download_token(filename: str, expires: str | int, token: str) -> bool:
    """Verify a signed, expiring report download URL."""
    if not filename or Path(filename).name != filename or not filename.endswith(".pdf"):
        return False
    try:
        expiry = int(expires)
    except (TypeError, ValueError):
        return False

    now = int(time.time())
    # Prevent both expired links and arbitrarily long-lived forged URLs.
    if expiry < now or expiry > now + REPORT_TTL_SECONDS + 60:
        return False
    try:
        expected = _signature(filename, expiry)
    except RuntimeError:
        return False
    return hmac.compare_digest(expected, str(token or ""))


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "OpsReportTitle",
            parent=base["Title"],
            fontName=CJK_FONT,
            fontSize=21,
            leading=29,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#17365D"),
            spaceAfter=8 * mm,
        ),
        "h1": ParagraphStyle(
            "OpsReportH1", parent=base["Heading1"], fontName=CJK_FONT,
            fontSize=15, leading=21, textColor=colors.HexColor("#17365D"),
            spaceBefore=5 * mm, spaceAfter=2 * mm,
        ),
        "h2": ParagraphStyle(
            "OpsReportH2", parent=base["Heading2"], fontName=CJK_FONT,
            fontSize=12, leading=18, textColor=colors.HexColor("#24527A"),
            spaceBefore=3 * mm, spaceAfter=1.5 * mm,
        ),
        "body": ParagraphStyle(
            "OpsReportBody", parent=base["BodyText"], fontName=CJK_FONT,
            fontSize=9.5, leading=16, alignment=TA_LEFT,
            textColor=colors.HexColor("#202124"), spaceAfter=2.2 * mm,
            wordWrap="CJK",
        ),
        "bullet": ParagraphStyle(
            "OpsReportBullet", parent=base["BodyText"], fontName=CJK_FONT,
            fontSize=9.5, leading=15, leftIndent=5 * mm,
            firstLineIndent=-3 * mm, spaceAfter=1.2 * mm,
            wordWrap="CJK",
        ),
        "meta": ParagraphStyle(
            "OpsReportMeta", parent=base["BodyText"], fontName=CJK_FONT,
            fontSize=9, leading=14, textColor=colors.HexColor("#343A40"),
            wordWrap="CJK",
        ),
        "table": ParagraphStyle(
            "OpsReportTable", parent=base["BodyText"], fontName=CJK_FONT,
            fontSize=8.3, leading=12, wordWrap="CJK",
        ),
        "table_header": ParagraphStyle(
            "OpsReportTableHeader", parent=base["BodyText"], fontName=CJK_FONT,
            fontSize=8.5, leading=12, textColor=colors.white,
            wordWrap="CJK",
        ),
    }


def _inline_markup(text: str) -> str:
    """Escape HTML first, then support a safe subset of Markdown inline syntax."""
    text = escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    return text


def _split_table_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [cell.strip() for cell in cells]


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _markdown_flowables(content: str, styles: dict[str, ParagraphStyle]) -> list:
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    story: list = []
    i = 0

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped:
            story.append(Spacer(1, 1.5 * mm))
            i += 1
            continue

        # Convert Markdown tables to real PDF tables.
        if stripped.startswith("|") and i + 1 < len(lines) and lines[i + 1].strip().startswith("|"):
            raw_rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row_line = lines[i].strip()
                if not _is_table_separator(row_line):
                    raw_rows.append(_split_table_row(row_line))
                i += 1
            if raw_rows:
                col_count = max(len(row) for row in raw_rows)
                normalized = [row + [""] * (col_count - len(row)) for row in raw_rows]
                table_data = []
                for row_index, row in enumerate(normalized):
                    style = styles["table_header"] if row_index == 0 else styles["table"]
                    table_data.append([Paragraph(_inline_markup(cell), style) for cell in row])
                available_width = A4[0] - 36 * mm
                table = Table(
                    table_data,
                    repeatRows=1,
                    hAlign="LEFT",
                    colWidths=[available_width / col_count] * col_count,
                )
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#24527A")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FC")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD5DF")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]))
                story.extend([table, Spacer(1, 3 * mm)])
            continue

        if re.fullmatch(r"[-*_]{3,}", stripped):
            story.extend([HRFlowable(width="100%", thickness=0.7, color=colors.HexColor("#CCD5DF")), Spacer(1, 2 * mm)])
            i += 1
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            style_name = "h1" if level == 1 else "h2"
            story.append(Paragraph(_inline_markup(heading.group(2)), styles[style_name]))
            i += 1
            continue

        bullet = re.match(r"^[-*+]\s+(.+)$", stripped)
        if bullet:
            story.append(Paragraph("- " + _inline_markup(bullet.group(1)), styles["bullet"]))
            i += 1
            continue

        numbered = re.match(r"^(\d+)[.)、]\s+(.+)$", stripped)
        if numbered:
            story.append(Paragraph(f"{numbered.group(1)}. {_inline_markup(numbered.group(2))}", styles["bullet"]))
            i += 1
            continue

        # Join wrapped source lines into one wrapping paragraph.
        paragraph_lines = [stripped]
        i += 1
        while i < len(lines):
            candidate = lines[i].strip()
            if (
                not candidate
                or candidate.startswith("|")
                or re.match(r"^#{1,3}\s+", candidate)
                or re.match(r"^[-*+]\s+", candidate)
                or re.match(r"^\d+[.)、]\s+", candidate)
                or re.fullmatch(r"[-*_]{3,}", candidate)
            ):
                break
            paragraph_lines.append(candidate)
            i += 1
        story.append(Paragraph(_inline_markup(" ".join(paragraph_lines)), styles["body"]))

    return story


def _draw_page(canvas, doc) -> None:
    canvas.saveState()
    page_width, page_height = A4
    canvas.setStrokeColor(colors.HexColor("#D9E2F0"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, page_height - 14 * mm, page_width - 18 * mm, page_height - 14 * mm)
    canvas.setFont(CJK_FONT, 7.5)
    canvas.setFillColor(colors.HexColor("#65758B"))
    canvas.drawString(18 * mm, 9 * mm, "智能运维报告 | 内部使用")
    canvas.drawRightString(page_width - 18 * mm, 9 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def generate_pdf_report(
    title: str,
    report_content: str,
    alert_id: str = "",
    risk_level: str = "未评估",
) -> str:
    """
    生成生产运维 PDF 报告，并返回报告下载链接。
    当用户明确要求生成 PDF、创建报告文件或导出报告时，调用此工具。
    请将分析过程中已经确认的信息填入 report_content。
    信息来源可以是当前对话内容或工具查询结果。
    不得编造监控数据、时间戳、故障根因或已完成的操作。

    本工具仅负责生成报告文件，不会执行任何生产环境操作。

    参数：
        title：报告标题，例如“生产告警分析报告”。

        report_content：报告正文，使用 Markdown 格式编写。
            支持标题、列表和简单的管道符表格。

        alert_id：关联的告警 ID；如果没有，则不填写。

        risk_level：基于现有分析结论确定的风险等级；
            如果尚未评估，则填写“未评估”。
    """
    title = (title or "生产运维分析报告").strip()[:120]
    report_content = (report_content or "").strip()
    alert_id = (alert_id or "未提供").strip()[:160]
    risk_level = (risk_level or "未评估").strip()[:80]

    if not report_content:
        raise ValueError("report_content 不能为空，请先整理报告正文。")
    if len(report_content) > 50000:
        raise ValueError("报告正文过长，请控制在 50000 字符以内。")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    filename = f"production_report_{now:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.pdf"
    output_path = REPORT_DIR / filename
    styles = _styles()

    meta_data = [
        [Paragraph("报告类型", styles["meta"]), Paragraph("生产运维分析报告", styles["meta"])],
        [Paragraph("关联告警", styles["meta"]), Paragraph(_inline_markup(alert_id), styles["meta"])],
        [Paragraph("风险等级", styles["meta"]), Paragraph(_inline_markup(risk_level), styles["meta"])],
        [Paragraph("生成时间", styles["meta"]), Paragraph(now.strftime("%Y-%m-%d %H:%M:%S %Z"), styles["meta"])],
    ]
    meta_table = Table(meta_data, colWidths=[28 * mm, 145 * mm], hAlign="LEFT")
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF0F7")),
        ("BACKGROUND", (1, 0), (1, -1), colors.HexColor("#FAFBFD")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D5DDE7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story = [
        Spacer(1, 3 * mm),
        Paragraph(_inline_markup(title), styles["title"]),
        meta_table,
        Spacer(1, 7 * mm),
        HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#24527A")),
        Spacer(1, 3 * mm),
    ]
    story.extend(_markdown_flowables(report_content, styles))

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=20 * mm,
        bottomMargin=17 * mm,
        title=title,
        author="智能运维助手",
        subject="生产运维分析报告",
    )
    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)

    expires = int(time.time()) + REPORT_TTL_SECONDS
    token = create_download_token(filename, expires)
    base_url = os.getenv("REPORT_PUBLIC_BASE_URL", "http://127.0.0.1:8001").strip().rstrip("/")
    download_url = (
        f"{base_url}/v1/download"
        f"?filename={quote(filename)}&expires={expires}&token={token}"
    )
    expiration_text = datetime.fromtimestamp(expires).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    return (
        "PDF 报告已生成。\n\n"
        f"- 报告名称：{title}\n"
        f"- 文件名：{filename}\n"
        f"- 关联告警：{alert_id}\n"
        f"- 风险等级：{risk_level}\n"
        f"- 下载链接：[点击下载 PDF 报告]({download_url})\n"
        f"- 链接有效期至：{expiration_text}\n"
        "请在最终回复中保留下载链接。"
    )
