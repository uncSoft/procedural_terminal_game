/**
 * The shared library for the Monster & Item Maker (docs/maker): where its Save button puts what people make, so
 * everyone sees it in the page's Library whether or not it's in the game yet. It runs free as a Google Apps Script
 * web app and keeps one row per creation in a Google Sheet, which doubles as the place to look after them.
 *
 * Setting it up, once:
 *   1. Make a Google Sheet (sheets.new) and call it, say, "Maker saves".
 *   2. Extensions → Apps Script. Replace everything in Code.gs with this file, and save.
 *   3. Deploy → New deployment → Select type: Web app. Execute as: Me. Who has access: Anyone. Deploy, and allow
 *      what it asks for (Google warns that the app isn't verified: it's yours, so Advanced → Go to …).
 *   4. Copy the web app URL (it ends in /exec) into docs/maker/config.json as "saves": {"url": "<that URL>"},
 *      then commit and push. The page's Save now sends things here, and its Library shows them.
 * After changing this code: Deploy → Manage deployments → Edit → Version: New version → Deploy (the URL stays).
 *
 * Looking after it: each row is one creation, with its number, name, type, who made it and when. The number never
 * changes or gets used again, so "uv run ptg import --saves 12" always means the same one. Type anything in a row's
 * "hide" cell to take it out of the Library (saving it again doesn't bring it back); clear the cell to show it
 * again. Deleting a row removes it for good.
 *
 * What the page sends and gets back, as JSON:
 *   GET               → {"creations": [{id, no, saved, type, fields, by, made, base?, art, small?}, ...]},
 *                       newest first (small: an item's 12x12 version, drawn by hand)
 *   POST (plain text) {"id", "secret", "creation"} saves a creation; the same id and secret update it later
 *                     {"id", "secret", "remove": true} takes it out
 *                     → {"ok": true, "id", "no", "saved"} or {"ok": false, "error": "..."}
 * The secret never leaves the browser that made the creation except to prove it's theirs (only a fingerprint of it
 * is kept here), so nobody else can change or remove it.
 */

const SHEET = "Saves";
const COLUMNS = ["no", "name", "type", "by", "saved", "hide", "id", "creation", "key"];
const MAX_ROWS = 1000;   // creations kept at most
const MAX_SIZE = 40000;  // characters of JSON per creation (a cell holds 50,000)
const LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const FIELDS = {  // what the maker sets, and what the game reads
  monster: {name: "text", hp: "number", defense: "number", attack: "number", damage: "text", xp: "number",
            tier: "number", tags: "list", weak: "list", intelligent: "flag", tell: "text", desc: "text"},
  item: {name: "text", kind: "text", damage: "text", defense: "number", heal: "number", escape: "flag",
         tier: "number", tags: "list", desc: "text"},
};
const col = name => COLUMNS.indexOf(name);

function doGet() {
  const creations = [];
  rows().forEach(row => {
    if (String(row[col("hide")]).trim()) return;
    try {
      const creation = JSON.parse(row[col("creation")]);
      creation.id = String(row[col("id")]);
      creation.no = Number(row[col("no")]) || undefined;
      creation.saved = when(row[col("saved")]);
      creations.push(creation);
    } catch (e) {
      // not one of ours: a row typed in by hand, say
    }
  });
  creations.sort((a, b) => (a.saved < b.saved ? 1 : a.saved > b.saved ? -1 : 0));
  return reply({creations});
}

function doPost(e) {
  let request;
  try {
    request = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ok: false, error: "that wasn't a creation"});
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return reply({ok: false, error: "the library is busy, try again"});
  try {
    return reply(handle(request || {}));
  } finally {
    lock.releaseLock();
  }
}

function handle(request) {
  const id = String(request.id || ""), secret = String(request.secret || "");
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{7,63}$/.test(id) || secret.length < 16 || secret.length > 200) {
    return {ok: false, error: "it needs an id and a secret"};
  }
  const sheet = saves(), all = rows(sheet), key = fingerprint(secret);
  const at = all.findIndex(row => String(row[col("id")]) === id);
  if (at >= 0 && String(all[at][col("key")]) !== key) return {ok: false, error: "someone else saved that one"};
  if (request.remove) {
    if (at >= 0) sheet.deleteRow(at + 2);
    return {ok: true, id};
  }
  const creation = clean(request.creation);
  if (typeof creation === "string") return {ok: false, error: creation};
  if (at < 0 && all.length >= MAX_ROWS) return {ok: false, error: "the library is full"};
  const saved = new Date(), row = COLUMNS.map(() => "");
  row[col("no")] = (at >= 0 && Number(all[at][col("no")])) || nextNumber(all);
  row[col("name")] = plain(creation.fields.name);
  row[col("type")] = creation.type;
  row[col("by")] = plain(creation.by);
  row[col("saved")] = saved;
  row[col("hide")] = at >= 0 ? plain(String(all[at][col("hide")])) : "";
  row[col("id")] = id;
  row[col("creation")] = JSON.stringify(creation);
  row[col("key")] = key;
  const range = sheet.getRange(at >= 0 ? at + 2 : all.length + 2, 1, 1, COLUMNS.length);
  range.setNumberFormats([COLUMNS.map(name => ({no: "0", saved: "yyyy-mm-dd hh:mm"}[name] || "@"))]);
  range.setValues([row]);
  return {ok: true, id, no: row[col("no")], saved: saved.toISOString()};
}

