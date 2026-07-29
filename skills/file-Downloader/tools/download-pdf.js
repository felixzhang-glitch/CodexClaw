#!/usr/bin/env bun
/**
 * File Downloader - 下载 PDF 或将网页/Markdown 转为离线 PDF/Markdown
 *
 * 用法：
 *   bun download-pdf.js <url> [--format both] [--output-dir output/pdf]
 *   bun download-pdf.js --markdown tmp/article.md --source-url <url> --format both
 *
 * 依赖：cheerio (HTML 解析), pdfmake (PDF 生成)
 */

import * as fs from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";
import * as cheerio from "cheerio";
import PdfPrinter from "pdfmake";

// ---------------------------------------------------------------------------
// 常量
// ---------------------------------------------------------------------------

const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36";

const CJK_RE = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]/;

// ---------------------------------------------------------------------------
// CLI 参数解析
// ---------------------------------------------------------------------------

function printHelp() {
  console.log(`File Downloader - 下载 PDF 或将网页转为离线 PDF/Markdown

用法：
  bun download-pdf.js <url> [options]
  bun download-pdf.js --markdown <file.md> --source-url <url> [options]

选项：
  --markdown <path>      本地 Markdown 文件（用于被封锁页面的离线转换）
  --source-url <url>     Markdown 模式下的原始来源 URL
  --output-dir <dir>     输出目录 (默认: output/pdf)
  --filename <name>      输出文件名（不含扩展名）
  --title <title>        覆盖自动检测的标题
  --format <fmt>         输出格式：pdf / md / both (默认: both)
  -h, --help             显示帮助信息`);
}

function parseArgs(argv) {
  const args = {
    url: null,
    markdown: null,
    sourceUrl: null,
    outputDir: "output/pdf",
    filename: null,
    title: null,
    format: "both",
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    switch (arg) {
      case "--markdown":
        args.markdown = argv[++i];
        break;
      case "--source-url":
        args.sourceUrl = argv[++i];
        break;
      case "--output-dir":
        args.outputDir = argv[++i];
        break;
      case "--filename":
        args.filename = argv[++i];
        break;
      case "--title":
        args.title = argv[++i];
        break;
      case "--format":
        args.format = argv[++i];
        break;
      case "-h":
      case "--help":
        printHelp();
        process.exit(0);
      default:
        if (arg.startsWith("-")) {
          console.error(`错误：未知选项 ${arg}`);
          printHelp();
          process.exit(2);
        }
        args.url = arg;
        break;
    }
  }

  if (!args.url && !args.markdown) {
    console.error("错误：请提供 URL 或 --markdown 文件");
    printHelp();
    process.exit(2);
  }

  if (!["pdf", "md", "both"].includes(args.format)) {
    console.error("错误：--format 必须是 pdf / md / both");
    process.exit(2);
  }

  return args;
}

// ---------------------------------------------------------------------------
// 工具函数
// ---------------------------------------------------------------------------

