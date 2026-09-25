import { type ReactNode } from 'react';

// A deliberately small Markdown renderer (roadmap v9, C1). Agent assets are
// headings, lists, paragraphs and fenced code - nothing else - so a library is
// not worth the bundle. Everything is built as React elements; no HTML is
// injected, so an asset cannot smuggle markup into the window.

const INLINE = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    const key = `${keyBase}-${i}`;
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('*') && part.endsWith('*')) return <em key={key}>{part.slice(1, -1)}</em>;
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={key} style={{ backgroundColor: 'var(--bg-code)', border: '1px solid var(--border-card)', color: 'var(--text-primary)', padding: '1px 5px', borderRadius: 4, fontSize: '0.85em' }}>{part.slice(1, -1)}</code>;
    }
    return <span key={key}>{part}</span>;
  });
}

const HEADING_SIZES = ['1.25rem', '1.1rem', '1rem', '0.95rem', '0.9rem', '0.85rem'];

export default function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let code: { lang: string; lines: string[] } | null = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const key = `p-${blocks.length}`;
    blocks.push(<p key={key} style={{ margin: '0 0 12px 0', lineHeight: 1.65 }}>{inline(paragraph.join(' '), key)}</p>);
    paragraph = [];
  };

  const flushList = () => {
    if (!list) return;
    const key = `l-${blocks.length}`;
    const items = list.items.map((item, i) => <li key={`${key}-${i}`} style={{ marginBottom: 4 }}>{inline(item, `${key}-${i}`)}</li>);
    blocks.push(
      list.ordered
        ? <ol key={key} style={{ margin: '0 0 12px 0', paddingLeft: 22, lineHeight: 1.6 }}>{items}</ol>
        : <ul key={key} style={{ margin: '0 0 12px 0', paddingLeft: 22, lineHeight: 1.6 }}>{items}</ul>,
    );
    list = null;
  };

  for (const raw of lines) {
    const line = raw.trimEnd();

    const fence = line.trim().match(/^```(.*)$/);
    if (fence) {
      if (code) {
        blocks.push(
          <pre key={`c-${blocks.length}`} style={{ backgroundColor: 'var(--bg-code)', border: '1px solid var(--border-card)', color: 'var(--text-primary)', borderRadius: 6, padding: 12, overflowX: 'auto', margin: '0 0 12px 0', fontSize: '0.8rem' }}>
            <code>{code.lines.join('\n')}</code>
          </pre>,
        );
        code = null;
      } else {
        flushParagraph();
        flushList();
        code = { lang: fence[1].trim(), lines: [] };
      }
      continue;
    }
    if (code) {
      code.lines.push(raw);
      continue;
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length;
      const key = `h-${blocks.length}`;
      blocks.push(
        <div key={key} style={{ fontSize: HEADING_SIZES[level - 1], fontWeight: 700, color: 'var(--text-primary, #ffffff)', margin: blocks.length ? '18px 0 8px 0' : '0 0 8px 0' }}>
          {inline(heading[2], key)}
        </div>,
      );
      continue;
    }

    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      flushParagraph();
      const ordered = !!numbered;
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push((bullet ? bullet[1] : numbered![1]));
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    flushList();
    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();
  if (code) {
    blocks.push(
      <pre key={`c-${blocks.length}`} style={{ backgroundColor: 'var(--bg-code, #0b0d14)', border: '1px solid var(--border-card, #1e2230)', color: 'var(--text-primary, #e2e8f0)', borderRadius: 6, padding: 12, overflowX: 'auto', margin: '0 0 12px 0', fontSize: '0.8rem' }}>
        <code>{code.lines.join('\n')}</code>
      </pre>,
    );
  }

  return <div style={{ color: 'var(--text-primary, #e2e8f0)', fontSize: '0.88rem' }}>{blocks}</div>;
}
