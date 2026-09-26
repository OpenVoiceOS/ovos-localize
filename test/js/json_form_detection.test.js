// T-4500. The editor renders a key-and-value form for a JSON resource and a
// free-line textarea for a line-based file. The choice used to be a list of
// type names, and word_connectors.json is typed `word_connectors` after its
// own name, so it missed the list: the translator got a free-line box for a
// flat JSON object and typed one value per line. That payload is
// ovos-workshop#659, `d` and `naɣ` over a file whose keys are `and` and `or`.
//
// The predicate is lifted out of index.html by reading the file, so this test
// fails if the page changes and this copy does not.
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, '..', '..', 'index.html'), 'utf8');
// Take the isJsonFile statement and any const the same block defines just
// before it. The match is deliberately loose: if somebody puts the old
// allow-list-only line back, this still extracts it and the cases below fail
// on BEHAVIOUR, which is the point. A shape-only match would report "not
// found" and say nothing about whether the editor is right.
const stmt = html.match(/^[ \t]*const isJsonFile = [\s\S]*?;$/m);
if (!stmt) {
  console.error('FAIL: index.html has no `const isJsonFile = ...` statement at all');
  process.exit(1);
}
const before = html.slice(0, stmt.index);
const helpers = [
  before.match(/^[ \t]*const JSON_FILE_TYPES = [\s\S]*?;$/m),
  before.match(/^[ \t]*const looksLikeJsonResource = [\s\S]*?;$/m),
].filter(Boolean).map(m => m[0]).join('\n');
const block = [helpers + '\n' + stmt[0]];
// Evaluate the page's own lines, with the two inputs the editor has.
const isJsonFile = (fileData, isCreateMode = false) =>
  eval(`(() => { ${block[0]} ; return isJsonFile; })()`);

let fail = 0;
const check = (label, cond) => {
  console.log((cond ? 'PASS ' : 'FAIL ') + label);
  if (!cond) fail = 1;
};

const lang = (file_path, entries) => ({ file_path, entries });
const keyed = (...ks) => ks.map((k, i) => ({ line: i + 1, text: k, key: k, translatable: true }));
const plain = (...ts) => ts.map((t, i) => ({ line: i + 1, text: t }));

// The case that produced ovos-workshop#659.
const wordConnectors = {
  type: 'word_connectors',
  langs: {
    'en-US': lang('ovos_workshop/locale/en-US/word_connectors.json', keyed('and', 'or')),
    kab: lang('ovos_workshop/locale/kab/word_connectors.json', keyed('and', 'or')),
  },
};
check('word_connectors.json gets the key and value form, though its type is in no list',
  isJsonFile(wordConnectors) === true);

// The three named types still work, including one with no lang data at all.
for (const t of ['skill.json', 'settingsmeta', 'resource_json']) {
  check(`a ${t} file is still a JSON file`, isJsonFile({ type: t, langs: {} }) === true);
}

// A JSON resource the target language does not have yet: the source locale's
// keys are what the form is built from, so one lang carrying them is enough.
check('a JSON resource only the source locale has is still a JSON file',
  isJsonFile({
    type: 'euphony', langs: { 'es-ES': lang('locale/es-ES/euphony.json', keyed('a', 'b')) },
  }) === true);

// Line-based files must keep the free-line textarea.
const lineTypes = {
  dialog: lang('locale/en-US/hello.dialog', plain('hello', 'hi')),
  voc: lang('locale/en-US/yes.voc', plain('yes', 'yeah')),
  intent: lang('locale/en-US/what.intent', plain('what is {x}')),
  entity: lang('locale/en-US/color.entity', plain('red', 'blue')),
  rx: lang('locale/en-US/x.rx', plain('(?P<a>.*)')),
  value: lang('locale/en-US/x.value', plain('a|b')),
};
for (const [t, ld] of Object.entries(lineTypes)) {
  check(`a ${t} file keeps the free-line textarea`,
    isJsonFile({ type: t, langs: { 'en-US': ld } }) === false);
}

// Create mode has no fileData: an .entity gap is written as free lines.
check('create mode is still free lines', isJsonFile({ type: 'entity', langs: {} }, true) === false);

// A file with no entries and no .json path is not guessed into a form.
check('an empty line-based file is not a JSON file',
  isJsonFile({ type: 'dialog', langs: { 'en-US': lang('locale/en-US/x.dialog', []) } }) === false);

process.exit(fail);
