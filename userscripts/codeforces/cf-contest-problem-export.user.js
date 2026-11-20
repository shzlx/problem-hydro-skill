// ==UserScript==
// @name         Codeforces Contest Problem Exporter
// @namespace    https://github.com/problem-tools
// @version      0.1.1
// @description  Export all problems from a Codeforces contest page as JSON or Markdown.
// @author       problem-tools
// @match        https://codeforces.com/contest/*
// @match        https://codeforces.com/gym/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
    "use strict";

    const SCRIPT_VERSION = "0.1.1";
    const FETCH_DELAY_MS = 500;
    const PANEL_ID = "problem-tools-cf-contest-export";

    function main() {
        const contest = getContestInfo();
        if (!contest)
            return;

        const links = getProblemLinks(contest);
        const panel = createPanel("CF 比赛题目导出");
        const countText = links.length > 0 ? `发现 ${links.length} 道题` : "未发现题目链接";
        panel.status.textContent = `${contest.kind}/${contest.id}，${countText}`;

        panel.jsonButton.textContent = "导出 JSON";
        panel.markdownButton.textContent = "导出 Markdown";

        panel.jsonButton.addEventListener("click", () => exportContest(contest, "json", panel.status));
        panel.markdownButton.addEventListener("click", () => exportContest(contest, "markdown", panel.status));
    }

    function getContestInfo() {
        const match = location.pathname.match(/^\/(contest|gym)\/(\d+)/);
        if (!match)
            return null;

        return {
            platform: "Codeforces",
            kind: match[1],
            id: match[2],
            url: `${location.origin}/${match[1]}/${match[2]}`,
            title: cleanTitle(getMeta("og:title") || document.title),
        };
    }

    function getProblemLinks(contest, root = document) {
        const result = new Map();
        const pattern = new RegExp(`^/${contest.kind}/${contest.id}/problem/([^/?#]+)$`);

        for (const anchor of root.querySelectorAll("a[href]")) {
            const url = new URL(anchor.getAttribute("href"), location.origin);
            const match = url.pathname.match(pattern);
            if (!match)
                continue;

            const index = decodeURIComponent(match[1]);
            result.set(index, {
                index,
                url: url.href,
                text: normalizeText(anchor.textContent),
            });
        }

        const current = root === document ? location.pathname.match(pattern) : null;
        if (current) {
            const index = decodeURIComponent(current[1]);
            result.set(index, {
                index,
                url: location.href.split("#")[0],
                text: index,
            });
        }

        return Array.from(result.values()).sort((a, b) => compareProblemIndex(a.index, b.index));
    }

    async function exportContest(contest, format, status) {
        let links = getProblemLinks(contest);
        if (links.length === 0) {
            status.textContent = "当前页没有题目链接，尝试读取 problems 页面";
            const problemsUrl = contest.kind === "contest" ? `${contest.url}/problems` : contest.url;
            try {
                const doc = await fetchDocument(problemsUrl);
                links = getProblemLinks(contest, doc);
            } catch (error) {
                status.textContent = `读取 problems 页面失败：${error && error.message ? error.message : error}`;
                return;
            }
        }

        if (links.length === 0) {
            status.textContent = "没有找到题目链接，请在 contest 页面或 problems 页面运行。";
            return;
        }

        const problems = [];
        status.textContent = `开始抓取 1/${links.length}`;

        for (let i = 0; i < links.length; i++) {
            const link = links[i];
            try {
                status.textContent = `抓取 ${link.index} (${i + 1}/${links.length})`;
                const doc = await fetchDocument(link.url);
                problems.push(extractProblem(doc, link.url, link.index));
            } catch (error) {
                problems.push({
                    index: link.index,
                    sourceUrl: link.url,
                    error: String(error && error.message ? error.message : error),
                });
            }
            await sleep(FETCH_DELAY_MS);
        }

        const data = {
            platform: contest.platform,
            type: "contest-problems",
            contestKind: contest.kind,
            contestId: contest.id,
            contestTitle: contest.title,
            contestUrl: contest.url,
            grabbedAt: new Date().toISOString(),
            scriptVersion: SCRIPT_VERSION,
            problemCount: problems.length,
            problems,
        };

        if (format === "json") {
            downloadText(
                `codeforces-${contest.kind}-${contest.id}-problems.json`,
                JSON.stringify(data, null, 2),
                "application/json;charset=utf-8"
            );
        } else {
            downloadText(
                `codeforces-${contest.kind}-${contest.id}-problems.md`,
                contestToMarkdown(data),
                "text/markdown;charset=utf-8"
            );
        }

        status.textContent = `完成：${problems.length} 道题`;
    }

    async function fetchDocument(url) {
        const response = await fetch(url, {
            credentials: "include",
            cache: "no-cache",
        });
        if (!response.ok)
            throw new Error(`HTTP ${response.status}`);

        const html = await response.text();
        return new DOMParser().parseFromString(html, "text/html");
    }

    function extractProblem(doc, sourceUrl, fallbackIndex) {
        const statement = doc.querySelector(".problem-statement");
        if (!statement)
            throw new Error("未找到 .problem-statement，可能页面未加载完整或被访问控制拦截。");

        const header = statement.querySelector(".header");
        const title = normalizeText(textOf(header, ".title")) || fallbackIndex;
        const indexMatch = title.match(/^([A-Z][0-9A-Z]*)\./);
        const index = indexMatch ? indexMatch[1] : fallbackIndex;
        const clone = cleanupClone(statement, sourceUrl);
        const sections = extractProblemSections(clone);
        const samples = extractSamples(statement);

        return {
            index,
            title,
            sourceUrl,
            timeLimit: cleanLimit(textOf(header, ".time-limit"), "time limit per test"),
            memoryLimit: cleanLimit(textOf(header, ".memory-limit"), "memory limit per test"),
            inputFile: cleanLimit(textOf(header, ".input-file"), "input"),
            outputFile: cleanLimit(textOf(header, ".output-file"), "output"),
            statementHtml: clone.innerHTML,
            statementText: normalizeText(clone.textContent),
            sections,
            samples,
        };
    }

    function extractProblemSections(root) {
        const body = document.createElement("div");
        const input = root.querySelector(".input-specification");
        const output = root.querySelector(".output-specification");
        const note = root.querySelector(".note");

        for (const child of Array.from(root.children)) {
            if (child.classList.contains("header"))
                continue;
            if (child.classList.contains("input-specification"))
                continue;
            if (child.classList.contains("output-specification"))
                continue;
            if (child.classList.contains("sample-tests"))
                continue;
            if (child.classList.contains("note"))
                continue;
            body.appendChild(child.cloneNode(true));
        }

        return {
            statementMarkdown: domToMarkdown(body).trim(),
            inputMarkdown: input ? domToMarkdown(input).trim() : "",
            outputMarkdown: output ? domToMarkdown(output).trim() : "",
            noteMarkdown: note ? domToMarkdown(note).trim() : "",
        };
    }

    function extractSamples(statement) {
        const samples = [];
        const sampleRoot = statement.querySelector(".sample-tests");
        if (!sampleRoot)
            return samples;

        const inputs = Array.from(sampleRoot.querySelectorAll(".input pre"));
        const outputs = Array.from(sampleRoot.querySelectorAll(".output pre"));
        const count = Math.max(inputs.length, outputs.length);

        for (let i = 0; i < count; i++) {
            const input = inputs[i] ? extractPreBlock(inputs[i]) : emptyPreBlock();
            const output = outputs[i] ? extractPreBlock(outputs[i]) : emptyPreBlock();
            samples.push({
                index: i + 1,
                input: input.text,
                output: output.text,
                inputLines: input.lines,
                outputLines: output.lines,
                inputOddLineRanges: input.oddLineRanges,
                inputEvenLineRanges: input.evenLineRanges,
                outputOddLineRanges: output.oddLineRanges,
                outputEvenLineRanges: output.evenLineRanges,
                hydroInputFence: `input${i + 1}${input.oddLineRanges ? `|${input.oddLineRanges}` : ""}`,
                hydroOutputFence: `output${i + 1}${output.oddLineRanges ? `|${output.oddLineRanges}` : ""}`,
            });
        }

        return samples;
    }

    function contestToMarkdown(data) {
        const lines = [
            `# ${data.contestTitle || `Codeforces ${data.contestKind} ${data.contestId}`}`,
            "",
            `- 平台：${data.platform}`,
            `- 比赛链接：${data.contestUrl}`,
            `- 抓取时间：${data.grabbedAt}`,
            `- 脚本版本：${data.scriptVersion}`,
            "",
        ];

        for (const problem of data.problems) {
            if (problem.error) {
                lines.push(`## ${problem.index}`, "", `抓取失败：${problem.error}`, "");
                continue;
            }

            lines.push(`## ${problem.title}`, "");
            lines.push(`- 原题链接：${problem.sourceUrl}`);
            if (problem.timeLimit)
                lines.push(`- 时间限制：${problem.timeLimit}`);
            if (problem.memoryLimit)
                lines.push(`- 空间限制：${problem.memoryLimit}`);
            if (problem.inputFile)
                lines.push(`- 输入：${problem.inputFile}`);
            if (problem.outputFile)
                lines.push(`- 输出：${problem.outputFile}`);
            lines.push("");

            appendSection(lines, "题目描述", problem.sections.statementMarkdown);
            appendSection(lines, "输入格式", problem.sections.inputMarkdown);
            appendSection(lines, "输出格式", problem.sections.outputMarkdown);

            if (problem.samples.length > 0) {
                lines.push("### 样例", "");
                for (const sample of problem.samples) {
                    lines.push(`#### 样例 ${sample.index} 输入`, "", `\`\`\`${sample.hydroInputFence}`, sample.input, "```", "");
                    lines.push(`#### 样例 ${sample.index} 输出`, "", `\`\`\`${sample.hydroOutputFence}`, sample.output, "```", "");
                }
            }

            appendSection(lines, "说明", problem.sections.noteMarkdown);
        }

        return `${lines.join("\n").replace(/\n{3,}/g, "\n\n").trim()}\n`;
    }

    function appendSection(lines, title, content) {
        if (!content)
            return;
        lines.push(`### ${title}`, "", content, "");
    }

    function cleanupClone(element, baseUrl) {
        const clone = element.cloneNode(true);
        for (const node of clone.querySelectorAll("script, style"))
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
            return `\n\`\`\`text\n${preText(node)}\n\`\`\`\n\n`;
        if (tag === "code")
            return `\`${normalizeText(node.textContent)}\``;
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
            return `\n${"#".repeat(level + 2)} ${childMarkdown(node).trim()}\n\n`;
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
        return extractPreBlock(node).text;
    }

    function extractPreBlock(node) {
        const lineNodes = Array.from(node.querySelectorAll(".test-example-line"));
        if (lineNodes.length === 0) {
            const text = textWithBreaks(node).replace(/\r\n/g, "\n").replace(/\u00a0/g, " ").trimEnd();
            const lines = text.length > 0 ? text.split("\n") : [];
            return {
                text,
                lines,
                oddLineRanges: "",
                evenLineRanges: "",
                lineGroups: [],
            };
        }

        const lines = [];
        const lineGroups = [];

        for (let i = 0; i < lineNodes.length; i++) {
            const lineNode = lineNodes[i];
            const group = getSampleLineGroup(lineNode);
            lines.push(lineNode.textContent.replace(/\u00a0/g, " ").trimEnd());
            lineGroups.push({
                line: i + 1,
                group: group.number,
                parity: group.parity,
            });
        }

        return {
            text: lines.join("\n"),
            lines,
            oddLineRanges: buildRanges(lineGroups.filter(item => item.parity === "odd").map(item => item.line)),
            evenLineRanges: buildRanges(lineGroups.filter(item => item.parity === "even" && item.group !== 0).map(item => item.line)),
            lineGroups,
        };
    }

    function emptyPreBlock() {
        return {
            text: "",
            lines: [],
            oddLineRanges: "",
            evenLineRanges: "",
            lineGroups: [],
        };
    }

    function getSampleLineGroup(node) {
        const classes = Array.from(node.classList);
        const lineClass = classes.find(name => /^test-example-line-\d+$/.test(name));
        const number = lineClass ? Number(lineClass.replace("test-example-line-", "")) : null;
        let parity = "";
        if (classes.includes("test-example-line-odd"))
            parity = "odd";
        if (classes.includes("test-example-line-even"))
            parity = "even";

        return { number, parity };
    }

    function buildRanges(lines) {
        if (lines.length === 0)
            return "";

        const ranges = [];
        let left = lines[0];
        let right = lines[0];

        for (let i = 1; i < lines.length; i++) {
            if (lines[i] === right + 1) {
                right = lines[i];
            } else {
                ranges.push(formatRange(left, right));
                left = lines[i];
                right = lines[i];
            }
        }

        ranges.push(formatRange(left, right));
        return ranges.join(",");
    }

    function formatRange(left, right) {
        return left === right ? String(left) : `${left}-${right}`;
    }

    function textWithBreaks(node) {
        let result = "";
        for (const child of node.childNodes) {
            if (child.nodeType === Node.TEXT_NODE) {
                result += child.nodeValue;
            } else if (child.nodeType === Node.ELEMENT_NODE && child.tagName.toLowerCase() === "br") {
                result += "\n";
            } else {
                result += textWithBreaks(child);
            }
        }
        return result;
    }

    function textOf(root, selector) {
        if (!root)
            return "";
        const node = root.querySelector(selector);
        return node ? normalizeText(node.textContent) : "";
    }

    function cleanLimit(text, prefix) {
        return normalizeText(text.replace(new RegExp(`^${escapeRegExp(prefix)}`, "i"), ""));
    }

    function getMeta(name) {
        const node = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
        return node ? node.getAttribute("content") : "";
    }

    function cleanTitle(title) {
        return normalizeText(title.replace(/\s*-\s*Codeforces\s*$/i, "").replace(/^Dashboard\s*-\s*/i, ""));
    }

    function normalizeText(text) {
        return String(text || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
    }

    function compareProblemIndex(a, b) {
        return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
    }

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
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

    function escapeRegExp(text) {
        return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    main();
})();
