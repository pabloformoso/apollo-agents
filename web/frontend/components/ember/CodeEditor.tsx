"use client";
/**
 * The algorave editor — CodeMirror 6, with completions built from the registry.
 *
 * **Plain `@codemirror/*`, never `@strudel/codemirror`.** That package depends
 * on `@strudel/core` and would arrive with its own copy — a second `Pattern`
 * class, the silent failure documented in lib/strudel.ts. Our completions have
 * to know the bank rule, the chromatic/one-shot rule and the live palette
 * anyway, none of which a generic Strudel mode knows.
 *
 * The editor is CONTROLLED from React but CodeMirror owns the document: the
 * value prop is pushed in only when it differs from what the view already
 * holds, or every keystroke would fight a re-render and the cursor would jump.
 * That matters here more than usual — the mind rewrites this buffer while a
 * human may be typing in it.
 */
import { useEffect, useRef } from "react";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, highlightActiveLine } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
  type CompletionContext,
  type CompletionResult,
} from "@codemirror/autocomplete";
import { javascript } from "@codemirror/lang-javascript";
import { syntaxHighlighting, defaultHighlightStyle } from "@codemirror/language";
import { completionsFor } from "@/lib/completions";
import type { Palette } from "@/lib/palette";

export type CodeEditorProps = {
  value: string;
  onChange: (next: string) => void;
  /** Ctrl/Cmd+Enter. The live-coding convention, and it must not be stolen. */
  onEvaluate: () => void;
  /** Completions are built from this. Null until the registry has loaded. */
  palette: Palette | null;
  className?: string;
};

/** Ember tokens, applied to CodeMirror's own class names. */
const emberTheme = EditorView.theme(
  {
    "&": { backgroundColor: "transparent", color: "var(--color-ember-text)", height: "100%" },
    ".cm-content": {
      fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
      fontSize: "13px",
      padding: "16px 0",
    },
    ".cm-gutters": {
      backgroundColor: "transparent",
      color: "color-mix(in srgb, var(--color-ember-text) 24%, transparent)",
      border: "none",
    },
    ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--color-ember-text) 4%, transparent)" },
    ".cm-activeLineGutter": { backgroundColor: "transparent" },
    "&.cm-focused": { outline: "none" },
    ".cm-cursor": { borderLeftColor: "var(--color-ember)" },
    ".cm-selectionBackground, ::selection": {
      backgroundColor: "color-mix(in srgb, var(--color-ember) 25%, transparent)",
    },
    ".cm-tooltip-autocomplete": {
      backgroundColor: "var(--color-surf2)",
      border: "1px solid var(--color-line2)",
      borderRadius: "4px",
      fontFamily: "var(--font-jetbrains-mono), ui-monospace, monospace",
      fontSize: "11.5px",
    },
    ".cm-tooltip-autocomplete ul li[aria-selected]": {
      backgroundColor: "var(--color-ember)",
      color: "var(--color-ink)",
    },
    ".cm-completionDetail": {
      fontStyle: "normal",
      opacity: 0.62,
      marginLeft: "1.2em",
    },
  },
  { dark: true },
);

export function CodeEditor({
  value,
  onChange,
  onEvaluate,
  palette,
  className,
}: CodeEditorProps) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  // Read through refs so the extensions built once always see the CURRENT
  // callbacks and palette — rebuilding the editor on every palette load would
  // throw away the cursor mid-set.
  const onChangeRef = useRef(onChange);
  const onEvaluateRef = useRef(onEvaluate);
  const paletteRef = useRef(palette);
  useEffect(() => {
    onChangeRef.current = onChange;
    onEvaluateRef.current = onEvaluate;
    paletteRef.current = palette;
  }, [onChange, onEvaluate, palette]);

  useEffect(() => {
    if (!host.current || view.current) return;

    const complete = (ctx: CompletionContext): CompletionResult | null => {
      const pal = paletteRef.current;
      if (!pal) return null;
      const before = ctx.state.doc.sliceString(0, ctx.pos);
      const found = completionsFor(before, pal);
      if (!found || found.options.length === 0) return null;
      return {
        from: found.from,
        options: found.options.map((o) => ({
          label: o.label,
          detail: o.detail,
          boost: o.boost,
          type: "keyword",
        })),
      };
    };

    const extensions: Extension[] = [
      lineNumbers(),
      highlightActiveLine(),
      history(),
      closeBrackets(),
      javascript(),
      syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
      // `activateOnTyping` so the list appears as you write a sound name —
      // the point is to not have to remember 61 of them.
      autocompletion({ activateOnTyping: true, override: [complete] }),
      emberTheme,
      EditorView.lineWrapping,
      keymap.of([
        {
          key: "Mod-Enter",
          run: () => {
            onEvaluateRef.current();
            return true;
          },
        },
        ...closeBracketsKeymap,
        ...completionKeymap,
        ...historyKeymap,
        ...defaultKeymap,
      ]),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) onChangeRef.current(u.state.doc.toString());
      }),
    ];

    view.current = new EditorView({
      state: EditorState.create({ doc: value, extensions }),
      parent: host.current,
    });

    return () => {
      view.current?.destroy();
      view.current = null;
    };
    // Built once. `value` is synced by the effect below, not by rebuilding.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push external changes in — the mind applying a proposal, a discard, a
  // palette insertion. Guarded on inequality so typing does not round-trip.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const current = v.state.doc.toString();
    if (current === value) return;
    v.dispatch({ changes: { from: 0, to: current.length, insert: value } });
  }, [value]);

  return <div ref={host} data-testid="buffer" className={className} />;
}
