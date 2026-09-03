import { ChevronDown, ChevronRight, File, Folder, FolderOpen } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

import { FILE_STATUS_LABEL, type DiffFileStatus, type TreeNode } from "../../lib/changes";

// File-icon tint by status; the counts + tooltip carry the exact meaning.
const STATUS_CLS: Record<DiffFileStatus, string> = {
  A: "text-success",
  M: "text-muted-foreground",
  D: "text-destructive",
};

/** The commit page's left file tree — a clean nested folder view (shadcn.io
 *  ai/file-tree idiom: chevron + folder/file icon + mono name). Clicking a file
 *  selects it (scrolls its diff into view). Status shows as icon tint + counts +
 *  a tooltip rather than cryptic letters. */
export function FileTree({
  nodes,
  selected,
  onSelect,
}: {
  nodes: TreeNode[];
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  return (
    <ul className="flex flex-col gap-px">
      {nodes.map((node) =>
        node.type === "dir" ? (
          <TreeDir key={node.path} node={node} selected={selected} onSelect={onSelect} depth={0} />
        ) : (
          <TreeFile key={node.path} node={node} selected={selected} onSelect={onSelect} depth={0} />
        ),
      )}
    </ul>
  );
}

function TreeDir({
  node,
  selected,
  onSelect,
  depth,
}: {
  node: Extract<TreeNode, { type: "dir" }>;
  selected: string | null;
  onSelect: (path: string) => void;
  depth: number;
}) {
  const [open, setOpen] = useState(true);
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 rounded-md border-0 bg-transparent py-1 pr-2 text-left hover:bg-muted/40"
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        {open ? (
          <ChevronDown className="size-3 shrink-0 text-muted-foreground/50" />
        ) : (
          <ChevronRight className="size-3 shrink-0 text-muted-foreground/50" />
        )}
        {open ? (
          <FolderOpen className="size-3.5 shrink-0 text-primary/70" />
        ) : (
          <Folder className="size-3.5 shrink-0 text-primary/70" />
        )}
        <span className="flex-1 whitespace-nowrap font-mono text-[12px] text-foreground/80">
          {node.name}
        </span>
      </button>
      {open && (
        <ul className="flex flex-col gap-px">
          {node.children.map((child) =>
            child.type === "dir" ? (
              <TreeDir key={child.path} node={child} selected={selected} onSelect={onSelect} depth={depth + 1} />
            ) : (
              <TreeFile key={child.path} node={child} selected={selected} onSelect={onSelect} depth={depth + 1} />
            ),
          )}
        </ul>
      )}
    </li>
  );
}

function TreeFile({
  node,
  selected,
  onSelect,
  depth,
}: {
  node: Extract<TreeNode, { type: "file" }>;
  selected: string | null;
  onSelect: (path: string) => void;
  depth: number;
}) {
  const active = selected === node.path;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        aria-current={active}
        title={`${FILE_STATUS_LABEL[node.status]} · +${node.adds} −${node.dels}`}
        className={cn(
          "flex w-full items-center gap-1.5 rounded-md border-0 py-1 pr-2 text-left transition-colors hover:bg-muted/40",
          active ? "bg-primary/10 text-foreground" : "bg-transparent",
        )}
        style={{ paddingLeft: `${depth * 14 + 26}px` }}
      >
        <File className={cn("size-3.5 shrink-0", STATUS_CLS[node.status])} />
        <span className="flex-1 whitespace-nowrap font-mono text-[12px] text-foreground/80">
          {node.name}
        </span>
        <span className="shrink-0 font-mono text-[10px] tabular-nums">
          {node.adds > 0 && <span className="text-success/70">+{node.adds}</span>}
          {node.adds > 0 && node.dels > 0 ? " " : ""}
          {node.dels > 0 && <span className="text-destructive/70">−{node.dels}</span>}
        </span>
      </button>
    </li>
  );
}
