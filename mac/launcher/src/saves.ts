// Game > Saves: the game's characters (BLUS30443DEMONSS005...) in the port's
// gamedata folder and, read-only, in RPCS3, side by side, with backups, copies
// from RPCS3, .zip export/import and deletes (src-tauri/src/saves.rs). Several
// saves of one kind collapse into a group whose cards are built when opened.
// Every destructive action asks first and backs up.
import { invoke } from "@tauri-apps/api/core";
import { ask, open, save } from "@tauri-apps/plugin-dialog";
import { Key, lang, t } from "./i18n";
import { human } from "./ui";

interface Slot {
  name: string;
  kind: "save";
  title: string;
  subtitle: string;
  detail: string;
  modified: number;
  bytes: number;
  path: string;
  icon: string | null;
  hash: string;
}
interface BackupMeta {
  id: string;
  created: number;
  reason: string;
  side: "port" | "rpcs3";
  user: string;
  slots: string[];
  titles: Record<string, string>;
  bytes: number;
}
interface Overview {
  port: Slot[];
  rpcs3: Slot[];
  rpcs3Users: string[];
  rpcs3User: string;
  backups: BackupMeta[];
  portDir: string;
  rpcs3Dir: string;
  backupsDir: string;
  gameRunning: boolean;
  rpcs3Running: boolean;
}

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let ov: Overview | null = null;
let user = "";
let busy = false;
let opts: { keep: () => number; setKeep: (n: number) => void };
/** The families open now, per side, so a refresh does not close them. */
const openFamilies = new Set<string>();

/** BLUS30443DEMONSS005 -> DEMONSS: the game's character saves. */
const family = (name: string) => name.replace(/^BLUS30443/, "").replace(/\d+$/, "");
const FAMILY_LABEL: Record<string, Key> = { DEMONSS: "saves.family.characters" };

function slotsView(slots: Slot[], side: "port" | "rpcs3", other: Slot[]): HTMLElement[] {
  const groups = new Map<string, Slot[]>();
  for (const s of slots) {
    const f = family(s.name);
    groups.set(f, [...(groups.get(f) ?? []), s]);
  }
  const out: HTMLElement[] = [];
  for (const [f, list] of groups) {
    if (list.length <= 3) {
      out.push(...list.map((s) => slotCard(s, side, other)));
      continue;
    }
    const d = el("details", "slot-family");
    const key = `${side}:${f}`;
    const size = list.reduce((a, s) => a + s.bytes, 0);
    const name = FAMILY_LABEL[f] ? t(FAMILY_LABEL[f]) : f;
    d.append(el("summary", "", t("saves.familySummary", { name, n: list.length, size: human(size) })));
    const fill = () => {
      if (d.open && d.childElementCount === 1) d.append(...list.map((s) => slotCard(s, side, other)));
    };
    d.open = openFamilies.has(key);
    d.addEventListener("toggle", () => {
      if (d.open) openFamilies.add(key);
      else openFamilies.delete(key);
      fill();
    });
    fill();
    out.push(d);
  }
  return out;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text = ""): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

function msg(text: string) {
  $("saves-msg").textContent = text;
}

export async function refresh() {
  try {
    ov = await invoke<Overview>("saves_overview", { user: user || null });
    user = ov.rpcs3User;
  } catch (e) {
    msg(String(e));
  }
  render();
}

function slotName(s: Slot): string {
  return s.subtitle || s.title || s.name;
}

async function run<T>(what: () => Promise<T>, done: (r: T) => string) {
  if (busy) return;
  busy = true;
  render();
  try {
    msg(done(await what()));
  } catch (e) {
    msg(String(e));
  }
  busy = false;
  await refresh();
}