function slugify(value, fallback = "download") {
  let v = value.trim().toLowerCase();
  v = v.replace(/https?:\/\//, "");
  v = v.replace(/[^a-z0-9._-]+/g, "-");
  v = v.replace(/-{2,}/g, "-").replace(/^[-._]+|[-._]+$/g, "");
  return (v || fallback).slice(0, 90);
}

function cleanText(value) {
  return value.replace(/\s+/g, " ").trim();
}

function cjkRatio(text) {
  const visible = [...text].filter((ch) => !/\s/.test(ch));
  if (visible.length === 0) return 0;
  const cjkCount = visible.filter((ch) => CJK_RE.test(ch)).length;
  return cjkCount / visible.length;
}

function firstExistingPath(paths) {
  for (const p of paths) {
    const expanded = p.replace(/^~/, process.env.HOME || "");
    if (fs.existsSync(expanded)) return expanded;
  }
  return null;
}

function resolveOutputPath(outputDir, filename, url, title, ext = ".pdf") {
  let name;
  if (filename) {
    name = filename.toLowerCase().endsWith(ext) ? filename : path.parse(filename).name + ext;
  } else if (title) {
    name = slugify(title) + ext;
  } else if (url) {
    const parsed = new URL(url);
    const stem = path.basename(parsed.pathname);
    if (stem.toLowerCase().endsWith(".pdf")) {
      name = slugify(stem, "download") + ext;
    } else {
      const digest = crypto.createHash("sha1").update(url).digest("hex").slice(0, 8);
      name = `${slugify(parsed.hostname + parsed.pathname, "download")}-${digest}${ext}`;
    }
  } else {
    name = `download${ext}`;
  }
  fs.mkdirSync(outputDir, { recursive: true });
  return path.join(outputDir, name);
}

// ---------------------------------------------------------------------------
// 学术源 PDF 直链解析
// ---------------------------------------------------------------------------

function resolveNativePdfUrl(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }
  const host = parsed.hostname.replace(/^www\./, "");
  const pathname = parsed.pathname.replace(/\/$/, "");

  // arXiv: arxiv.org/abs/{id} -> arxiv.org/pdf/{id}.pdf
  if (host.endsWith("arxiv.org")) {
    const m = pathname.match(/^\/abs\/(.+)$/);
    if (m) return `https://arxiv.org/pdf/${m[1]}.pdf`;
  }

  // ACL Anthology
  if (host === "aclanthology.org") {
    const m = pathname.match(/^\/([A-Z]\d{2}-\d{4}|20\d{2}\.[\w-]+)$/);
    if (m) return `https://aclanthology.org${pathname}.pdf`;
  }

  // OpenReview: openreview.net/forum?id={id} -> openreview.net/pdf?id={id}
  if (host === "openreview.net" && pathname === "/forum") {
    const paperId = parsed.searchParams.get("id");
    if (paperId) return `https://openreview.net/pdf?id=${paperId}`;
  }

  // NeurIPS
  if (host === "proceedings.neurips.cc") {
    if (pathname.includes("/paper_files/paper/") && !pathname.endsWith("/file")) {
      return url.replace(/\/$/, "") + "/file";
    }
  }

  return null;
}

// ---------------------------------------------------------------------------
// HTTP 请求
// ---------------------------------------------------------------------------

