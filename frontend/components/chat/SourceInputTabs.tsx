"use client";

import { useState, type ChangeEvent } from "react";

export type PendingSourceInput =
  | { type: "pdf"; file: File; label: string }
  | { type: "txt"; file: File; label: string }
  | { type: "youtube"; url: string; label: string }
  | { type: "website"; url: string; label: string }
  | { type: "pasted_text"; text: string; label: string };

type Tab = "file" | "youtube" | "website" | "text";

const TABS: { key: Tab; label: string }[] = [
  { key: "file", label: "Upload File" },
  { key: "youtube", label: "YouTube Link" },
  { key: "website", label: "Website Link" },
  { key: "text", label: "Paste Text" },
];

export function SourceInputTabs({ onAdd }: { onAdd: (input: PendingSourceInput) => void }) {
  const [tab, setTab] = useState<Tab>("file");
  const [linkValue, setLinkValue] = useState("");
  const [textValue, setTextValue] = useState("");

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const ext = file.name.toLowerCase().split(".").pop();
    const type = ext === "pdf" ? "pdf" : "txt";
    onAdd({ type, file, label: file.name });
    e.target.value = "";
  };

  const onAddLink = () => {
    const url = linkValue.trim();
    if (!url) return;
    onAdd({ type: tab as "youtube" | "website", url, label: url });
    setLinkValue("");
  };

  const onAddText = () => {
    const text = textValue.trim();
    if (!text) return;
    onAdd({ type: "pasted_text", text, label: text.slice(0, 60) });
    setTextValue("");
  };

  return (
    <div>
      <div className="source-inputs">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`source-tab ${tab === t.key ? "active" : ""}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "file" && (
        <label className="upload-dropzone" style={{ display: "block", marginBottom: 20 }}>
          <input type="file" accept=".pdf,.txt" onChange={onFileChange} hidden />
          Click to add a .pdf or .txt file
        </label>
      )}

      {(tab === "youtube" || tab === "website") && (
        <div className="source-add-row">
          <input
            className="text-input"
            placeholder={tab === "youtube" ? "https://youtube.com/watch?v=..." : "https://example.com/article"}
            value={linkValue}
            onChange={(e) => setLinkValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAddLink()}
          />
          <button type="button" className="btn" onClick={onAddLink}>
            Add
          </button>
        </div>
      )}

      {tab === "text" && (
        <div style={{ marginBottom: 20 }}>
          <textarea
            className="textarea-input"
            placeholder="Paste text here..."
            value={textValue}
            onChange={(e) => setTextValue(e.target.value)}
          />
          <button type="button" className="btn" style={{ marginTop: 8 }} onClick={onAddText}>
            Add
          </button>
        </div>
      )}
    </div>
  );
}
