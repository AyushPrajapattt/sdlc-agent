// Repo tree and file helpers over the mock graph.
import { FILES, NODES } from "./data";

export interface TreeNode { name: string; path: string; dir: boolean; children: TreeNode[] }

export const FILE_PATHS = [...new Set([...Object.values(NODES).flatMap((n) => n.paths ?? []), ...FILES.map((f) => f.path)])].sort();

export const buildTree = (): TreeNode[] => {
  const root: TreeNode = { name: "", path: "", dir: true, children: [] };
  for (const p of FILE_PATHS) {
    let cur = root;
    p.split("/").forEach((name, i, a) => {
      const path = a.slice(0, i + 1).join("/");
      let child = cur.children.find((c) => c.path === path);
      if (!child) { child = { name, path, dir: i < a.length - 1, children: [] }; cur.children.push(child); }
      cur = child;
    });
  }
  const sort = (t: TreeNode) => { t.children.sort((a, b) => Number(b.dir) - Number(a.dir) || a.name.localeCompare(b.name)); t.children.forEach(sort); };
  sort(root);
  return root.children;
};

export const hasPreview = (p: string) => FILES.some((f) => f.path === p);
