import { describe, expect, it } from "vitest";

import { classifyScopes, plainTokenize, tokenize } from "@/lib/highlighter";

describe("scope classification", () => {
  it.each([
    [["comment.line.number-sign.python"], "# c", "tk-com"],
    [["meta.function.decorator.python", "entity.name.function.decorator.python"], "traced", "tk-deco"],
    [["meta.function.python", "entity.name.function.python"], "check_limit", "tk-def"],
    [["meta.function-call.python", "meta.function-call.generic.python"], "fetch", "tk-fn"],
    [["meta.function-call.python", "meta.function-call.generic.python"], "Invoice", "tk-type"],
    [["meta.class.python", "entity.name.type.class.python"], "Limiter", "tk-def"],
    [["meta.class.python", "meta.class.inheritance.python", "entity.other.inherited-class.python"], "Base", "tk-type"],
    [["variable.parameter.function.language.python", "variable.parameter.function.language.special.self.python"], "self", "tk-self"],
    [["meta.block.ts", "variable.language.this.ts"], "this", "tk-self"],
    [["meta.function-call.python", "support.function.builtin.python"], "len", "tk-bi"],
    [["meta.return.type.ts", "support.type.primitive.ts"], "number", "tk-bi"],
    [["constant.numeric.dec.python"], "42", "tk-num"],
    [["constant.language.python"], "None", "tk-kw"],
    [["keyword.control.flow.python"], "return", "tk-kw"],
    [["new.expr.ts", "keyword.operator.new.ts"], "new", "tk-kw"],
    [["keyword.operator.arithmetic.python"], "+", "tk-p"],
    [["string.quoted.single.python", "punctuation.definition.string.begin.python"], '"', "tk-str"],
    [["source.python"], "value", null],
  ] as const)("%j %s -> %s", (scopes, text, expected) => {
    expect(classifyScopes(scopes, text)).toBe(expected);
  });
});

describe("tokenize", () => {
  it("falls back to plain identifier-aware tokens", () => {
    const [line] = plainTokenize("x = foo(bar)");
    expect(line?.filter((t) => t.identifier).map((t) => t.text)).toEqual(["x", "foo", "bar"]);
  });

  it("highlights Python with the golden palette", async () => {
    const lines = await tokenize(
      '@traced("x")\nclass A(Base):\n    def run(self, n: int) -> str:\n        return fmt(n)  # done',
      "python",
    );
    const cls = (text: string) => lines.flat().find((t) => t.text === text)?.cls;
    expect(cls("traced")).toBe("tk-deco");
    expect(cls("A")).toBe("tk-def");
    expect(cls("Base")).toBe("tk-type");
    expect(cls("run")).toBe("tk-def");
    expect(cls("self")).toBe("tk-self");
    expect(cls("int")).toBe("tk-bi");
    expect(cls("return")).toBe("tk-kw");
    expect(cls("fmt")).toBe("tk-fn");
    expect(lines[3]?.map((t) => t.text).join("")).toBe("        return fmt(n)  # done");
  });

  it("highlights TypeScript and keeps identifiers as separate tokens", async () => {
    const lines = await tokenize("class R { go(): number { return this.svc.call(new Foo(1)); } }", "typescript");
    const tokens = lines.flat();
    const cls = (text: string) => tokens.find((t) => t.text === text)?.cls;
    expect(cls("R")).toBe("tk-def");
    expect(cls("go")).toBe("tk-def");
    expect(cls("this")).toBe("tk-self");
    expect(cls("call")).toBe("tk-fn");
    expect(cls("Foo")).toBe("tk-type");
    expect(cls("1")).toBe("tk-num");
    expect(tokens.find((t) => t.text === "svc")?.identifier).toBe(true);
  });
});