async function requestUrl(url) {
  const response = await fetch(url, {
    headers: {
      "User-Agent": USER_AGENT,
      Accept: "text/html,application/pdf,*/*",
    },
    redirect: "follow",
    signal: AbortSignal.timeout(45000),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${response.statusText}`);
  }
  return response;
}

function isPdfResponse(response, buffer) {
  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  if (contentType.includes("application/pdf")) return true;
  if (buffer && buffer.length >= 5 && buffer.slice(0, 5).toString() === "%PDF-") return true;
  return false;
}

// ---------------------------------------------------------------------------
// HTML → items 提取
// ---------------------------------------------------------------------------

function htmlToItems(sourceHtml) {
  const $ = cheerio.load(sourceHtml);

  // 移除无关标签
  $("script, style, noscript, template, svg").remove();

  const title = cleanText($("h1").first().text() || $("title").first().text() || "");
  const $root = $("article").first().length
    ? $("article").first()
    : $("main").first().length
      ? $("main").first()
      : $("body").length
        ? $("body")
        : $.root();

  const items = [];
  const accepted = new Set(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre", "table", "figcaption", "img"]);
  const containers = new Set(["blockquote", "pre", "table"]);
  let seenTitle = false;

  $root.find("*").each((_, elem) => {
    const tagName = elem.tagName?.toLowerCase();
    if (!tagName || !accepted.has(tagName)) return;

    // 跳过嵌套在容器内的元素（避免重复）
    let parent = elem.parent;
    while (parent && parent.tagName) {
      if (containers.has(parent.tagName.toLowerCase())) return;
      parent = parent.parent;
    }

    if (tagName === "img") {
      const alt = cleanText($(elem).attr("alt") || "");
      if (alt) items.push(["caption", `Image: ${alt}`]);
      return;
    }

    const text = cleanText($(elem).text());
    if (!text) return;

    if (tagName === "h1") {
      if (seenTitle || text === title) {
        seenTitle = true;
        return;
      }
      seenTitle = true;
    }

    if (tagName === "table") {
      const rows = [];
      $(elem).find("tr").each((_, tr) => {
        const cells = [];
        $(tr).find("th, td").each((_, cell) => {
          cells.push(cleanText($(cell).text()));
        });
        if (cells.length > 0) rows.push(cells);
      });
      if (rows.length > 0) items.push(["table", rows]);
      return;
    }

    items.push([tagName, text]);
  });

  return [title || "Offline webpage", items];
}

// ---------------------------------------------------------------------------
// Markdown → items 解析
// ---------------------------------------------------------------------------

function markdownToItems(markdownText) {
  const items = [];
  let title = "Offline webpage";
  let inCode = false;
  let codeLines = [];
  let paragraph = [];

  function flushParagraph() {
    if (paragraph.length > 0) {
      items.push(["p", cleanText(paragraph.join(" "))]);
      paragraph = [];
    }
  }

  for (const raw of markdownText.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    if (line.trim().startsWith("```")) {
      if (inCode) {
        items.push(["pre", codeLines.join("\n")]);
        codeLines = [];
        inCode = false;
      } else {
        flushParagraph();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    const stripped = line.trim();
    if (!stripped) {
      flushParagraph();
      continue;
    }
    if (stripped.startsWith("# ")) {
      flushParagraph();
      const text = stripped.slice(2).trim();
      if (title === "Offline webpage") {
        title = text;
      } else {
        items.push(["h1", text]);
      }
    } else if (stripped.startsWith("## ")) {
      flushParagraph();
      items.push(["h2", stripped.slice(3).trim()]);
    } else if (stripped.startsWith("### ")) {
      flushParagraph();
      items.push(["h3", stripped.slice(4).trim()]);
    } else if (stripped.startsWith("- ") || stripped.startsWith("* ")) {
      flushParagraph();
      items.push(["li", stripped.slice(2).trim()]);
    } else if (stripped.startsWith("> ")) {
      flushParagraph();
      items.push(["caption", stripped.slice(2).trim()]);
    } else {
      paragraph.push(stripped);
    }
  }
  flushParagraph();
  if (codeLines.length > 0) {
    items.push(["pre", codeLines.join("\n")]);
  }
  return [title, items];
}

// ---------------------------------------------------------------------------
// 字体注册
// ---------------------------------------------------------------------------

const CJK_FONT_PATHS = [
  "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
  "/Library/Fonts/Arial Unicode.ttf",
  "~/Library/Fonts/Arial Unicode.ttf",
  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
];

function getFontProfile(textSample) {
  const cjkHeavy = cjkRatio(textSample) >= 0.08;
  const hasCjk = CJK_RE.test(textSample);

  if (cjkHeavy || hasCjk) {
    const cjkPath = firstExistingPath(CJK_FONT_PATHS);
    if (cjkPath) {
      return {
        fonts: {
          Main: { normal: cjkPath, bold: cjkPath, italics: cjkPath, bolditalics: cjkPath },
          Mono: { normal: "Courier", bold: "Courier-Bold", italics: "Courier-Oblique", bolditalics: "Courier-BoldOblique" },
        },
        defaultFont: "Main",
      };
    }
  }

  return {
    fonts: {
      Main: { normal: "Helvetica", bold: "Helvetica-Bold", italics: "Helvetica-Oblique", bolditalics: "Helvetica-BoldOblique" },
      Mono: { normal: "Courier", bold: "Courier-Bold", italics: "Courier-Oblique", bolditalics: "Courier-BoldOblique" },
    },
    defaultFont: "Main",
  };
}

// ---------------------------------------------------------------------------
// PDF 生成 (pdfmake)
// ---------------------------------------------------------------------------

function escapeXml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function buildPdfContent(title, items, sourceUrl, generatedFrom) {
  const content = [];

  // 标题
  content.push({ text: title, style: "title" });

  // 元信息
  const metaChildren = [{ text: "Source: " }];
  if (sourceUrl) {
    metaChildren.push({ text: sourceUrl, link: sourceUrl, color: "#1a0dab" });
  } else {
    metaChildren.push({ text: generatedFrom });
  }
  content.push({ text: metaChildren, style: "meta" });

  const now = new Date();
  const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  content.push({ text: `Generated: ${dateStr} from ${generatedFrom}`, style: "meta" });
  content.push({ text: "", margin: [0, 6, 0, 0] });

  // 内容
  for (const [kind, value] of items) {
    if (kind === "h1" || kind === "h2") {
      content.push({ text: String(value), style: "h2" });
    } else if (kind === "h3" || kind === "h4") {
      content.push({ text: String(value), style: "h3" });
    } else if (kind === "li") {
      content.push({ text: `• ${value}`, style: "bullet" });
    } else if (kind === "caption" || kind === "figcaption") {
      content.push({ text: `[Note] ${value}`, style: "caption" });
    } else if (kind === "blockquote") {
      content.push({ text: String(value), style: "caption" });
    } else if (kind === "pre") {
      // 代码块：替换 box-drawing 字符，限制行宽
      const text = String(value)
        .replace(/├/g, "+").replace(/└/g, "+").replace(/│/g, "|").replace(/─/g, "-").replace(/…/g, "...");
      const wrapped = [];
      for (const line of text.split("\n")) {
        if (line.length <= 82) {
          wrapped.push(line);
        } else {
          for (let i = 0; i < line.length; i += 82) {
            wrapped.push(line.slice(i, i + 82));
          }
        }
      }
      content.push({
        table: {
          widths: ["*"],
          body: [[{ text: wrapped.join("\n"), style: "pre" }]],
        },
        layout: {
          hLineWidth: () => 0.5,
          vLineWidth: () => 0.5,
          hLineColor: () => "#dddddd",
          vLineColor: () => "#dddddd",
          paddingLeft: () => 6,
          paddingRight: () => 6,
          paddingTop: () => 6,
          paddingBottom: () => 6,
          fillColor: () => "#f5f5f5",
        },
        margin: [0, 5, 0, 10],
      });
    } else if (kind === "table") {
      const rows = Array.isArray(value) ? value : [];
      if (rows.length > 0) {
        const width = Math.max(...rows.map((r) => r.length));
        const body = rows.map((row, rowIdx) => {
          const padded = [...row, ...Array(width - row.length).fill("")];
          return padded.map((cell) => ({
            text: String(cell),
            style: rowIdx === 0 ? "tableHeader" : "tableCell",
          }));
        });
        content.push({
          table: { widths: Array(width).fill("*"), body },
          layout: {
            hLineWidth: () => 0.25,
            vLineWidth: () => 0.25,
            hLineColor: () => "#cccccc",
            vLineColor: () => "#cccccc",
            paddingLeft: () => 4,
            paddingRight: () => 4,
            paddingTop: () => 3,
            paddingBottom: () => 3,
            fillColor: (rowIndex) => (rowIndex === 0 ? "#eeeeee" : null),
          },
          margin: [0, 0, 0, 8],
        });
      }
    } else {
      content.push({ text: String(value), style: "body" });
    }
  }

  return content;
}

async function buildPdf(outPath, title, items, sourceUrl, generatedFrom) {
  const textSample = [title, ...items.slice(0, 80).map(([, v]) => String(v))].join("\n");
  const fontProfile = getFontProfile(textSample);

  const printer = new PdfPrinter(fontProfile.fonts);

  const docDefinition = {
    pageSize: "A4",
    pageMargins: [54, 51, 54, 48],
    defaultStyle: {
      font: fontProfile.defaultFont,
      fontSize: 10.8,
      lineHeight: 1.3,
    },
    styles: {
      title: { fontSize: 24, bold: true, margin: [0, 0, 0, 12] },
      meta: { fontSize: 8.8, color: "#555555", margin: [0, 0, 0, 5] },
      body: { fontSize: 10.8, lineHeight: 1.35, margin: [0, 0, 0, 9.5] },
      h2: { fontSize: 16.5, bold: true, margin: [0, 16, 0, 8] },
      h3: { fontSize: 12.8, bold: true, margin: [0, 11, 0, 6] },
      bullet: { fontSize: 10.6, margin: [17, 0, 0, 6.5] },
      caption: { fontSize: 9, color: "#666666", margin: [9, 0, 9, 8.5] },
      pre: { font: "Mono", fontSize: 8, lineHeight: 1.2 },
      tableHeader: { fontSize: 9, bold: true },
      tableCell: { fontSize: 9 },
    },
    content: buildPdfContent(title, items, sourceUrl, generatedFrom),
    footer: (currentPage) => ({
      columns: [
        { text: title.slice(0, 70), margin: [54, 0, 0, 0] },
        { text: `Page ${currentPage}`, alignment: "right", margin: [0, 0, 54, 0] },
      ],
      fontSize: 8,
      color: "#777777",
    }),
    info: {
      title,
      subject: `Offline PDF generated from ${sourceUrl || generatedFrom}`,
    },
  };

  const pdfDoc = printer.createPdfKitDocument(docDefinition);

  await new Promise((resolve, reject) => {
    const stream = fs.createWriteStream(outPath);
    pdfDoc.pipe(stream);
    pdfDoc.on("error", reject);
    stream.on("finish", resolve);
    stream.on("error", reject);
    pdfDoc.end();
  });
}

// ---------------------------------------------------------------------------
// Markdown 输出
// ---------------------------------------------------------------------------

function writeMarkdown(outPath, title, items, sourceUrl) {
  const lines = [`# ${title}`, ""];
  if (sourceUrl) {
    lines.push(`Source: ${sourceUrl}`, "");
  }

  for (const [kind, value] of items) {
    if (kind === "h1" || kind === "h2") {
      lines.push(`## ${value}`, "");
    } else if (kind === "h3" || kind === "h4") {
      lines.push(`### ${value}`, "");
    } else if (kind === "li") {
      lines.push(`- ${value}`);
    } else if (kind === "pre") {
      lines.push("```text", String(value), "```", "");
    } else if (kind === "table") {
      const rows = Array.isArray(value) ? value.filter((r) => Array.isArray(r)) : [];
      if (rows.length > 0) {
        const width = Math.max(...rows.map((r) => r.length));
        const padded = rows.map((r) => [...r, ...Array(width - r.length).fill("")]);
        lines.push("| " + padded[0].join(" | ") + " |");
        lines.push("| " + Array(width).fill("---").join(" | ") + " |");
        for (const row of padded.slice(1)) {
          lines.push("| " + row.join(" | ") + " |");
        }
        lines.push("");
      }
    } else if (kind === "caption" || kind === "figcaption") {
      lines.push(`> ${value}`, "");
    } else {
      lines.push(String(value), "");
    }
  }

  fs.writeFileSync(outPath, lines.join("\n"), "utf-8");
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const outDir = args.outputDir;

  // --- Markdown fallback 模式 ---
  if (args.markdown) {
    const mdText = fs.readFileSync(args.markdown, "utf-8");
    let [title, items] = markdownToItems(mdText);
    if (args.title) title = args.title;
    const source = args.sourceUrl || args.url;

    if (args.format === "md" || args.format === "both") {
      const mdOut = resolveOutputPath(outDir, args.filename, source, title, ".md");
      writeMarkdown(mdOut, title, items, source);
      console.log(`generated_markdown=${mdOut}`);
    }
    if (args.format === "pdf" || args.format === "both") {
      const pdfOut = resolveOutputPath(outDir, args.filename, source, title, ".pdf");
      await buildPdf(pdfOut, title, items, source, `Markdown file ${args.markdown}`);
      console.log(`generated_pdf=${pdfOut}`);
    }
    return;
  }

  // --- URL 模式 ---
  const fetchUrl = resolveNativePdfUrl(args.url) || args.url;

  let response;
  try {
    response = await requestUrl(fetchUrl);
  } catch (err) {
    console.error(`error=fetch_failed message=${err.message}`);
    process.exit(2);
  }

  const buffer = Buffer.from(await response.arrayBuffer());

  // --- 原生 PDF 响应 ---
  if (isPdfResponse(response, buffer)) {
    if (args.format === "md") {
      console.error(
        "error=format_unavailable message=Source provides a native PDF only; " +
        "use --format pdf or both, or provide --markdown content"
      );
      process.exit(4);
    }
    const out = resolveOutputPath(outDir, args.filename, args.url, args.title, ".pdf");
    fs.writeFileSync(out, buffer);
    console.log(`downloaded_pdf=${out}`);
    return;
  }

  // --- HTML 页面：提取内容 ---
  const htmlText = buffer.toString("utf-8");
  let [title, items] = htmlToItems(htmlText);
  if (args.title) title = args.title;

  if (items.length === 0) {
    console.error("error=no_extractable_content message=Page yielded no readable content");
    process.exit(3);
  }

  const finalUrl = response.url || args.url;

  if (args.format === "md" || args.format === "both") {
    const mdOut = resolveOutputPath(outDir, args.filename, args.url, title, ".md");
    writeMarkdown(mdOut, title, items, finalUrl);
    console.log(`generated_markdown=${mdOut}`);
  }
  if (args.format === "pdf" || args.format === "both") {
    const pdfOut = resolveOutputPath(outDir, args.filename, args.url, title, ".pdf");
    await buildPdf(pdfOut, title, items, finalUrl, "webpage HTML");
    console.log(`generated_pdf=${pdfOut}`);
  }
}

main().catch((err) => {
  console.error(`error=unexpected message=${err.message}`);
  process.exit(1);
});
