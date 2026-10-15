// Repo tree from a flat list of file paths, and file URL helpers.
export const decodeSeg = (s: string) => { try { return decodeURIComponent(s); } catch { return s; } };
export const fileHref = (base: string, path: string) => `${base}/f/${path.split("/").map(encodeURIComponent).join("/")}`;

export interface TreeNode { name: string; path: string; dir: boolean; children: TreeNode[] }

export const buildTree = (paths: string[]): TreeNode[] => {
  const root: TreeNode = { name: "", path: "", dir: true, children: [] };
  for (const p of [...new Set(paths)].sort()) {
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