function slotCard(s: Slot, side: "port" | "rpcs3", other: Slot[]): HTMLElement {
  const card = el("div", "slot");
  if (s.icon) {
    const img = el("img", "slot-icon");
    img.src = s.icon;
    img.alt = "";
    card.append(img);
  }
  const body = el("div", "slot-body");
  body.append(el("strong", "", slotName(s)));
  if (s.title && s.subtitle) body.append(el("span", "small muted", s.title));
  body.append(el("span", "small muted", `${s.name} · ${human(s.bytes)} · ${s.modified ? new Date(s.modified * 1000).toLocaleString(lang()) : "?"}`));
  const twin = other.find((o) => o.name === s.name);
  if (twin && twin.hash && s.hash) body.append(el("span", twin.hash === s.hash ? "pill" : "pill warn", t(twin.hash === s.hash ? "saves.same" : "saves.differs")));
  const act = el("div", "row slot-actions");
  const b = (label: string, fn: () => void, cls = "") => {
    const x = el("button", cls, label);
    x.disabled = busy || !!ov?.gameRunning;
    x.addEventListener("click", fn);
    act.append(x);
  };
  const writable = true;
  b(t("saves.backup"), () => run(() => invoke<BackupMeta | null>("saves_backup", { side, user, slot: s.name }), (r) => (r ? t("saves.backedUp", { id: r.id }) : "")));
  // RPCS3's saves are only read: one copies from there, never to there
  if (side === "rpcs3" && writable) {
    b(t("saves.toPort"), async () => {
      const yes = await ask(t(twin ? "saves.copyReplaceAsk" : "saves.copyAsk", { name: slotName(s), to: t("saves.port") }), { title: t("saves.copy"), kind: "warning" });
      if (yes) run(() => invoke<{ backup: string | null }>("saves_copy", { from: "rpcs3", to: "port", user, slot: s.name }), (r) => t("saves.copied") + (r.backup ? " " + t("saves.backedUp", { id: r.backup }) : ""));
    });
  }
  b(t("saves.reveal"), () => invoke("reveal", { path: s.path }), "link");
  if (side === "port" && writable) {
    b(t("saves.delete"), async () => {
      const yes = await ask(t("saves.deleteAsk", { name: slotName(s) }), { title: t("saves.delete"), kind: "warning" });
      if (yes) run(() => invoke<BackupMeta>("saves_delete_slot", { side, user, slot: s.name }), (r) => t("saves.deleted", { id: r.id }));
    }, "link danger-link");
  }
  body.append(act);
  card.append(body);
  return card;
}

const REASONS: Record<string, string> = {
  auto: "saves.reason.auto",
  manual: "saves.reason.manual",
  "before-restore": "saves.reason.restore",
  "before-copy": "saves.reason.copy",
  "before-import": "saves.reason.import",
  "before-delete": "saves.reason.delete",
};

