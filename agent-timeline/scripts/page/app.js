const LIVE = __LIVE__;
let DATA = __DATA__;
const STATUS = {running: ["Running", "●"], quiet: ["Quiet", "◐"], stalled: ["Stalled", "⚠"], done: ["Done", "✓"]};
// Hook markers: "notable" hides routine runs that printed nothing; the Hooks chip cycles through the modes.
const NOTABLE = new Set(["blocked", "error", "message", "context"]);
const HOOK_MODES = {notable: ["Notable hooks", "all"], all: ["All hooks", "off"], off: ["Hooks off", "notable"]};
const state = {open: new Set(), details: new Set(), hide: new Set(), groups: new Map(), folders: new Map(),
  view: "timeline", file: "", fileMode: "changes", hooks: "notable", q: "", range: "fit"};
const SEVERITY = ["ran", "context", "message", "cancelled", "error", "blocked"];  // least to most, as in HOOK_KINDS
const KEEP = 8, EARLIER = "earlier";  // groups or rows kept outside the Earlier fold; its state key
let foldedIds = new Set();
const groupStatus = agents => ["running", "stalled", "quiet"].find(s => agents.some(a => a.status === s)) || "done";
const tally = agents => Object.keys(STATUS).map(k => [k, agents.filter(a => a.status === k).length]).filter(([, n]) => n)
  .map(([k, n]) => `${n} ${STATUS[k][0].toLowerCase()}`).join(" · ");
const statusOf = a => STATUS[a.status] || ["Idle", "·"];
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
// Copying: the raw text rides in data-copy (escaped), never the coloured HTML. copyable() puts a Copy button
// on a block; copyIcon() is a small button beside an identifier. The page URL is never offered: it holds the token.
const copyable = (text, html, label = "Copy") =>
  `<div class="copyable"><button class="copy" data-copy="${esc(text)}" title="Copy to clipboard">${esc(label)}</button>${html}</div>`;
