// Workspaces, connectable sources and what each artifact belongs to. Plain data: safe for server and client.
import type { Node } from "./data";

export interface WsConfig { repos: string[]; jira: string[]; slack: string[] }
export interface Workspace { slug: string; name: string; defaults: WsConfig }

export const WORKSPACES: Workspace[] = [
  { slug: "acme", name: "Acme", defaults: { repos: ["acme/shop"], jira: ["PAY", "SEC"], slack: ["#payments-incident", "#support"] } },
  { slug: "sandbox", name: "Sandbox", defaults: { repos: [], jira: [], slack: [] } },
];

export const CATALOG = {
  repos: ["acme/shop", "acme/billing", "acme/web", "acme/infra"],
  jira: ["PAY", "SEC", "OPS", "GROWTH"],
  slack: ["#payments-incident", "#support", "#eng-general", "#releases"],
};
export const INDEXED_REPO = "acme/shop"; // the only repo with mock data
export const repoSlug = (r: string) => r.split("/")[1];
export const repoByslug = (slug: string) => CATALOG.repos.find((r) => repoSlug(r) === slug);

// Which Jira project / Slack channel each mock artifact belongs to.
const SCOPE: Record<string, string> = {
  pay412: "PAY", sec77: "SEC",
  thrA: "#payments-incident", msgRaj: "#payments-incident", msgDana: "#payments-incident",
  thrB: "#support", msgMira: "#support",
};
/** True when the artifact's repo / Jira project / Slack channel is not connected in this workspace. */
export const isLocked = (n: Node, c: WsConfig) =>
  n.source === "jira" ? !c.jira.includes(SCOPE[n.id]) : n.source === "slack" ? !c.slack.includes(SCOPE[n.id]) : !c.repos.includes(INDEXED_REPO);
export const lockedReason = (n: Node) => (n.source === "jira" ? `Jira ${SCOPE[n.id]}` : n.source === "slack" ? `Slack ${SCOPE[n.id]}` : "Repository");
