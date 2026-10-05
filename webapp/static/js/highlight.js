// A small Python syntax highlighter. Returns one escaped HTML string per source line, so
// callers can number lines and mark the failing / injected ones.

const KEYWORDS = new Set(("and as async await break class continue def del elif else except finally for from " +
  "global if import in is lambda nonlocal not or pass raise return try while with yield match case").split(" "));
const BUILTINS = new Set(("abs all any bool dict divmod enumerate filter float format frozenset int isinstance " +
  "len list map max min next pow print range reversed round set sorted str sum tuple zip ValueError TypeError " +
  "ZeroDivisionError Exception AssertionError IndexError KeyError math cmath statistics fractions decimal " +
  "itertools functools collections datetime random heapq bisect numpy np Fraction Decimal").split(" "));
const CONSTANTS = new Set(["True", "False", "None", "RESULT"]);

const TOKEN = new RegExp([
  /(#[^\n]*)/.source,                                                                   // 1 comment
  /((?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))/.source, // 2 string
  /((?:\b\d[\d_]*(?:\.\d[\d_]*)?|\.\d+)(?:[eE][+-]?\d+)?j?\b)/.source,                  // 3 number
  /([A-Za-z_][A-Za-z0-9_]*)/.source,                                                     // 4 name
  /([^\sA-Za-z0-9_])/.source,                                                            // 5 operator
].join("|"), "g");

const escapeHtml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/** Wrap text in a span; multi-line tokens are split so every line stays self-contained. */
function wrap(text, cls) {
  return text.split("\n").map((part) => (part ? `<span class="${cls}">${escapeHtml(part)}</span>` : "")).join("\n");
}

export function highlightLines(code) {
  let out = "";
  let last = 0;
  let prevName = "";
  TOKEN.lastIndex = 0;
  let m;
  while ((m = TOKEN.exec(code)) !== null) {
    out += escapeHtml(code.slice(last, m.index));
    last = TOKEN.lastIndex;
    const [text, comment, string, number, name, op] = m;
    if (comment) out += wrap(text, "tok-com");
    else if (string) out += wrap(text, "tok-str");
    else if (number) out += wrap(text, "tok-num");
    else if (name) {
      let cls = "";
      if (name === "assert") cls = "tok-assert";
      else if (KEYWORDS.has(name)) cls = "tok-kw";
      else if (CONSTANTS.has(name)) cls = "tok-const";
      else if (prevName === "def" || prevName === "class") cls = "tok-fn";
      else if (BUILTINS.has(name)) cls = "tok-bi";
      else if (code[TOKEN.lastIndex] === "(") cls = "tok-fn";
      out += cls ? wrap(text, cls) : escapeHtml(text);
      prevName = name;
      continue;
    } else if (op) out += wrap(text, "tok-op");
    if (!/^\s*$/.test(text)) prevName = "";
  }
  out += escapeHtml(code.slice(last));
  return out.replace(/\n$/, "").split("\n");
}