const copyIcon = (text, title, label = "⧉") => `<button class="copy-icon" data-copy="${esc(text)}" title="${esc(title)}">${label}</button>`;
const dur = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), r = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${String(r).padStart(2, "0")}s` : `${r}s`; };
const kt = n => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
const clock = t => new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"});

function segmentsOf(a) {
  // A running agent is still working: draw its last bar up to now.
  return a.status === "running" ? a.segments.map((s, i, all) => i === all.length - 1 ? [s[0], Math.max(s[1], DATA.now)] : s) : a.segments;
}

// Times on other days than the data's "now" carry their date.
const when = t => new Date(t * 1000).toDateString() === new Date(DATA.now * 1000).toDateString() ? clock(t)
  : new Date(t * 1000).toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});

// Tooltip for one bar: who and how it ended, when, and what it used.
function barTip(a) {
  const tools = Object.entries(a.tools).sort((p, q) => q[1] - p[1]);
  const calls = tools.reduce((sum, [, v]) => sum + v, 0);
  const top = tools.slice(0, 3).map(([k, v]) => `${k.replace(/^mcp__.*?__/, "")} ${v}`).join(", ");
  const [name] = statusOf(a);
  const finish = a.status === "running" ? "still running" : a.status === "done" ? `finished ${when(a.end)}` : `${name.toLowerCase()} since ${when(a.end)}`;
  return `<div class="entry"><b>${esc(a.description)}</b> · <span class="s-${a.status}">${name}</span>${a.result ? "\n" + esc(a.result.slice(0, 200)) : ""}</div>`
    + `<div class="entry">Started ${when(a.start)} · ${finish}\n${dur(a.active)} active</div>`
    + `<div class="entry">${kt(a.tokens_out)} output tokens · ${kt(a.tokens_in)} input (including cached context)\n`
    + `${esc(a.model)}${a.type ? " · " + esc(a.type) : ""}\n${calls} tool call${calls === 1 ? "" : "s"}${top ? ": " + esc(top) : ""}</div>`;
}

// The Outputs tab: a folder tree of changed files with a viewer beside it, then files that several agents
// changed, and commits and pull requests.
const OUTSIDE = "(outside the project)";  // scratch files, temp PR bodies and the like
const fileCache = new Map();  // viewer data by file and its latest change, so polling doesn't refetch it
let viewerKey = "";
const who = a => `<button class="goto" data-goto="${esc(a.id)}">${esc(a.description)}</button>`;
const did = f => [f.writes && `wrote${f.writes > 1 ? ` ×${f.writes}` : ""}`, f.edits && `${f.edits} edit${f.edits > 1 ? "s" : ""}`].filter(Boolean).join(", ");
const flag = x => x.clash ? `<span class="clash" title="Changed by agents that were running at the same time">⚠</span> `
  : x.shared ? `<span class="shared" title="Changed by more than one agent">◆</span> ` : "";
const nameOf = id => id === "main" ? "Main session" : DATA.agents.find(a => a.id === id)?.description || id;

function outputsModel() {
  const m = DATA.main;
  const people = [{...m, id: "main", description: "Main session", status: m.running ? "running" : "idle"}, ...DATA.agents];
  const files = new Map();
  for (const a of people) for (const f of a.files) {
    const key = f.path.toLowerCase();
    if (!files.has(key)) files.set(key, {key, path: f.path, inside: f.inside, by: []});
    files.get(key).by.push({a, f});
  }
  // The main session integrating agents' work is expected; two subagents on one file is worth a look,
  // more so when they ran at the same time (a likely merge conflict or overwrite).
  const together = (a, b) => a.start < b.end && b.start < a.end;
  for (const x of files.values()) {
    const subs = x.by.filter(b => b.a.id !== "main");
    x.shared = x.inside && subs.length > 1;
    x.clash = x.shared && subs.some((b, i) => subs.slice(i + 1).some(c => together(b.a, c.a)));
    x.last = Math.max(...x.by.map(b => b.f.t1));
  }
  return {people, files};
}

function renderOutputs() {
  const {people, files} = outputsModel();
  const q = state.q.toLowerCase(), match = (...parts) => !q || parts.join(" ").toLowerCase().includes(q);
  const all = [...files.values()].filter(x => match(x.path, ...x.by.map(b => b.a.description)));

  // Folder tree; a folder holding only one folder is joined with it ("src/app/admin"), as in most editors.
  const root = {path: "", dirs: new Map(), files: []};
  for (const x of all) {
    const parts = x.inside ? x.path.split("/") : [OUTSIDE, x.path];
    let node = root;
    for (const part of parts.slice(0, -1)) {
      if (!node.dirs.has(part)) node.dirs.set(part, {name: part, path: node.path ? `${node.path}/${part}` : part, dirs: new Map(), files: []});
      node = node.dirs.get(part);
    }
    node.files.push({x, name: parts.at(-1)});
  }
  const count = n => n.files.length + [...n.dirs.values()].reduce((s, d) => s + count(d), 0);
  const many = all.length > 40 && !q;  // big trees start with only the top level open
  const tree = (node, depth) => {
    let html = "";
    const dirs = [...node.dirs.values()].sort((a, b) => (a.name === OUTSIDE) - (b.name === OUTSIDE) || a.name.localeCompare(b.name));
    for (let d of dirs) {
      let label = d.name;
      while (d.name !== OUTSIDE && !d.files.length && d.dirs.size === 1) { d = [...d.dirs.values()][0]; label += `/${d.name}`; }
      const open = state.folders.has(d.path) ? state.folders.get(d.path) : d.name !== OUTSIDE && (!many || depth === 0);
      html += `<div class="tnode dir" data-dir="${esc(d.path)}" data-open="${open}" style="padding-left:${6 + depth * 14}px" title="${esc(label)}">`
        + `<span class="chev">${open ? "▾" : "▸"}</span>${esc(label)} <small>${count(d)}</small></div>`;
      if (open) html += tree(d, depth + 1);
    }
    for (const {x, name} of node.files.sort((a, b) => a.name.localeCompare(b.name)))
      html += `<div class="tnode file${state.file === x.key ? " sel" : ""}" data-file="${esc(x.key)}" style="padding-left:${20 + depth * 14}px" title="${esc(x.path)}">`
        + `${flag(x)}${esc(name)}${x.by.length > 1 ? ` <small>${x.by.length} agents</small>` : ""}</div>`;
    return html;
  };

  const events = [
    ...people.flatMap(a => a.prs.map(p => ({...p, a, pr: true}))).filter(p => match(p.url, p.a.description)),
    ...people.flatMap(a => a.commits.map(c => ({...c, a}))).filter(c => match(c.message, c.a.description)),
  ].sort((x, y) => x.t - y.t);
  const commitCount = events.filter(e => !e.pr).length;
  const changers = new Set(all.flatMap(x => x.by.map(b => b.a.id))).size;
  $("osum").textContent = `${all.length} files changed by ${changers} agent${changers === 1 ? "" : "s"} · ${commitCount} commits · `
    + `${events.length - commitCount} pull requests. Files come from Write and Edit calls; changes made through shell commands are not counted.`;
  const scroll = $("otree").scrollTop;
  $("otree").innerHTML = tree(root, 0) || `<p class="empty">No file changes recorded.</p>`;
  $("otree").scrollTop = scroll;
  renderViewer(files.get(state.file));

  let extra = "";
  if (events.length) extra += `<section><h2>Commits and pull requests</h2><table class="otable">${events.map(e => e.pr
    ? `<tr><td class="t">${when(e.t)}</td><td>${who(e.a)}</td><td colspan="2">Pull request <a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.url.replace("https://github.com/", ""))}</a>${copyIcon(e.url, "Copy the pull request URL")}</td></tr>`
    : `<tr><td class="t">${when(e.t)}</td><td>${who(e.a)}</td><td>${esc(e.message) || "<small>(message not in the command)</small>"}</td>
      <td class="p">${esc([e.branch || e.a.branch, e.hash].filter(Boolean).join(" "))}${e.hash ? copyIcon(e.hash, "Copy the commit hash") : ""}</td></tr>`).join("")}</table></section>`;
  $("oextra").innerHTML = extra;
}

// The viewer re-renders only when the selected file, its latest change, or the mode changes, so polling
// doesn't reset its scroll position or refetch.
function renderViewer(x) {
  // Preview exists only for markdown; on other files that choice shows the current file instead.
  const mode = x && state.fileMode === "preview" && !isMarkdown(x.path) ? "current" : state.fileMode;
  const key = x ? `${x.key}|${x.last}|${mode}` : "";
  if (key === viewerKey) return;
  viewerKey = key;
  const v = $("oviewer");
  if (!x) { v.innerHTML = `<p class="empty">Select a file to see what each agent changed.</p>`; return; }
  const modes = [["changes", "Changes"], ["current", "Current file"], ...(isMarkdown(x.path) ? [["preview", "Preview"]] : [])]
    .map(([m, label]) => `<button class="chip" data-mode="${m}" aria-pressed="${mode === m}">${label}</button>`).join(" ");
  v.innerHTML = `<div class="vhead"><div class="p">${flag(x)}${esc(x.path)}${copyIcon(x.path, "Copy the file path")}</div>
    <div class="vmeta">${x.by.map(b => `${who(b.a)} <small>${did(b.f)} · ${when(b.f.t1)}</small>`).join(" · ")}</div><div>${modes}</div></div>
    <div id="vbody"><p class="empty">${LIVE ? "Loading…" : "File contents need the live view: run the script with --serve."}</p></div>`;
  v.scrollTop = 0;
  if (!LIVE) return;
  const show = d => {
    if (viewerKey !== key) return;
    $("vbody").innerHTML = mode === "changes" ? changesHtml(d) : mode === "preview" ? previewHtml(d) : currentHtml(d, x.path);
    placeCopies($("vbody"));
  };
  const cacheKey = `${x.key}|${x.last}`;
  if (fileCache.has(cacheKey)) return show(fileCache.get(cacheKey));
  fetch(`file.json${location.search}${location.search ? "&" : "?"}path=${encodeURIComponent(x.path)}`,
        {cache: "no-store", headers: {"X-Timeline-Token": TOKEN}})
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => { fileCache.set(cacheKey, d); show(d); })
    .catch(() => { if (viewerKey === key) $("vbody").innerHTML = `<p class="empty">Couldn't load this file.</p>`; });
}

