// ==UserScript==
// @name         Codeforces Editorial Exporter
// @namespace    https://github.com/problem-tools
// @version      0.1.1
// @description  Export a Codeforces blog editorial as JSON or Markdown.
// @author       problem-tools
// @match        https://codeforces.com/blog/entry/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    const SCRIPT_VERSION = "0.1.1";
    const PANEL_ID = "problem-tools-cf-editorial-export";

    function main() {
        const entry = getEntryInfo();
        if (!entry)
            return;

        const panel = createPanel("CF 题解导出");
        panel.status.textContent = `blog/entry/${entry.entryId}`;
        panel.jsonButton.textContent = "导出 JSON";
        panel.markdownButton.textContent = "导出 Markdown";

        panel.jsonButton.addEventListener("click", () => exportEditorial(entry, "json", panel.status));
        panel.markdownButton.addEventListener("click", () => exportEditorial(entry, "markdown", panel.status));
    }

    function getEntryInfo() {
        const match = location.pathname.match(/^\/blog\/entry\/(\d+)/);
        if (!match)
            return null;

        return {
            platform: "Codeforces",
            entryId: match[1],
            sourceUrl: location.href.split("#")[0],
            title: cleanTitle(getMeta("og:title") || document.title),
        };
    }

    function exportEditorial(entry, format, status) {
        try {
            status.textContent = "正在解析题解正文";
            const data = extractEditorial(entry);

            if (format === "json") {
                downloadText(
                    `codeforces-blog-${entry.entryId}-editorial.json`,
                    JSON.stringify(data, null, 2),
                    "application/json;charset=utf-8"
                );
            } else {
                downloadText(
                    `codeforces-blog-${entry.entryId}-editorial.md`,
                    editorialToMarkdown(data),
                    "text/markdown;charset=utf-8"
                );
            }

            status.textContent = `完成：${data.sections.length} 个题解分段`;
        } catch (error) {
            status.textContent = `失败：${error && error.message ? error.message : error}`;
        }
    }

    function extractEditorial(entry) {
        const content = findEditorialContent();
        if (!content)
            throw new Error("未找到题解正文 .ttypography。");

        const clone = cleanupClone(content, entry.sourceUrl);
        const split = splitByProblemHeading(clone, entry.sourceUrl);

        return {
            platform: entry.platform,
            type: "editorial",
            entryId: entry.entryId,
            title: entry.title,
            sourceUrl: entry.sourceUrl,
            author: findAuthor(),
            publishedAt: findPublishedAt(),
            grabbedAt: new Date().toISOString(),
            scriptVersion: SCRIPT_VERSION,
            html: clone.innerHTML,
            text: readableText(clone),
            markdown: domToMarkdown(clone).trim(),
            introText: split.introText,
            introMarkdown: split.introMarkdown,
            sections: split.sections,
        };
    }

    function findEditorialContent() {
        const candidates = Array.from(document.querySelectorAll(".ttypography"));
        return candidates.find(node => !node.closest(".comment-content")) || null;
    }

    function splitByProblemHeading(root, baseUrl) {
        const intro = document.createElement("div");
        const sections = [];
        let current = null;

        for (const child of Array.from(root.children)) {
            const heading = detectProblemHeading(child, baseUrl);
            if (heading) {
                if (current)
                    sections.push(finalizeSection(current));
                current = {
                    index: heading.index,
                    title: heading.title,
                    problemUrl: heading.problemUrl,
                    nodes: [],
                };
                continue;
            }

            if (current)
                current.nodes.push(child.cloneNode(true));
            else
                intro.appendChild(child.cloneNode(true));
        }

        if (current)
            sections.push(finalizeSection(current));

        return {
            introText: readableText(intro),
            introMarkdown: domToMarkdown(intro).trim(),
            sections,
        };
    }

    function detectProblemHeading(node, baseUrl) {
        const anchor = node.querySelector("a[href*='/problem/']");
        if (anchor) {
            const url = new URL(anchor.getAttribute("href"), baseUrl);
            const match = url.pathname.match(/\/(?:contest|gym)\/(\d+)\/problem\/([^/?#]+)/);
            if (match) {
                const text = normalizeText(anchor.textContent || node.textContent);
                return {
                    index: decodeURIComponent(match[2]),
                    title: text,
                    problemUrl: url.href,
                };
            }
        }

        const text = normalizeText(node.textContent);
        const match = text.match(/^([A-Z][0-9A-Z]*)\.\s+(.+)/);
        if (!match)
            return null;

        return {
            index: match[1],
            title: text,
            problemUrl: "",
        };
    }

    function finalizeSection(section) {
        const wrapper = document.createElement("div");
        for (const node of section.nodes)
            wrapper.appendChild(node);

        return {
            index: section.index,
            title: section.title,
            problemUrl: section.problemUrl,
            html: wrapper.innerHTML,
            text: readableText(wrapper),
            markdown: domToMarkdown(wrapper).trim(),
        };
    }

    function editorialToMarkdown(data) {
        const lines = [
            `# ${data.title || `Codeforces Blog ${data.entryId}`}`,
            "",
            `- 平台：${data.platform}`,
            `- 题解链接：${data.sourceUrl}`,
            `- 作者：${data.author || "未知"}`,
            `- 发布时间：${data.publishedAt || "未知"}`,
            `- 抓取时间：${data.grabbedAt}`,
            `- 脚本版本：${data.scriptVersion}`,
            "",
        ];

        if (data.introMarkdown)
            lines.push("## 前言", "", data.introMarkdown, "");

        if (data.sections.length === 0) {
            lines.push("## 正文", "", data.markdown, "");
        } else {
            for (const section of data.sections) {
                lines.push(`## ${section.title || section.index}`, "");
                if (section.problemUrl)
                    lines.push(`- 原题链接：${section.problemUrl}`, "");
                if (section.markdown)
                    lines.push(section.markdown, "");
            }
        }

        return `${lines.join("\n").replace(/\n{3,}/g, "\n\n").trim()}\n`;
    }

    function cleanupClone(element, baseUrl) {
        const clone = element.cloneNode(true);
        const noiseSelector = [
            "script",
            "style",
            ".html2md-panel",
            ".input-output-copier",
            ".ojb_btn",
            ".translateButton",
            ".popover_content",
            ".monaco-editor",
            "[data-keybinding-context]",
            "[data-mode-id]",
            ".source-copier",
        ].join(",");

        for (const node of clone.querySelectorAll(noiseSelector))
            node.remove();
        for (const node of clone.querySelectorAll("[style]"))
            node.removeAttribute("style");
        for (const anchor of clone.querySelectorAll("a[href]"))
            anchor.href = new URL(anchor.getAttribute("href"), baseUrl).href;
        for (const image of clone.querySelectorAll("img[src]"))
            image.src = new URL(image.getAttribute("src"), baseUrl).href;
        return clone;
    }

    function domToMarkdown(node) {
        if (!node)
            return "";
        if (node.nodeType === Node.TEXT_NODE)
            return node.nodeValue.replace(/\s+/g, " ");
        if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE)
            return "";

        const tag = node.tagName ? node.tagName.toLowerCase() : "";
        if (tag === "script" || tag === "style")
            return "";
        if (tag === "br")
            return "\n";
        if (tag === "pre")
            return `\n\`\`\`\n${preText(node)}\n\`\`\`\n\n`;
        if (tag === "code")
            return `\`${normalizeText(node.textContent)}\``;
        if (tag === "strong" || tag === "b")
            return `**${childMarkdown(node).trim()}**`;
        if (tag === "em" || tag === "i")
            return `*${childMarkdown(node).trim()}*`;
        if (tag === "a") {
            const text = childMarkdown(node).trim() || normalizeText(node.textContent);
            return node.href ? `[${text}](${node.href})` : text;
        }
        if (tag === "img") {
            const alt = node.getAttribute("alt") || "";
            return node.src ? `![${alt}](${node.src})` : "";
        }
        if (/^h[1-6]$/.test(tag)) {
            const level = Number(tag.slice(1));
            return `\n${"#".repeat(level + 1)} ${childMarkdown(node).trim()}\n\n`;
        }
        if (tag === "li")
            return `- ${childMarkdown(node).trim()}\n`;
        if (tag === "ul" || tag === "ol")
            return `\n${childMarkdown(node)}\n`;
        if (tag === "p" || tag === "div" || tag === "section")
            return `\n${childMarkdown(node).trim()}\n\n`;
        if (tag === "table")
            return `\n${normalizeText(node.textContent)}\n\n`;

        return childMarkdown(node);
    }

    function childMarkdown(node) {
        return Array.from(node.childNodes).map(domToMarkdown).join("").replace(/[ \t]+\n/g, "\n");
    }

    function preText(node) {
        return node.textContent.replace(/\r\n/g, "\n").replace(/\u00a0/g, " ").trimEnd();
    }

    function readableText(node) {
        const parts = [];
        appendReadableText(node, parts);
        return parts.join("")
            .replace(/\u00a0/g, " ")
            .replace(/[ \t]+\n/g, "\n")
            .replace(/\n{3,}/g, "\n\n")
            .trim();
    }

    function appendReadableText(node, parts) {
        if (!node)
            return;

        if (node.nodeType === Node.TEXT_NODE) {
            parts.push(node.nodeValue.replace(/\s+/g, " "));
            return;
        }

        if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE)
            return;

        const tag = node.tagName ? node.tagName.toLowerCase() : "";
        if (tag === "script" || tag === "style")
            return;
        if (tag === "br") {
            parts.push("\n");
            return;
        }
        if (tag === "pre") {
            parts.push(`\n${preText(node)}\n`);
            return;
        }
        if (/^h[1-6]$/.test(tag)) {
            parts.push("\n");
            appendChildrenReadableText(node, parts);
            parts.push("\n");
            return;
        }
        if (tag === "li") {
            parts.push("\n- ");
            appendChildrenReadableText(node, parts);
            parts.push("\n");
            return;
        }
        if (tag === "p" || tag === "div" || tag === "section" || tag === "ul" || tag === "ol" || tag === "table") {
            parts.push("\n");
            appendChildrenReadableText(node, parts);
            parts.push("\n");
            return;
        }

        appendChildrenReadableText(node, parts);
    }

    function appendChildrenReadableText(node, parts) {
        for (const child of node.childNodes)
            appendReadableText(child, parts);
    }

    function findAuthor() {
        const node = document.querySelector(".topic .rated-user, .topic .user-red, .topic .user-orange, .topic .user-violet, .topic .user-blue, .topic .user-cyan, .topic .user-green, .topic .user-gray");
        return node ? normalizeText(node.textContent) : "";
    }

    function findPublishedAt() {
        const node = document.querySelector(".topic .format-humantime, .format-humantime");
        return node ? (node.getAttribute("title") || normalizeText(node.textContent)) : "";
    }

    function getMeta(name) {
        const node = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
        return node ? node.getAttribute("content") : "";
    }

    function cleanTitle(title) {
        return normalizeText(title.replace(/\s*-\s*Codeforces\s*$/i, ""));
    }

    function normalizeText(text) {
        return String(text || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
    }

    function downloadText(filename, text, type) {
        const blob = new Blob([text], { type });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function createPanel(title) {
        const old = document.getElementById(PANEL_ID);
        if (old)
            old.remove();

        const panel = document.createElement("div");
        panel.id = PANEL_ID;
        panel.style.cssText = [
            "position:fixed",
            "right:16px",
            "bottom:16px",
            "z-index:99999",
            "width:220px",
            "padding:10px",
            "background:#fff",
            "border:1px solid #b9b9b9",
            "box-shadow:0 2px 10px rgba(0,0,0,.18)",
            "font:13px/1.4 Arial,sans-serif",
            "color:#222",
        ].join(";");

        const heading = document.createElement("div");
        heading.textContent = title;
        heading.style.cssText = "font-weight:bold;margin-bottom:8px;";

        const jsonButton = makeButton();
        const markdownButton = makeButton();
        const status = document.createElement("div");
        status.style.cssText = "margin-top:8px;color:#555;word-break:break-word;";

        panel.append(heading, jsonButton, markdownButton, status);
        document.body.appendChild(panel);
        return { panel, jsonButton, markdownButton, status };
    }

    function makeButton() {
        const button = document.createElement("button");
        button.type = "button";
        button.style.cssText = "display:block;width:100%;margin-top:6px;padding:5px 8px;cursor:pointer;";
        return button;
    }

    main();
})();