export function render() {
  if (!opts) return;
  const keep = $<HTMLInputElement>("saves-keep");
  if (document.activeElement !== keep) keep.value = String(opts.keep());
  if (!ov) return;
  $("saves-busy").classList.toggle("hidden", !ov.gameRunning);
  for (const id of ["saves-backup-all", "saves-export-zip", "saves-import-zip"]) $<HTMLButtonElement>(id).disabled = busy || ov.gameRunning;
  const port = $("saves-port");
  port.replaceChildren(...(ov.port.length ? slotsView(ov.port, "port", ov.rpcs3) : [el("p", "small muted", t("saves.none"))]));
  const r = $("saves-rpcs3");
  if (!ov.rpcs3Users.length) r.replaceChildren(el("p", "small muted", t("saves.noRpcs3")));
  else r.replaceChildren(...(ov.rpcs3.length ? slotsView(ov.rpcs3, "rpcs3", ov.port) : [el("p", "small muted", t("saves.none"))]));
  const wrap = $("saves-user-wrap");
  wrap.classList.toggle("hidden", ov.rpcs3Users.length < 2);
  const sel = $<HTMLSelectElement>("saves-user");
  sel.replaceChildren(...ov.rpcs3Users.map((u) => {
    const o = el("option", "", u);
    o.value = u;
    return o;
  }));
  sel.value = user;
  const ul = $("saves-backups");
  ul.replaceChildren();
  if (!ov.backups.length) ul.append(el("li", "small muted", t("saves.noBackups")));
  for (const bk of ov.backups) {
    const li = el("li");
    const what = el("div", "what");
    const when = new Date(bk.created * 1000).toLocaleString(lang());
    what.append(el("b", "", `${when} · ${bk.side === "port" ? t("saves.port") : `RPCS3 ${bk.user}`}`));
    const shown = bk.slots.slice(0, 6).map((s) => s.replace(/^BLUS30443/, ""));
    const names = shown.join(", ") + (bk.slots.length > shown.length ? ` +${bk.slots.length - shown.length}` : "");
    what.append(el("span", "msg muted", `${t((REASONS[bk.reason] ?? "saves.reason.manual") as Key)} · ${names} · ${human(bk.bytes)}`));
    li.append(what);
    const restore = el("button", "", t("saves.restore"));
    restore.disabled = busy || ov.gameRunning || bk.side !== "port";
    restore.addEventListener("click", async () => {
      const yes = await ask(t("saves.restoreAsk", { when }), { title: t("saves.restore"), kind: "warning" });
      if (yes) run(() => invoke<{ backup: string | null }>("saves_restore", { id: bk.id, slot: null }), (r) => t("saves.restored") + (r.backup ? " " + t("saves.backedUp", { id: r.backup }) : ""));
    });
    const del = el("button", "link danger-link", t("saves.delete"));
    del.disabled = busy;
    del.addEventListener("click", async () => {
      const yes = await ask(t("saves.deleteBackupAsk", { when }), { title: t("saves.delete"), kind: "warning" });
      if (yes) run(() => invoke("saves_delete_backup", { id: bk.id }), () => "");
    });
    li.append(restore, del);
    ul.append(li);
  }
}

export function initSaves(o: typeof opts) {
  opts = o;
  $("saves-refresh").addEventListener("click", refresh);
  $("saves-user").addEventListener("change", () => {
    user = $<HTMLSelectElement>("saves-user").value;
    refresh();
  });
  $("saves-keep").addEventListener("change", () => {
    const n = Math.max(0, Math.min(100, Math.round(Number($<HTMLInputElement>("saves-keep").value) || 0)));
    opts.setKeep(n);
    render();
  });
  $("saves-backup-all").addEventListener("click", () =>
    run(() => invoke<BackupMeta | null>("saves_backup", { side: "port", user: "", slot: null }), (r) => (r ? t("saves.backedUp", { id: r.id }) : t("saves.none"))));
  $("saves-export-zip").addEventListener("click", async () => {
    const dest = await save({ title: t("saves.exportZip"), defaultPath: "demons-souls-saves.zip", filters: [{ name: "ZIP", extensions: ["zip"] }] });
    if (dest) run(() => invoke<string>("saves_export_zip", { slots: null, dest }), (p) => t("saves.exported", { path: p }));
  });
  $("saves-import-zip").addEventListener("click", async () => {
    const p = await open({ title: t("saves.importZip"), filters: [{ name: "ZIP", extensions: ["zip"] }] });
    if (typeof p !== "string") return;
    const yes = await ask(t("saves.importAsk", { name: t("saves.port") }), { title: t("saves.importZip"), kind: "warning" });
    if (yes) run(() => invoke<{ slots: string[]; backup: string | null }>("saves_import_zip", { path: p }), (r) => t("saves.imported", { n: r.slots.length }) + (r.backup ? " " + t("saves.backedUp", { id: r.backup }) : ""));
  });
  $("saves-open-port").addEventListener("click", () => ov && invoke("reveal", { path: ov.portDir }));
  $("saves-open-rpcs3").addEventListener("click", () => ov && invoke("reveal", { path: ov.rpcs3Dir }));
  $("saves-open-backups").addEventListener("click", () => ov && invoke("reveal", { path: ov.backupsDir }));
}
