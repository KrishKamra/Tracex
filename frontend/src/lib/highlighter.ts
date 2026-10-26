// Grammar-accurate highlighting: Shiki's TextMate grammars produce scopes, and
// classifyScopes maps them onto the golden palette classes (tk-kw, tk-def, ...)
// from tracex-workspace.html. Identifiers stay separate tokens so the inspector
// can attach hover tooltips to them.

import type { Language } from "./types";

export interface CodeToken {
  text: string;
  cls: string | null;
  identifier: boolean;
}
export type CodeLine = CodeToken[];

const IDENT = /^[A-Za-z_$][\w$]*$/;

/** Map a TextMate scope stack (outermost first) to a golden token class. */
export function classifyScopes(scopes: readonly string[], text: string): string | null {
  const inner = scopes[scopes.length - 1] ?? "";
  const any = (prefix: string) => scopes.some((s) => s.startsWith(prefix));
  const anyIncludes = (part: string) => scopes.some((s) => s.includes(part));

  if (any("comment")) return "tk-com";
  if (any("string")) return "tk-str";
  if (
    inner.startsWith("entity.name.function.decorator") ||
    inner.startsWith("punctuation.definition.decorator") ||
    (any("meta.decorator") && (inner.startsWith("entity.name.function") || inner.startsWith("punctuation.decorator")))
  )
    return "tk-deco";
  if (inner.includes("special.self") || inner.includes("special.cls") || inner.startsWith("variable.language.this"))
    return "tk-self";
  if (inner.startsWith("entity.name.type.class") || inner.startsWith("entity.name.class")) return "tk-def";
  if (inner.startsWith("entity.name.function") || inner.startsWith("meta.function-call.generic")) {
    const isCall = anyIncludes("function-call") || anyIncludes("new.expr");
    if (!isCall && inner.startsWith("entity.name.function")) return "tk-def";
    return /^[A-Z]/.test(text) ? "tk-type" : "tk-fn";
  }
  if (inner.startsWith("support.function.builtin") || inner.startsWith("support.type")) return "tk-bi";
  if (inner.startsWith("entity.name.type") || inner.startsWith("entity.other.inherited-class") || inner.startsWith("support.class"))
    return "tk-type";
  if (inner.startsWith("constant.numeric")) return "tk-num";
  if (inner.startsWith("constant.language")) return "tk-kw";
  if (inner.startsWith("keyword.operator.")) {
    return /^keyword\.operator\.(new|expression|logical\.python|word)/.test(inner) ? "tk-kw" : "tk-p";
  }
  if (inner.startsWith("keyword") || inner.startsWith("storage.type") || inner.startsWith("storage.modifier"))
    return "tk-kw";
  if (inner.startsWith("punctuation") || inner.startsWith("meta.brace")) return "tk-p";
  if (IDENT.test(text) && /^[A-Z]/.test(text)) return "tk-type";
  return null;
}

/** Split text into identifier / non-identifier runs sharing one class. */
function pieces(text: string, cls: string | null): CodeToken[] {
  return Array.from(text.matchAll(/[A-Za-z_$][\w$]*|[^A-Za-z_$]+/g), ([t]) => ({
    text: t,
    cls,
    identifier: IDENT.test(t),
  }));
}

/** Unhighlighted fallback used until the grammar loads (or if it fails). */
export function plainTokenize(source: string): CodeLine[] {
  return source.split("\n").map((line) => pieces(line, null));
}

type Highlighter = {
  codeToTokens: (
    code: string,
    options: { lang: string; theme: string; includeExplanation: true },
  ) => { tokens: { content: string; explanation?: { content: string; scopes: { scopeName: string }[] }[] }[][] };
};

let highlighterPromise: Promise<Highlighter> | null = null;

async function getHighlighter(): Promise<Highlighter> {
  highlighterPromise ??= (async () => {
    const [{ createHighlighterCore, createCssVariablesTheme }, { createJavaScriptRegexEngine }] = await Promise.all([
      import("shiki/core"),
      import("shiki/engine/javascript"),
    ]);
    return (await createHighlighterCore({
      themes: [createCssVariablesTheme({ name: "tracex" })],
      langs: [import("shiki/langs/python.mjs"), import("shiki/langs/typescript.mjs"), import("shiki/langs/tsx.mjs")],
      engine: createJavaScriptRegexEngine({ forgiving: true }),
    })) as unknown as Highlighter;
  })();
  return highlighterPromise;
}

const cache = new Map<string, CodeLine[]>();

export async function tokenize(source: string, language: Language): Promise<CodeLine[]> {
  const key = `${language}\u0000${source}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const highlighter = await getHighlighter();
  const { tokens } = highlighter.codeToTokens(source, { lang: language, theme: "tracex", includeExplanation: true });
  const lines = tokens.map((line) =>
    line.flatMap((token) =>
      (token.explanation ?? [{ content: token.content, scopes: [] }]).flatMap((part) =>
        pieces(
          part.content,
          classifyScopes(
            part.scopes.map((s) => s.scopeName).slice(1),
            part.content,
          ),
        ),
      ),
    ),
  );
  cache.set(key, lines);
  return lines;
}
