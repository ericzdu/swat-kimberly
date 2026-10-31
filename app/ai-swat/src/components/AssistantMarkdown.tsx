import type { ReactNode } from 'react';

/** Lightweight markdown for advisor replies (bold, lists, section headers). */
export default function AssistantMarkdown({ text }: { text: string }) {
  const lines = text.split('\n');
  const nodes: ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = (key: string) => {
    if (!listItems.length) return;
    nodes.push(
      <ul key={key} className="list-disc list-inside space-y-1 my-2 text-[var(--se-text-mut)]">
        {listItems.map((item, i) => (
          <li key={i}>{formatInline(item)}</li>
        ))}
      </ul>,
    );
    listItems = [];
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList(`list-${idx}`);
      return;
    }
    if (trimmed.startsWith('- ')) {
      listItems.push(trimmed.slice(2));
      return;
    }
    flushList(`list-${idx}`);

    if (trimmed.startsWith('**') && trimmed.endsWith('**') && trimmed.length > 4) {
      nodes.push(
        <p key={idx} className="font-semibold text-[var(--se-text)] mt-3 first:mt-0">
          {trimmed.slice(2, -2)}
        </p>,
      );
      return;
    }

    nodes.push(
      <p key={idx} className="text-[var(--se-text)] leading-relaxed mt-2 first:mt-0">
        {formatInline(trimmed)}
      </p>,
    );
  });
  flushList('list-end');

  return <div className="space-y-0.5">{nodes}</div>;
}

function formatInline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={i} className="font-semibold text-[var(--se-text)]">
          {part.slice(2, -2)}
        </strong>
      );
    }
    return <span key={i}>{part}</span>;
  });
}