// The next creation's number: one more than any so far, even ones whose rows have been deleted.
function nextNumber(all) {
  const props = PropertiesService.getScriptProperties();
  const highest = all.reduce((most, row) => Math.max(most, Number(row[col("no")]) || 0), 0);
  const next = Math.max(Number(props.getProperty("next")) || 1, highest + 1);
  props.setProperty("next", String(next + 1));
  return next;
}

// A creation as the page sent it, keeping only what the maker makes; or what's wrong with it.
function clean(c) {
  if (!c || (c.type !== "monster" && c.type !== "item")) return "a creation is a monster or an item";
  const fields = cleanFields(c.type, c.fields || {}), by = String(c.by || "").trim();
  if (!String(fields.name || "").trim() || fields.name.length > 40) return "it needs a name (up to 40 letters)";
  if (!by || by.length > 40) return "it needs who made it (up to 40 letters)";
  const out = {v: 1, type: c.type, fields, by, made: String(c.made || "").slice(0, 10)};
  if (c.base) out.base = String(c.base).slice(0, 40);
  if (c.art) {
    if (!goodArt(c.art)) return "the drawing is damaged";
    out.art = {w: c.art.w, h: c.art.h, palette: c.art.palette, frames: c.art.frames};
  } else if (!out.base) {
    return "it needs a drawing";
  }
  if (c.small && c.type === "item") {  // an item's 12x12 version, drawn by hand for the inventory
    if (!goodArt(c.small) || c.small.w !== 12 || c.small.h !== 12) return "the small drawing is damaged";
    out.small = {w: 12, h: 12, palette: c.small.palette, frames: c.small.frames};
  }
  if (JSON.stringify(out).length > MAX_SIZE) return "that's too big to save";
  return out;
}

function cleanFields(type, fields) {
  const out = {};
  Object.keys(FIELDS[type]).forEach(name => {
    const value = fields[name], kind = FIELDS[type][name];
    if (kind === "text" && typeof value === "string" && value.trim()) out[name] = value.slice(0, 400);
    if (kind === "number" && typeof value === "number" && isFinite(value)) out[name] = Math.round(value);
    if (kind === "flag" && typeof value === "boolean") out[name] = value;
    if (kind === "list" && Array.isArray(value)) {
      out[name] = value.filter(v => typeof v === "string" && v.trim()).map(v => v.slice(0, 40)).slice(0, 30);
    }
  });
  return out;
}

// Pixel art the way the maker stores it: rows of palette letters, "." for see-through.
function goodArt(art) {
  const sized = Number.isInteger(art.w) && Number.isInteger(art.h) && art.w >= 8 && art.w <= 64 && art.h >= 8 &&
    art.h <= 64;
  if (!sized || !Array.isArray(art.palette) || art.palette.length > LETTERS.length ||
      !art.palette.every(c => /^#[0-9a-fA-F]{6}$/.test(c)) ||
      !Array.isArray(art.frames) || art.frames.length < 1 || art.frames.length > 4) {
    return false;
  }
  const letters = new RegExp(`^[.${LETTERS.slice(0, art.palette.length)}]*$`);
  return art.frames.every(rows => Array.isArray(rows) && rows.length === art.h &&
    rows.every(row => typeof row === "string" && row.length === art.w && letters.test(row)));
}

function saves() {
  const book = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = book.getSheetByName(SHEET);
  if (!sheet) {
    sheet = book.insertSheet(SHEET);
    sheet.getRange(1, 1, 1, COLUMNS.length).setValues([COLUMNS]).setFontWeight("bold");
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function rows(sheet) {
  sheet = sheet || saves();
  const last = sheet.getLastRow();
  return last < 2 ? [] : sheet.getRange(2, 1, last - 1, COLUMNS.length).getValues();
}

function fingerprint(secret) {
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, secret, Utilities.Charset.UTF_8);
  return "k" + Utilities.base64EncodeWebSafe(digest);
}

// Words people typed, kept as words: the sheet would take "=..." for a formula.
function plain(text) {
  return /^[=+\-@]/.test(text) ? "'" + text : text;
}

function when(value) {
  return value instanceof Date ? value.toISOString() : String(value);
}

function reply(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}