const diffLines = (text, cls, sign) => text ? esc(text).split("\n").map(l => `<span class="${cls}">${sign} ${l}</span>`).join("") : "";
const diffText = e => [[e.old, "-"], [e.new, "+"]].filter(([t]) => t).flatMap(([t, sign]) => t.split("\n").map(l => `${sign} ${l}`)).join("\n");
function changesHtml(d) {
  if (!d.changes.length) return `<p class="empty">No recorded changes.</p>`;
  return d.changes.slice().reverse().map((c, i) => `<div class="change">
    <div class="chead">${when(c.t)} · <button class="goto" data-goto="${esc(c.agent)}">${esc(nameOf(c.agent))}</button> · `
    + `${c.edits ? `edit${c.edits.length > 1 ? ` in ${c.edits.length} places` : ""}` : c.tool === "Write" ? "wrote the whole file" : "notebook cell"}</div>`
    + (c.edits ? c.edits.map(e => copyable(diffText(e), `<pre class="diff">${diffLines(e.old, "del", "-")}${diffLines(e.new, "add", "+")}</pre>`)).join("")
      : `<details${i === 0 ? " open" : ""}><summary>${c.content.split("\n").length} lines</summary>${copyable(c.content, `<pre>${esc(c.content)}</pre>`)}</details>`)
    + `</div>`).join("");
}
const numbered = html => html.split("\n").map((l, i) => `<span class="ln">${i + 1}</span>${l}`).join("\n");
function currentHtml(d, path) {
  const c = d.current;
  if (c.missing) {
    const known = lastKnown(d.changes);
    return `<p class="empty">This file isn't in the project or its worktrees now. It was probably deleted, renamed, or merged into
      another file by a shell command, or left in a worktree that has since been removed; the transcripts can't follow that.</p>`
      + (known === null ? "" : `<p class="sub">Last version an agent wrote, rebuilt from the transcript (its last full write plus later edits):</p>
      ${copyable(known, `<pre class="code">${numbered(highlight(known, path))}</pre>`)}`);
  }
  if (c.binary) return `<p class="empty">Binary file: ${esc(c.path)}</p>`;
  return `<p class="sub">${esc(c.path)}${c.truncated ? " (first 500 KB)" : ""}</p>${copyable(c.text, `<pre class="code">${numbered(highlight(c.text, c.path))}</pre>`)}`;
}
const isMarkdown = path => /\.(md|markdown|mdx)$/i.test(path);
function previewHtml(d) {
  const c = d.current, text = c.missing ? lastKnown(d.changes) : c.binary ? null : c.text;
  if (text === null) return `<p class="empty">Nothing to preview.</p>`;
  return (c.missing ? `<p class="sub">Rebuilt from the transcript: this file isn't in the project now.</p>` : "")
    + copyable(text, `<div class="md">${markdown(text)}</div>`, "Copy markdown");
}

