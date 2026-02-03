import React, { useEffect, useMemo, useRef, useState } from 'react';
import Modal from './Modal';
import { GLOSSARY, type GlossaryEntry } from '../glossary';

function matches(entry: GlossaryEntry, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return (
    entry.term.toLowerCase().includes(needle) ||
    entry.short.toLowerCase().includes(needle) ||
    entry.detail.toLowerCase().includes(needle) ||
    (entry.tags ?? []).some((t) => t.toLowerCase().includes(needle))
  );
}

export default function GlossaryModal({
  open,
  initialQuery,
  onClose,
}: {
  open: boolean;
  initialQuery?: string;
  onClose: () => void;
}) {
  const [q, setQ] = useState(initialQuery ?? '');
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setQ(initialQuery ?? '');
    // focus after mount
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [open, initialQuery]);

  const filtered = useMemo(() => GLOSSARY.filter((e) => matches(e, q)), [q]);

  return (
    <Modal open={open} title="용어사전" onClose={onClose}>
      <div className="glossaryTop">
        <input
          ref={inputRef}
          className="glossarySearch"
          placeholder="예: RSI, ATR, MDD, Fill rate..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div className="muted" style={{ marginTop: 8 }}>
          {filtered.length}개 항목
        </div>
      </div>

      <div className="glossaryList">
        {filtered.map((e) => (
          <div key={e.term} className="glossaryItem">
            <div className="glossaryTerm">{e.term}</div>
            <div className="muted">{e.short}</div>
            <div style={{ marginTop: 8, lineHeight: 1.45 }}>{e.detail}</div>
            {e.tags && e.tags.length > 0 ? (
              <div className="glossaryTags">
                {e.tags.map((t) => (
                  <span key={t} className="tag">
                    {t}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </Modal>
  );
}