// A small built-in markdown renderer. Everything is escaped first; only http(s) and mailto links are clickable,
// and images are shown as placeholders, so the page never loads anything from elsewhere.
// No step ever runs over markup another step produced: one pass over the raw text swaps code spans, images, links
// and bare URLs for placeholders, each built from its own escaped parts; the rest is escaped, and emphasis is a
// single pass over that escaped text, which holds no tags yet.
const MD_HELD = /`([^`]+)`|!\[([^\]]*)\]\([^)]*\)|\[([^\]]+)\]\(([^)\s]+)[^)]*\)|(https?:\/\/[^\s<>"'`)]+)/g;
const MD_EMPHASIS = /\*\*(?=\S)([^*]*?\S)\*\*|__(?=\S)([^_]*?\S)__|~~(?=\S)([^~]*?\S)~~|(^|[^*\w])\*(?=\S)([^*]*?\S)\*(?!\w)|(^|[^\w])_(?=\S)([^_]*?\S)_(?!\w)/g;
function mdInline(raw) {
  const held = [], hold = html => `\u0000${held.push(html) - 1}\u0000`;
  const link = (url, text) => /^(https?:|mailto:)/i.test(url)
    ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`
    : `<span class="mdlink" title="${esc(url)}">${esc(text)}</span>`;
  const text = raw.replace(/\u0000/g, "").replace(MD_HELD, (_, code, alt, label, url, bare) => hold(
    code !== undefined ? `<code>${esc(code)}</code>`
    : alt !== undefined ? `<span class="mdimg">[image${alt ? ": " + esc(alt) : ""}]</span>`
    : label !== undefined ? link(url, label) : link(bare, bare)));
  return esc(text)
    .replace(MD_EMPHASIS, (_, strong, strong2, del, pre, em, pre2, em2) =>
      strong || strong2 ? `<strong>${strong || strong2}</strong>` : del ? `<del>${del}</del>` : em ? `${pre}<em>${em}</em>` : `${pre2}<em>${em2}</em>`)
    .replace(/\u0000(\d+)\u0000/g, (_, i) => held[i]);
}
const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
function mdList(lines, i) {
  const indent = lines[i].match(/^\s*/)[0].length, ordered = /^\s*\d/.test(lines[i]);
  let html = "";
  while (i < lines.length) {
    const m = lines[i].match(LIST_ITEM);
    if (!m || m[1].length < indent) break;
    if (m[1].length > indent) { const [inner, next] = mdList(lines, i); html = html.replace(/<\/li>$/, inner + "</li>"); i = next; continue; }
    let text = m[3]; i++;
    while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !LIST_ITEM.test(lines[i])) text += " " + lines[i++].trim();
    const task = text.match(/^\[([ xX])\]\s+(.*)$/);
    html += `<li>${task ? `<input type="checkbox" disabled${task[1] === " " ? "" : " checked"}> ${mdInline(task[2])}` : mdInline(text)}</li>`;
  }
  return [ordered ? `<ol>${html}</ol>` : `<ul>${html}</ul>`, i];
}
function markdown(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n"), para = [];
  let html = "", i = 0, m;
  const flush = () => { if (para.length) html += `<p>${mdInline(para.splice(0).join(" "))}</p>`; };
  const cells = l => l.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
  while (i < lines.length) {
    const line = lines[i];
    if ((m = line.match(/^\s*(`{3,}|~{3,})\s*([\w+#.-]*)/))) {
      flush(); const body = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith(m[1])) body.push(lines[i++]);
      i++; html += `<pre class="code">${highlight(body.join("\n"), `x.${m[2] || "txt"}`)}</pre>`;
    } else if (!line.trim()) { flush(); i++; }
    else if ((m = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/))) { flush(); html += `<h${m[1].length}>${mdInline(m[2])}</h${m[1].length}>`; i++; }
    else if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); html += "<hr>"; i++; }
    else if (/^\s*>/.test(line)) {
      flush(); const body = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ""));
      html += `<blockquote>${markdown(body.join("\n"))}</blockquote>`;
    } else if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || "")) {
      flush(); const head = cells(line), rows = []; i += 2;
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
      html += `<table class="mdtable"><thead><tr>${head.map(c => `<th>${mdInline(c)}</th>`).join("")}</tr></thead>`
        + `<tbody>${rows.map(r => `<tr>${r.map(c => `<td>${mdInline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    } else if (LIST_ITEM.test(line)) { flush(); const [list, next] = mdList(lines, i); html += list; i = next; }
    else { para.push(line.trim()); i++; }
  }
  flush();
  return html;
}

// The file as the agents left it: the last whole-file write, with the edits made after it applied in order.
function lastKnown(changes) {
  const start = changes.map(c => c.tool === "Write").lastIndexOf(true);
  if (start < 0) return null;
  let text = changes[start].content;
  for (const c of changes.slice(start + 1)) for (const e of c.edits || []) text = text.replace(e.old, () => e.new);
  return text;
}

// A small built-in highlighter (no third-party code on a page that holds transcripts and a token): comments,
// strings, numbers, keywords and capitalised type names, with comment styles picked by file extension.
const KEYWORDS = new Set(("abstract as async await base bool break case catch char class const continue def default del delete do "
  + "double elif else enum except export extends false final finally float fn for foreach from func function get if impl "
  + "implements import in int interface internal is lambda let long match mod mut namespace new nil none not null object of "
  + "or out override package pass private protected pub public raise readonly ref return sealed self set static string struct "
  + "super switch this throw throws trait true try type typeof uint unsafe use using val var virtual void when where while with yield").split(" "));
function highlight(text, path) {
  const ext = (path.match(/\.([^./\\]+)$/) || [])[1]?.toLowerCase() || "";
  if (/^(md|markdown|txt|log|csv|tsv|rst)$/.test(ext)) return esc(text);
  const hash = /^(py|rb|sh|bash|zsh|ps1|psm1|yml|yaml|toml|r|pl|conf|ini|cfg|env|mk|dockerfile|gitignore)$/.test(ext);
  const markup = /^(html?|xml|xaml|svg|csproj|props|targets|vue)$/.test(ext);
  const comment = markup ? String.raw`<!--[\s\S]*?-->` : hash ? String.raw`#[^\n]*` : ext === "sql" ? String.raw`--[^\n]*|/\*[\s\S]*?\*/`
    : String.raw`//[^\n]*|/\*[\s\S]*?\*/`;
  const strings = String.raw`"{3}[\s\S]*?"{3}|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'` + (/^(js|mjs|cjs|jsx|ts|tsx)$/.test(ext) ? String.raw`|` + "`(?:\\\\.|[^`\\\\])*`" : "");
  const token = new RegExp(`(${comment})|(${strings})|(\\b0x[0-9a-fA-F]+\\b|\\b\\d[\\d_]*(?:\\.\\d+)?(?:[eE][+-]?\\d+)?\\b)|([A-Za-z_$][\\w$]*)`, "g");
  let html = "", last = 0;
  for (const m of text.matchAll(token)) {
    html += esc(text.slice(last, m.index));
    const cls = m[1] ? "hl-c" : m[2] ? "hl-s" : m[3] ? "hl-n" : KEYWORDS.has(m[4]) ? "hl-k" : !markup && /^[A-Z][a-z]/.test(m[4]) ? "hl-t" : "";
    html += cls ? `<span class="${cls}">${esc(m[0])}</span>` : esc(m[0]);
    last = m.index + m[0].length;
  }
  return html + esc(text.slice(last));
}

function selectFile(key) {
  const x = outputsModel().files.get(key); if (!x) return;
  state.file = key;
  const parts = x.inside ? x.path.split("/").slice(0, -1) : [OUTSIDE];
  parts.forEach((_, i) => state.folders.set(parts.slice(0, i + 1).join("/"), true));
  renderOutputs();
  document.querySelector("#otree .file.sel")?.scrollIntoView({block: "nearest"});
}

function range() {
  const agents = DATA.agents, m = DATA.main;
  const liveEnd = m.running ? Math.max(m.end, DATA.now) : m.end;
  let lo, hi;
  if (state.range === "recent") { hi = Math.max(liveEnd, DATA.now); lo = hi - 1800; }
  else if (state.range === "session" || !agents.length) { lo = m.start; hi = liveEnd; }
  else { lo = Math.min(...agents.map(a => a.start)); hi = Math.max(...agents.map(a => segmentsOf(a).at(-1)[1])); }
  const pad = Math.max((hi - lo) * 0.02, 5);
  return [lo - pad, hi + pad];
}

function render() {
  const [lo, hi] = range();
  const x = t => Math.min(100, Math.max(0, (t - lo) / (hi - lo) * 100));
  const bar = (s, e, cls, tip) => e < lo || s > hi ? "" :
    `<div class="bar ${cls}" style="left:${x(s)}%;width:${Math.max(0, x(e) - x(s))}%" data-tip="${esc(tip)}"></div>`;
  const bars = (a, cls) => { const tip = barTip(a); return segmentsOf(a).map(([s, e]) => bar(s, e, cls, tip)).join(""); };
  const steps = [10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600, 43200, 86400, 172800, 604800];
  const maxTicks = Math.max(4, Math.floor($("list").clientWidth * 0.6 / 130));  // more labels on wide screens
  const step = steps.find(s => (hi - lo) / s <= maxTicks) || 1209600;
  const label = t => step >= 86400 ? new Date(t * 1000).toLocaleDateString([], {month: "short", day: "numeric"})
    : hi - lo > 86400 ? new Date(t * 1000).toLocaleString([], {weekday: "short", hour: "2-digit", minute: "2-digit"})
    : new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", ...(step < 60 ? {second: "2-digit"} : {})});
  const tickTimes = [];
  for (let t = Math.ceil(lo / step) * step; t < hi; t += step) tickTimes.push(t);
  const grid = tickTimes.map(t => `<div class="tick" style="left:${x(t)}%"></div>`).join("")
    + DATA.chapters.filter(c => c.t > lo && c.t < hi).map(c => `<div class="chapter" style="left:${x(c.t)}%" title="${esc(c.title)}"></div>`).join("")
    + (LIVE && DATA.now < hi ? `<div class="nowline" style="left:${x(DATA.now)}%" title="now"></div>` : "");

  const counts = {running: 0, quiet: 0, stalled: 0, done: 0};
  DATA.agents.forEach(a => counts[a.status]++);
  const allHooks = [DATA.main, ...DATA.agents].flatMap(a => a.hooks);
  const notableCount = allHooks.filter(h => NOTABLE.has(h.kind)).length;
  $("chips").innerHTML = Object.entries(STATUS).map(([k, [name, icon]]) =>
    `<button class="chip" data-status="${k}" aria-pressed="${!state.hide.has(k)}"><span class="s-${k}">${icon}</span> ${name}<span class="n">${counts[k]}</span></button>`).join(" ")
    + ` <button class="chip" data-hooks aria-pressed="${state.hooks !== "off"}" title="Hook markers: notable only, all, or none (click to cycle)"><span class="tk-message">◆</span> ${HOOK_MODES[state.hooks][0]}<span class="n">${state.hooks === "all" ? allHooks.length : notableCount}</span></button>`;
  // Hooks closer than a marker's width share one marker, coloured by the most severe; its tooltip lists them all.
  const near = 12 / Math.max(200, $("list").clientWidth * 0.65) * 100;  // 12px as a share of the track
  const markers = hooks => {
    if (state.hooks === "off") return "";
    const clusters = [];
    hooks.filter(h => h.t >= lo && h.t <= hi && (state.hooks === "all" || NOTABLE.has(h.kind)))
      .sort((a, b) => a.t - b.t).forEach(h => {
        const last = clusters.at(-1);
        if (last && x(h.t) - x(last.hooks[0].t) < near) last.hooks.push(h); else clusters.push({hooks: [h]});
      });
    return clusters.map(({hooks: hs}) => {
      const kind = hs.map(h => h.kind).reduce((a, b) => SEVERITY.indexOf(b) > SEVERITY.indexOf(a) ? b : a);
      const tip = hs.slice(0, 6).map(h => `<div class="entry"><b>${clock(h.t)} · ${esc(h.event)} · ${esc(h.kind)}</b>${h.hook ? " · " + esc(h.hook) : ""}`
        + (h.texts[0] ? "\n" + esc(h.texts[0].slice(0, 240)) : "") + "</div>").join("")
        + (hs.length > 6 ? `<div class="entry">+${hs.length - 6} more</div>` : "");
      return `<div class="hook k-${kind}${hs.length > 1 ? " multi" : ""}" style="left:${x(hs[0].t)}%" data-tip="${esc(tip)}"></div>`;
    }).join("");
  };

  const q = state.q.toLowerCase();
  const shown = DATA.agents.filter(a => !state.hide.has(a.status) &&
    (!q || [a.description, a.type, a.model, a.result, a.group_label].join(" ").toLowerCase().includes(q)));
  // Agents launched from the same message share a group; one launched alone is a plain row.
  const groups = [];
  shown.forEach(a => { let g = groups.find(g => g.name === a.group); if (!g) groups.push(g = {name: a.group, label: a.group_label, agents: []}); g.agents.push(a); });
  // Finished groups start collapsed in long runs; a search, or the user's own choice, overrides that.
  const groupOpen = g => q ? true : state.groups.has(g.name) ? state.groups.get(g.name)
    : shown.length <= 6 || groupStatus(g.agents) !== "done";

  const m = DATA.main;
  const mainRow = {...m, id: "main", description: "Main session", status: m.running ? "running" : "idle",
    type: "main session", model: m.models.join(", "), depth: 1, background: false};

  // Stalled agents and recent blocked or failed hooks; older ones only count in the stats.
  // A block or failure is cleared once the same hook on the same event has since run without one.
  const bad = h => h.kind === "blocked" || h.kind === "error";
  const urgent = (h, hooks) => bad(h) && DATA.now - h.t < 900
    && !hooks.some(l => l.t > h.t && l.event === h.event && l.hook === h.hook && !bad(l));
  const urgentHooks = a => a.hooks.filter(h => urgent(h, a.hooks));
  const attention = [mainRow, ...DATA.agents].filter(a => a.status === "stalled" || urgentHooks(a).length).map(a =>
    `<button class="goto" data-goto="${esc(a.id)}">${esc(a.description)}</button> <small>(${a.status === "stalled" ? "stalled" : `hook ${urgentHooks(a).at(-1).kind}`})</small>`);
  $("attention").hidden = !attention.length;
  $("attention").innerHTML = attention.length ? `<b>Needs attention:</b> ${attention.join(", ")}` : "";
  const mainOpen = state.open.has("main");
  let html = `<div class="row axis"><span></span><span class="name" style="color:var(--muted);font-size:12px">${shown.length} of ${DATA.agents.length} agents</span>
      <div class="track">${tickTimes.map(t => `<div class="tick" style="left:${x(t)}%">${label(t)}</div>`).join("")}</div><span class="num">active</span></div>
    <div class="row agent" data-id="main" tabindex="0" role="button" aria-expanded="${mainOpen}">
      <span class="badge s-${mainRow.status}" title="${m.running ? "Main session active" : "Main session idle"}">${statusOf(mainRow)[1]}</span>
      <span class="name">Main session<small>${esc(mainRow.model.replace(/^claude-/, ""))}</small></span>
      <div class="track">${grid}${bars(mainRow, "b-main")}${markers(m.hooks)}</div>
      <span class="num">${dur(m.active)}</span></div>${mainOpen ? detail(mainRow) : ""}`;
  if (!DATA.agents.length) html += `<div class="empty">No subagents in this session yet.</div>`;
  else if (!shown.length) html += `<div class="empty">No agents match the filters.</div>`;
  // A collapsible header row; collapsed, it draws all its agents' bars and hooks on one line.
  const hhmm = t => new Date(t * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  const header = (key, label, agents, open, note) => {
    const track = open ? "" : agents.map(a => bars(a, `b-${a.status}`)).join("")
      + markers(agents.flatMap(a => a.hooks));
    return `<div class="row grouprow" data-group="${esc(key)}" tabindex="0" role="button" aria-expanded="${open}">
      <span class="badge chev">${open ? "▾" : "▸"}</span>
      <span class="name" title="${esc(label)}">${esc(label)}<small>${agents.length} agents · ${groupStatus(agents) === "done" ? "all done" : tally(agents)} · ${note}</small></span>
      <div class="track">${grid}${track}</div>
      <span class="num">${dur(agents.reduce((s, a) => s + a.active, 0))}</span></div>`;
  };
  const agentRow = a => {
    const open = state.open.has(a.id);
    return `<div class="row agent" data-id="${a.id}" tabindex="0" role="button" aria-expanded="${open}">
      <span class="badge s-${a.status}" title="${STATUS[a.status][0]}">${STATUS[a.status][1]}</span>
      <span class="name" title="${esc(a.description)}">${"&nbsp;&nbsp;".repeat(Math.max(0, a.depth - 1))}${esc(a.description)}<small>${esc(a.model.replace(/^claude-/, ""))}</small></span>
      <div class="track">${grid}${bars(a, `b-${a.status}${a.status === "running" ? " running" : ""}`)}${markers(a.hooks)}</div>
      <span class="num">${dur(a.active)}</span></div>${open ? detail(a) : ""}`;
  };
  const unit = g => {
    if (g.agents.length === 1) return agentRow(g.agents[0]);
    const open = groupOpen(g);
    return header(g.name, g.label, g.agents, open, hhmm(g.agents[0].start)) + (open ? g.agents.map(agentRow).join("") : "");
  };
  // Long runs fold finished work before the latest KEEP groups or rows into one "Earlier" row.
  // Anything unfinished stays visible, and a search shows every match.
  const foldable = q ? [] : groups.slice(0, -KEEP).filter(g => groupStatus(g.agents) === "done");
  const folded = new Set(foldable.length >= 3 ? foldable : []);
  foldedIds = new Set([...folded].flatMap(g => g.agents.map(a => a.id)));
  if (folded.size) {
    const agents = [...folded].flatMap(g => g.agents), open = state.groups.get(EARLIER) === true;
    const last = Math.max(...agents.map(a => a.end));
    const day = t => new Date(t * 1000).toLocaleDateString([], {month: "short", day: "numeric"});
    const span = day(agents[0].start) === day(last) ? `${hhmm(agents[0].start)}–${hhmm(last)}`
      : `${day(agents[0].start)} ${hhmm(agents[0].start)} – ${day(last)} ${hhmm(last)}`;
    html += header(EARLIER, "Earlier", agents, open, span)
      + (open ? [...folded].map(unit).join("") : "");
  }
  html += groups.filter(g => !folded.has(g)).map(unit).join("");
  const scrolls = new Map([...$("list").querySelectorAll("[data-scroll]")].map(el => [el.dataset.scroll, el.scrollTop]));
  $("list").innerHTML = html;
  for (const d of $("list").querySelectorAll("details[data-key]")) d.open = state.details.has(d.dataset.key);
  balance();
  placeCopies($("list"));
  for (const el of $("list").querySelectorAll("[data-scroll]")) el.scrollTop = scrolls.get(el.dataset.scroll) || 0;

  const agentSecs = DATA.agents.reduce((s, a) => s + a.active, 0);
  $("sub").innerHTML = `${esc(DATA.project)} / ${esc(DATA.session)}${copyIcon(DATA.session, "Copy the session ID")}`
    + copyIcon(`claude --resume ${DATA.session}`, `Copy a command that reopens this session (run it in ${m.cwd || "the project folder"})`, "⧉ resume command");
  $("title").textContent = DATA.title || "Agent timeline";
  document.title = DATA.title ? `${DATA.title} · Agent timeline` : "Agent timeline";
  const blocked = allHooks.filter(h => h.kind === "blocked").length;
  const totals = `Agent time ${dur(agentSecs)} · agent output tokens ${kt(DATA.agents.reduce((s, a) => s + a.tokens_out, 0))}`
    + ` · main output tokens ${kt(m.tokens_out)} · ${allHooks.length} hook events`;
  $("stats").innerHTML = [
    ["Session", `${dur(m.active)} active over ${dur((m.running ? DATA.now : m.end) - m.start)}`],
    ["Agents", tally(DATA.agents) || "none", totals],
    ...(blocked ? [["Blocked hooks", blocked]] : []),
  ].map(([k, v, title]) => `<span${title ? ` title="${esc(title)}"` : ""}>${k}: <b>${v}</b></span>`).join("");
  if (state.view === "outputs") renderOutputs();
}

// The two detail columns share a grid row, so both are as tall as the taller one.
// Give each column's scroll box (activity feed, reply) the slack, so neither leaves empty space.
function balance() {
  const pairs = [...$("list").querySelectorAll(".cols")].flatMap(cols => [...cols.children].map(section =>
    [section, section.querySelector(":scope > .feed, :scope > pre, :scope > .copyable > pre")]).filter(([, box]) => box));
  for (const [, box] of pairs) { box.style.height = ""; box.style.maxHeight = ""; }
  for (const [section, box] of pairs) {
    const used = [...section.children].reduce((h, el) => { const s = getComputedStyle(el);
      return h + el.offsetHeight + parseFloat(s.marginTop) + parseFloat(s.marginBottom); }, 0);
    const slack = section.clientHeight - used;
    if (slack > 1) { const height = box.offsetHeight + slack; box.style.maxHeight = "none"; box.style.height = `${height}px`; }
  }
}
window.addEventListener("resize", () => { if (DATA) render(); });

// Keep each Copy button clear of its block's scrollbar, which CSS alone can't detect.
function placeCopies(root = document) {
  for (const button of root.querySelectorAll(".copyable > .copy")) {
    const box = button.nextElementSibling; if (!box) continue;
    const s = getComputedStyle(box);
    const bar = box.offsetWidth - box.clientWidth - parseFloat(s.borderLeftWidth) - parseFloat(s.borderRightWidth);
    button.style.right = `${8 + Math.max(0, bar)}px`;
  }
}

// One handler for every copy button, in the capture phase so a click never also toggles the row around it.
document.addEventListener("click", async e => {
  const button = e.target.closest("[data-copy]"); if (!button) return;
  e.stopPropagation(); e.preventDefault();
  const text = button.dataset.copy;
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; }
  catch {  // no clipboard API (some file:// snapshots): fall back to a hidden textarea
    const area = Object.assign(document.createElement("textarea"), {value: text});
    area.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(area); area.select();
    try { ok = document.execCommand("copy"); } catch {}
    area.remove();
  }
  const label = button.textContent;
  button.textContent = ok ? (button.classList.contains("copy-icon") ? "✓" : "Copied") : "Copy failed";
  button.classList.add("done");
  setTimeout(() => { button.textContent = label; button.classList.remove("done"); }, 1200);
}, true);

function detail(a) {
  const feed = a.activity.slice().reverse().map(([t, tool, what]) =>
    `<li><span class="t">${clock(t)}</span><span class="tool" title="${esc(tool)}">${esc(tool.replace(/^mcp__.*?__/, ""))}</span><span class="what" title="${esc(what)}">${esc(what)}</span></li>`).join("");
  const tools = Object.entries(a.tools).sort((p, q) => q[1] - p[1]).map(([k, v]) => `${k} ${v}`).join(", ");
  const hooks = a.hooks.slice().reverse().map((h, i) => `<li><div class="head"><span class="t">${clock(h.t)}</span>
      <span title="${esc(h.event)}">${esc(h.event)}</span><span class="tk-${h.kind}">${esc(h.kind)}</span>
      <span title="${esc(h.hook)}">${esc(h.hook)}</span><span class="t">${h.ms ? dur(h.ms / 1000) : ""}</span></div>
      ${h.texts.length ? `<details data-key="hook-${a.id}-${h.t}-${i}"><summary>${esc(h.texts[0].split("\n")[0].slice(0, 120))}</summary>${copyable(h.texts.join("\n\n"), `<pre>${esc(h.texts.join("\n\n"))}</pre>`)}</details>` : ""}</li>`).join("");
  const prompt = a.id === "main" ? "First prompt" : "Prompt";
  return `<div class="detail">
  <p class="statusline"><span class="s-${a.status}">${statusOf(a)[0]}</span> · ${esc(a.type)}${a.background ? " · background" : ""} · ${esc(a.model)}
    · started ${clock(a.start)} · ${dur(a.active)} active${a.segments.length > 1 ? ` in ${a.segments.length} parts` : ""} · last activity ${clock(a.end)}</p>
  <div class="cols">
    <section><h3>Latest activity</h3>${feed ? `<ol class="feed" data-scroll="feed-${a.id}">${feed}</ol>` : `<p class="empty">No tool calls yet.</p>`}</section>
    <section><h3>${a.status === "done" ? "Result" : "Latest reply"}</h3>${a.final ? copyable(a.final, `<pre data-scroll="final-${a.id}">${esc(a.final)}</pre>`) : `<p class="empty">Nothing yet.</p>`}</section>
  </div>
  <details class="more" data-key="more-${a.id}"><summary>More: tokens, tools, ${prompt.toLowerCase()}, hooks (${a.hooks.length})</summary>
    <dl><dt title="Input includes cached context re-read on each turn">Tokens</dt><dd>${kt(a.tokens_in)} in / ${kt(a.tokens_out)} out</dd>
      <dt>Tools</dt><dd>${esc(tools)}</dd>
      <dt>Outputs</dt><dd>${a.files.length} file${a.files.length === 1 ? "" : "s"} changed · ${a.commits.length} commit${a.commits.length === 1 ? "" : "s"}${a.branch ? ` · branch ${esc(a.branch)}` : ""}${a.prs.map(p => ` · <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.url.replace(/^.*\/pull\//, "PR #"))}</a>`).join("")}</dd>
      <dt>Transcript</dt><dd>${esc(a.transcript)}${copyIcon(a.transcript, "Copy the transcript path")}</dd></dl>
    <details data-key="prompt-${a.id}"><summary>${prompt}</summary>${copyable(a.prompt, `<pre data-scroll="prompt-${a.id}">${esc(a.prompt)}</pre>`)}</details>
    <section class="hookbox"><h3>Hooks (${a.hooks.length})</h3>${hooks ? `<ol class="hooks" data-scroll="hooks-${a.id}">${hooks}</ol>` : `<p class="empty">No hook events recorded.</p>`}</section>
  </details></div>`;
}

const ROWS = ".agent, .grouprow";
const rowSelector = row => "group" in row.dataset ? `.grouprow[data-group="${CSS.escape(row.dataset.group)}"]`
  : `.agent[data-id="${CSS.escape(row.dataset.id)}"]`;
function toggle(row) {
  if ("group" in row.dataset) state.groups.set(row.dataset.group, row.getAttribute("aria-expanded") !== "true");
  else { const id = row.dataset.id; state.open.has(id) ? state.open.delete(id) : state.open.add(id); }
  render();
}
$("list").addEventListener("click", e => { const row = e.target.closest(ROWS); if (row) toggle(row); });
$("list").addEventListener("keydown", e => {
  const row = e.target.closest(ROWS);
  if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); const sel = rowSelector(row); toggle(row); document.querySelector(sel)?.focus(); }
});
// Open an agent's row on the timeline, from the attention line or the Outputs tab.
function gotoAgent(e) {
  const id = e.target.closest("[data-goto]")?.dataset.goto; if (!id) return;
  const a = DATA.agents.find(a => a.id === id);
  if (a) { state.groups.set(a.group, true); state.hide.delete(a.status); }
  if (foldedIds.has(id)) state.groups.set(EARLIER, true);
  state.open.add(id); state.q = ""; $("q").value = "";
  setView("timeline");
  document.querySelector(`.agent[data-id="${CSS.escape(id)}"]`)?.scrollIntoView({block: "center"});
}
$("attention").addEventListener("click", gotoAgent);
$("outputs").addEventListener("click", e => {
  const mode = e.target.closest("[data-mode]"), dir = e.target.closest("[data-dir]"), file = e.target.closest("[data-file]");
  if (mode) { state.fileMode = mode.dataset.mode; renderOutputs(); }
  else if (dir) { state.folders.set(dir.dataset.dir, dir.dataset.open !== "true"); renderOutputs(); }
  else if (file) selectFile(file.dataset.file);
  else gotoAgent(e);
});
function setView(view) {
  if (view === "sessions" && state.view !== "sessions") state.back = state.view;
  state.view = view;
  document.querySelector("main").classList.toggle("view-outputs", view === "outputs");
  document.querySelector("main").classList.toggle("view-sessions", view === "sessions");
  if (view === "sessions") { renderSessions(); loadSessions(); return; }
  for (const t of document.querySelectorAll(".tab")) t.setAttribute("aria-selected", String(t.dataset.view === view));
  $("q").placeholder = view === "outputs" ? "Filter files, commits, agents" : "Filter agents";
  if (DATA) render();
}
document.querySelector(".tabs").addEventListener("click", e => { const t = e.target.closest(".tab"); if (t) setView(t.dataset.view); });

// Sessions: step outside the current session to find another. The list comes from the server, which can
// serve any of the user's sessions with the same token; picking one switches the page in place.
let SESSIONS = null;
const currentSession = () => new URLSearchParams(location.search).get("s") || DATA?.session || "";
const ago = t => { const s = Date.now() / 1000 - t; return s < 90 ? "active now" : s < 5400 ? `${Math.round(s / 60)} min ago`
  : s < 129600 ? `${Math.round(s / 3600)} h ago` : new Date(t * 1000).toLocaleDateString([], {month: "short", day: "numeric"}); };
async function loadSessions() {
  try {
    const res = await fetch("sessions.json", {cache: "no-store", headers: {"X-Timeline-Token": TOKEN}});
    if (!res.ok) throw new Error(res.status);
    SESSIONS = await res.json();
  } catch { if (!SESSIONS) $("slist").innerHTML = `<p class="empty">Couldn't load the sessions list.</p>`; return; }
  if (state.view === "sessions") renderSessions();
}
function renderSessions() {
  const here = currentSession();
  $("back").hidden = !DATA;
  $("back").textContent = `Back to ${DATA?.title || "this session"}`;
  if (!SESSIONS) return;
  const q = $("sq").value.toLowerCase();
  const rows = SESSIONS.filter(r => !q || [r.title, r.prompt, r.project].join(" ").toLowerCase().includes(q));
  const projects = new Map();
  for (const r of rows) { if (!projects.has(r.project)) projects.set(r.project, []); projects.get(r.project).push(r); }
  const live = r => Date.now() / 1000 - r.mtime <= 120;
  $("slist").innerHTML = [...projects].map(([project, rs]) => `<div class="sproject">${esc(project)}</div>${rs.map(r =>
    `<button class="srow${r.id === here ? " current" : ""}" data-session="${esc(r.id)}" title="${esc(r.id)}">
      <span class="dot${live(r) ? " live" : ""}" title="${live(r) ? "Active in the last 2 minutes" : ""}"></span>
      <span class="stitle">${esc(r.title || "(untitled)")}${r.id === here ? ` <small class="smeta">· viewing</small>` : ""}</span>
      <span class="smeta">${r.agents ? `${r.agents} agent${r.agents === 1 ? "" : "s"} · ` : ""}${ago(r.mtime)}</span>
      <span class="sprompt">${esc(r.prompt || "")}</span></button>`).join("")}`).join("")
    || `<p class="empty">No sessions match.</p>`;
}
function resetForSession() {
  for (const k of ["open", "details"]) state[k].clear();
  state.groups.clear(); state.folders.clear();
  state.file = ""; state.q = ""; $("q").value = "";
  viewerKey = ""; fileCache.clear(); foldedIds = new Set();
}
function switchSession(id) {
  if (id !== currentSession()) {
    history.pushState(null, "", `?s=${encodeURIComponent(id)}${location.hash}`);
    resetForSession();
    DATA = null;
    $("list").innerHTML = `<p class="empty">Loading…</p>`;
  }
  setView("timeline");
  poll();
}
$("toSessions").addEventListener("click", () => setView("sessions"));
$("back").addEventListener("click", () => setView(state.back || "timeline"));
$("sq").addEventListener("input", renderSessions);
$("slist").addEventListener("click", e => { const row = e.target.closest("[data-session]"); if (row) switchSession(row.dataset.session); });
window.addEventListener("popstate", () => { resetForSession(); DATA = null; setView("timeline"); poll(); });
$("list").addEventListener("toggle", e => {
  const d = e.target; if (!d.dataset?.key) return;
  d.open ? state.details.add(d.dataset.key) : state.details.delete(d.dataset.key);
  balance();
  placeCopies($("list"));
}, true);
$("chips").addEventListener("click", e => {
  const chip = e.target.closest(".chip"); if (!chip) return;
  if ("hooks" in chip.dataset) state.hooks = HOOK_MODES[state.hooks][1];
  else { const k = chip.dataset.status; state.hide.has(k) ? state.hide.delete(k) : state.hide.add(k); }
  render();
});
$("q").addEventListener("input", e => { state.q = e.target.value; render(); });

// Hook and bar tooltips show at once (a native title waits about a second) and stay inside the window.
$("list").addEventListener("mousemove", e => {
  const hook = e.target.closest(".hook, .bar[data-tip]"), tip = $("tip");
  if (!hook) { tip.hidden = true; return; }
  if (tip.hidden || tip.dataset.for !== hook.dataset.tip) { tip.innerHTML = hook.dataset.tip; tip.dataset.for = hook.dataset.tip; tip.hidden = false; }
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = `${Math.max(8, Math.min(e.clientX + 14, innerWidth - w - 8))}px`;
  tip.style.top = `${e.clientY + 18 + h > innerHeight - 8 ? e.clientY - h - 10 : e.clientY + 18}px`;
});
$("list").addEventListener("mouseleave", () => { $("tip").hidden = true; });
$("range").addEventListener("change", e => { state.range = e.target.value; render(); });

// Colour theme: System follows prefers-color-scheme; Light and Dark override it. Remembered like Full width.
const THEME_KEY = "agent-timeline-theme";
function setTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else { theme = "system"; delete document.documentElement.dataset.theme; }
  for (const b of document.querySelectorAll("[data-set-theme]")) b.setAttribute("aria-pressed", String(b.dataset.setTheme === theme));
  try { localStorage.setItem(THEME_KEY, theme); } catch {}
}
try { setTheme(localStorage.getItem(THEME_KEY)); } catch { setTheme("system"); }
document.querySelector(".theme").addEventListener("click", e => { const b = e.target.closest("[data-set-theme]"); if (b) setTheme(b.dataset.setTheme); });

// Full width is remembered in this browser (per server port, since the port is the origin).
const WIDE_KEY = "agent-timeline-wide";
function setWide(on) {
  document.querySelector("main").classList.toggle("wide", on);
  $("wide").setAttribute("aria-pressed", String(on));
  try { localStorage.setItem(WIDE_KEY, on ? "1" : "0"); } catch {}
}
try { setWide(localStorage.getItem(WIDE_KEY) === "1"); } catch { setWide(false); }
$("wide").addEventListener("click", () => { setWide($("wide").getAttribute("aria-pressed") !== "true"); if (DATA) render(); });

function setLive(ok) {
  $("live").className = "live" + (ok ? "" : " off");
  $("live").innerHTML = LIVE ? `<span class="dot"></span>${ok ? "Live" : "Disconnected (the server may have stopped; run /agent-timeline again)"} · updated ${clock(DATA.now)}`
    : `Snapshot taken ${clock(DATA.now)}`;
}
// The live server hands out data only with the per-run token from the URL fragment, which never leaves the browser.
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("t") || "";
async function poll() {
  try {
    const res = await fetch(`data.json${location.search}`, {cache: "no-store", headers: {"X-Timeline-Token": TOKEN}});
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json(); render(); setLive(true);
  } catch {
    if (DATA) setLive(false);
    else $("live").textContent = "Can't load data: open the exact URL the script printed.";
  }
}
if (DATA) { render(); setLive(true); }
if (LIVE) {
  $("crumbs").hidden = false;  // a snapshot holds one session, so there is nowhere to step out to
  poll();
  setInterval(() => { poll(); if (state.view === "sessions") loadSessions(); }, 5000);
}
