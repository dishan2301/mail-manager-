import { useCallback, useEffect, useState } from "react";
import { GitHubCalendar } from "./components/ui/git-hub-calendar";
import type { FormEvent, ReactNode } from "react";
import { Bar, Doughnut, Line } from "react-chartjs-2";
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LineElement,
  PointElement,
  Filler,
  LinearScale,
  Tooltip,
} from "chart.js";
import { motion, useReducedMotion } from "motion/react";
import {
  Alert,
  Box,
  Button,
  Card,
  CircularProgress,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
  FormControlLabel,
  IconButton,
  InputAdornment,
  LinearProgress,
  MenuItem,
  Pagination,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import {
  Assessment,
  Add,
  AutoFixHigh,
  AutoAwesome,
  ArrowForward,
  Bolt,
  CheckCircleOutline,
  Close,
  ContentCopy,
  Edit,
  Dashboard,
  Delete,
  Email,
  ErrorOutline,
  Groups,
  History,
  HelpOutline,
  FlightRounded,
  LockOutlined,
  Logout,
  Mail,
  Menu as MenuIcon,
  OpenInNew,
  Search,
  Send,
  Schedule,
  ShieldOutlined,
  Settings,
  Sync,
  Visibility,
  VisibilityOff,
} from "@mui/icons-material";
import GuidedTour from "./GuidedTour";
import type { TourStep } from "./GuidedTour";
import { useContent } from "./dynamicContent";
ChartJS.register(
  ArcElement,
  BarElement,
  CategoryScale,
  LinearScale,
  Legend,
  LineElement,
  PointElement,
  Filler,
  Tooltip,
);
const sections: { name: string; description: string; icon: ReactNode }[] = [
  { name: "Dashboard", description: "", icon: <Dashboard /> },
  { name: "Pending Emails", description: "", icon: <Email /> },
  { name: "Employee List", description: "Names and email addresses", icon: <Groups /> },
  { name: "Employee Performance", description: "", icon: <Groups /> },
  { name: "Reports", description: "", icon: <Assessment /> },
  { name: "Mailboxes", description: "", icon: <Mail /> },
  { name: "Escalations", description: "", icon: <Assessment /> },
  { name: "Audit Logs", description: "", icon: <History /> },
  { name: "Users & Roles", description: "", icon: <Groups /> },
  { name: "Settings", description: "", icon: <Settings /> },
  { name: "AI Settings", description: "Choose provider and model", icon: <AutoAwesome /> },
];
const departments = ["Sales", "Support", "HRMS"];
const sectionMeta: Record<string, { eyebrow: string; description: string }> = {
  "Employee List": { eyebrow: "EMPLOYEES", description: "Review employees with @indianinfotech.org email addresses. Edit or remove incorrect entries." },
};
const emptyStateMeta: Record<string, { title: string; description: string }> = {
  "Employee List": { title: "No employees yet", description: "Employees with @indianinfotech.org addresses discovered in incoming To recipients appear here." },
};
const tourTargets: Record<string, string> = {
  "Pending Emails": "pending-nav",
  "Employee Performance": "performance-nav",
  Reports: "reports-nav",
  Mailboxes: "mailboxes-nav",
  Escalations: "escalations-nav",
  "Audit Logs": "audit-nav",
  "Users & Roles": "users-nav",
  Settings: "settings-nav",
  "AI Settings": "ai-settings-nav",
};
const sectionContentKeys: Record<string, string> = {
  "Employee List": "employee_list",
  Dashboard: "dashboard",
  "Pending Emails": "pending",
  "Employee Performance": "performance",
  Reports: "reports",
  Mailboxes: "mailboxes",
  Escalations: "escalations",
  "Audit Logs": "audit",
  "Users & Roles": "users",
  Settings: "settings",
  "AI Settings": "ai_settings",
};
const tourStepKeys = [
  ["workspace", "workspace"],
  ["navigation", "navigation"],
  ["readiness", "readiness"],
  ["kpis", "kpis"],
  ["sync", "sync"],
  ["pending-nav", "pending"],
  ["performance-nav", "performance"],
  ["reports-nav", "reports"],
  ["mailboxes-nav", "mailboxes"],
  ["escalations-nav", "escalations"],
  ["audit-nav", "audit"],
  ["users-nav", "users"],
  ["settings-nav", "settings"],
  ["help", "help"],
] as const;
const initialQuery = new URLSearchParams(location.search);
const initialView = initialQuery.get("view");
function tokenRole(token: string) {
  try {
    const value = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(value)).role as "admin" | "manager";
  } catch {
    return "manager";
  }
}
function apiErrorMessage(detail: unknown, fallback: string) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          const field = Array.isArray((item as any).loc)
            ? (item as any).loc.slice(1).join(".")
            : "";
          return field
            ? `${field}: ${(item as any).msg}`
            : String((item as any).msg);
        }
        return JSON.stringify(item);
      })
      .filter(Boolean)
      .join("; ");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return fallback;
}
function replyStatusLabel(value: unknown) {
  const status = String(value || "").toLowerCase();
  if (status === "pending") return "Not Replied";
  if (status === "replied") return "Replied";
  if (status === "ignored") return "Ignored";
  if (status === "observer_copy") return "Observer copy";
  if (status === "duplicate_copy") return "Duplicate copy";
  return String(value ?? "");
}
function formatMailboxDateTime(value: unknown, timeZone?: string) {
  if (!value) return "—";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: timeZone || "Asia/Kolkata",
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}
function localDateKey(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  return `${part("year")}-${part("month")}-${part("day")}`;
}
function formatIndiaDate(value: string, options: Intl.DateTimeFormatOptions = {}) {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", ...options }).format(date);
}
let refreshInFlight: Promise<string | null> | null = null;
function refreshAccessToken() {
  if (!refreshInFlight) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    refreshInFlight = fetch("/api/auth/refresh", { method: "POST", credentials: "include", signal: controller.signal })
      .then(async (response) => response.ok ? (await response.json()).access_token : null)
      .catch(() => null)
      .finally(() => window.clearTimeout(timeout))
      .finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}
async function api(path: string, token: string, options: RequestInit = {}) {
  const request = (accessToken: string) =>
    fetch(`/api${path}`, {
      ...options,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
        ...options.headers,
      },
    });
  let r = await request(token);
  if (r.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      window.dispatchEvent(
        new CustomEvent("oeis-token", { detail: refreshed }),
      );
      r = await request(refreshed);
    } else {
      window.dispatchEvent(new CustomEvent("oeis-token", { detail: "" }));
      throw new Error("Session expired. Sign in again.");
    }
  }
  if (!r.ok) {
    const contentType = r.headers.get("content-type") || "";
    if (contentType.includes("text/html")) {
      redirectToProductionDashboard();
      throw new Error("Wrong OEIS server opened. Opening the production dashboard…");
    }
    const e = contentType.includes("application/json")
      ? await r.json().catch(() => ({}))
      : {};
    throw new Error(
      apiErrorMessage(e.detail, `Request failed (${r.status})`),
    );
  }
  if (r.status === 204) return null;
  if (!(r.headers.get("content-type") || "").includes("application/json")) {
    redirectToProductionDashboard();
    throw new Error("Wrong OEIS server opened. Opening the production dashboard…");
  }
  return r.json();
}
function redirectToProductionDashboard() {
  const configured = import.meta.env.VITE_DASHBOARD_URL ||
    (import.meta.env.VITE_VERCEL_PROJECT_PRODUCTION_URL
      ? `https://${import.meta.env.VITE_VERCEL_PROJECT_PRODUCTION_URL}`
      : "");
  const localWrongServer = ["8000", "10000"].includes(window.location.port) &&
    ["localhost", "127.0.0.1"].includes(window.location.hostname);
  const destination = configured || (localWrongServer
    ? `${window.location.protocol}//${window.location.hostname}:8080`
    : "");
  if (!destination) return;
  const target = new URL(destination, window.location.origin);
  if (target.origin === window.location.origin) return;
  target.pathname = "/";
  target.search = window.location.search;
  target.hash = window.location.hash;
  window.location.replace(target.toString());
}
function OeisLogo({ compact = false }: { compact?: boolean }) {
  const { text } = useContent();
  return (
    <Box
      className={`oeis-logo ${compact ? "compact" : ""}`}
      aria-label={text("brand.aria")}
    >
      <svg viewBox="0 0 56 56" aria-hidden="true">
        <rect x="2" y="2" width="52" height="52" rx="17" fill="currentColor" />
        <circle
          cx="28"
          cy="28"
          r="16"
          fill="none"
          stroke="white"
          strokeWidth="4"
          opacity=".98"
        />
        <path
          d="M18 23.5 28 31l10-7.5M19 22h18v13H19z"
          fill="none"
          stroke="white"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle
          cx="43"
          cy="13"
          r="5"
          fill="#F2A93B"
          stroke="#fff"
          strokeWidth="2"
        />
      </svg>
      <Box>
        <b>{text("brand.name")}</b>
        <small>{text("brand.full_name")}</small>
      </Box>
    </Box>
  );
}
function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const { text } = useContent();
  const [email, setEmail] = useState(""),
    [password, setPassword] = useState(""),
    [showPassword, setShowPassword] = useState(false),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const reduced = useReducedMotion();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username: email, password }),
      });
      if (!r.ok) {
        let message = "Login failed";
        try {
          const body = await r.json();
          if (body && typeof body.detail === "string" && body.detail.trim()) {
            message = body.detail;
          }
        } catch {}
        throw new Error(message);
      }
      const d = await r.json();
      onLogin(d.access_token);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Box className="prod-login login-shell">
      <motion.section
        className="login-story"
        aria-label={text("login.intro_aria")}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: reduced ? 0 : 0.45 }}
      >
        <OeisLogo />
        <Box className="login-story-copy">
          <Typography className="login-kicker">
            {text("login.kicker")}
          </Typography>
          <Typography component="h1">
            {text("login.headline.line1")}
            <br />
            <span>{text("login.headline.line2")}</span>
          </Typography>
          <Typography>{text("login.summary")}</Typography>
        </Box>
        <Box className="login-orbit" aria-hidden="true">
          <span className="orbit-ring ring-one" />
          <span className="orbit-ring ring-two" />
          <span className="orbit-ring ring-three" />
          <motion.div
            className="plane-orbit"
            animate={reduced ? {} : { rotate: 360 }}
            transition={{ duration: 5.5, repeat: Infinity, ease: "linear" }}
          >
            <span className="plane">
              <FlightRounded />
            </span>
          </motion.div>
          <motion.div
            className="orbit-core"
            initial={{ scale: reduced ? 1 : 0.82, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{
              delay: reduced ? 0 : 0.65,
              duration: reduced ? 0 : 0.5,
              ease: [0.22, 1, 0.36, 1],
            }}
          >
            <svg viewBox="0 0 56 56" aria-hidden="true">
              <circle
                cx="28"
                cy="28"
                r="19"
                fill="none"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                d="M17 23 28 31l11-8M18 21h20v16H18z"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <b>{text("login.signal.title")}</b>
            <small>{text("login.signal.detail")}</small>
          </motion.div>
          <motion.div
            className="orbit-note note-one"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: reduced ? 0 : 1.2 }}
          >
            <b>{text("login.critical.value")}</b>
            <span>{text("login.critical.label")}</span>
          </motion.div>
          <motion.div
            className="orbit-note note-two"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: reduced ? 0 : 1.45 }}
          >
            <b>{text("login.time.value")}</b>
            <span>{text("login.time.label")}</span>
          </motion.div>
        </Box>
        <Box className="login-trust">
          <LockOutlined />
          <span>{text("login.trust.graph")}</span>
          <i />
          <span>{text("login.trust.password")}</span>
        </Box>
      </motion.section>
      <motion.section
        className="login-panel"
        aria-label={text("login.panel_aria")}
        initial={{ opacity: 0, x: reduced ? 0 : 24 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{
          delay: reduced ? 0 : 1.05,
          duration: reduced ? 0 : 0.55,
          ease: [0.22, 1, 0.36, 1],
        }}
      >
        <Card className="login-card">
          <Box className="login-mobile-logo">
            <OeisLogo compact />
          </Box>
          <Box className="login-heading">
            <Typography className="date">{text("login.eyebrow")}</Typography>
            <Typography variant="h4" component="h2">
              {text("login.title")}
            </Typography>
            <Typography color="text.secondary">{text("login.description")}</Typography>
          </Box>
          <form onSubmit={submit}>
            <TextField
              label={text("login.email")}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
              fullWidth
            />
            <TextField
              label={text("login.password")}
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              InputProps={{
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      edge="end"
                      aria-label={
                        showPassword ? text("login.hide_password") : text("login.show_password")
                      }
                      onClick={() => setShowPassword((value) => !value)}
                    >
                      {showPassword ? <VisibilityOff /> : <Visibility />}
                    </IconButton>
                  </InputAdornment>
                ),
              }}
              fullWidth
            />
            {error && <Alert severity="error">{error}</Alert>}
            <Button
              type="submit"
              variant="contained"
              color="info"
              disabled={busy}
              fullWidth
            >
              {busy ? (
                <>
                  <CircularProgress size={17} color="inherit" />
                  {text("login.signing_in")}
                </>
              ) : (
                text("login.submit")
              )}
            </Button>
          </form>
          <Box className="login-security">
            <LockOutlined />
            <Box>
              <b>{text("login.security.title")}</b>
              <span>{text("login.security.detail")}</span>
            </Box>
          </Box>
        </Card>
        <Typography className="login-footer">
          {text("login.footer")}
        </Typography>
      </motion.section>
    </Box>
  );
}
function DataTable({
  rows,
  onSelect,
  onEdit,
  onDelete,
  onConnect,
  emptyTitle,
  emptyDescription,
  dimensionLabel,
}: {
  rows: any[];
  onSelect?: (row: any) => void;
  onEdit?: (row: any) => void;
  onDelete?: (row: any) => void;
  onConnect?: (row: any) => void;
  emptyTitle?: string;
  emptyDescription?: string;
  dimensionLabel?: string;
}) {
  const { format, text } = useContent();
  if (!rows.length)
    return (
      <Box className="feature-empty compact">
        <Search />
        <b>{emptyTitle || text("empty.default.title")}</b>
        <span>{emptyDescription || text("empty.default.description")}</span>
      </Box>
    );
  const columns = Object.keys(rows[0]).filter(
    (column) => (column !== "id" || !("serial_number" in rows[0])) && column !== "mailbox_timezone" && column !== "employee_id",
  );
  return (
    <Box
      className="table-scroll"
      role="region"
      aria-label={text("table.region_aria")}
      tabIndex={0}
    >
      <table aria-label={text("table.aria")}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th scope="col" key={c}>
                {c === "dimension" && dimensionLabel ? dimensionLabel : c
                  .replaceAll("_", " ")
                  .replace(/\b\w/g, (letter) => letter.toUpperCase())}
              </th>
            ))}
            {(onConnect || onEdit || onDelete) && <th scope="col">{text("table.actions")}</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={r.id ?? i}
              onClick={() => onSelect?.(r)}
              onKeyDown={(event) => {
                if (onSelect && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                  onSelect(r);
                }
              }}
              tabIndex={onSelect ? 0 : undefined}
              className={onSelect ? "clickable-row" : ""}
            >
              {columns.map((c) => (
                <td key={c}>
                  {r[c] === null ? (
                    "—"
                  ) : typeof r[c] === "boolean" ? (
                    <Chip
                      size="small"
                      variant="outlined"
                      color={r[c] ? "success" : "default"}
                      label={r[c] ? text("status.active") : text("status.inactive")}
                    />
                  ) : typeof r[c] === "object" ? (
                    JSON.stringify(r[c])
                  ) : typeof r[c] === "number" ? (
                    c === "reply_rate" ? `${r[c].toFixed(1)}%` : c === "average_reply_hours" ? `${r[c].toFixed(2)} h` : String(r[c])
                  ) : typeof r[c] === "string" && /^\d{4}-\d{2}-\d{2}/.test(r[c]) && /(date|time|received|created|_at$)/i.test(c) &&
                    !Number.isNaN(Date.parse(String(r[c]))) ? (
                    formatMailboxDateTime(r[c], r.mailbox_timezone)
                  ) : /(status|priority|role|classification)/i.test(c) ? (
                    <Chip
                      className={`data-chip chip-${String(r[c]).toLowerCase().replaceAll(" ", "-")}`}
                      size="small"
                      variant="outlined"
                      label={/status/i.test(c) ? replyStatusLabel(r[c]) : String(r[c])}
                    />
                  ) : (
                    String(r[c])
                  )}
                </td>
              ))}
              {(onConnect || onEdit || onDelete) && (
                <td>
                  <Stack direction="row" spacing={1}>
                    {onEdit && (
                      <Button
                        size="small"
                        startIcon={<Edit />}
                        onClick={(event) => {
                          event.stopPropagation();
                          onEdit(r);
                        }}
                      >
                        Edit
                      </Button>
                    )}
                    {onConnect && (
                      <Button
                        size="small"
                        startIcon={<OpenInNew />}
                        onClick={(event) => {
                          event.stopPropagation();
                          onConnect(r);
                        }}
                      >
                        {text(r.provider === "gmail" ? "table.connect_gmail" : "table.connect_outlook")}
                      </Button>
                    )}
                    {onDelete && (
                      <Button
                        color="error"
                        size="small"
                        startIcon={<Delete />}
                        onClick={(event) => {
                          event.stopPropagation();
                          onDelete(r);
                        }}
                      >
                        {text("table.remove")}
                      </Button>
                    )}
                  </Stack>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </Box>
  );
}

function MailKanban({ rows, onSelect }: { rows: any[]; onSelect: (row: any) => void }) {
  const columns = [
    ["pending", "Awaiting reply"],
    ["replied", "Replied"],
    ["ignored", "Ignored"],
    ["observer_copy", "Observer copy"],
    ["duplicate_copy", "Duplicate copy"],
  ] as const;
  return <Box className="mail-kanban">{columns.map(([status, label]) => {
    const items = rows.filter((row) => String(row.status).toLowerCase() === status);
    return <Box className="kanban-column" key={status}><Box className="kanban-column-head"><b>{label}</b><Chip size="small" label={items.length} /></Box>{items.length ? items.map((row) => <Card className="kanban-card" key={row.id} onClick={() => onSelect(row)} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") onSelect(row); }}><Box className="kanban-card-top"><Chip size="small" label={row.priority || "Mail"} /><small>{row.read_at ? "Read" : "Unread"}</small></Box><b>{row.subject || "(no subject)"}</b><span>{row.from || row.email}</span><small>To: {row.to || row.mailbox}</small><Box className="kanban-card-foot"><span>{row.assigned_employee || "Unassigned"}</span><strong>{row.hours ? `${Number(row.hours).toFixed(1)}h` : "—"}</strong></Box></Card>) : <Typography className="kanban-empty" variant="body2">No mail in this stage</Typography>}</Box>;
  })}</Box>;
}
const kpiMeta: Record<string, { label: string; note: string }> = {};
type Readiness = {
  operational: boolean;
  integration_configured: boolean;
  graph_configured: boolean;
  gmail_configured: boolean;
  smtp_configured: boolean;
  configured_mailboxes: number;
  healthy_mailboxes: number;
  error_mailboxes: number;
  warning_mailboxes: number;
  stale_mailboxes: number;
  stale_after_seconds: number;
  mailbox_health: {id:number;address:string;last_successful_sync:string|null;stale:boolean;never_synced:boolean;sync_error:boolean}[];
  paused_mailboxes: number;
  last_successful_sync: string | null;
};
function SyncFreshnessAlert({ readiness }: { readiness: Readiness | null }) {
  const affected = readiness?.mailbox_health?.filter((row) => row.stale || row.never_synced) || [];
  if (!affected.length) return null;
  return <Alert severity="warning" sx={{ mb: 2 }}>Mailbox data may be incomplete: {affected.map((row) => `${row.address} (${row.never_synced ? "never synced" : `last successful sync ${new Date(row.last_successful_sync!).toLocaleString()}`})`).join("; ")}. Please check Mailboxes and run Sync.</Alert>;
}
type GraphSetup = {
  graph_configured: boolean;
  missing: string[];
  credential_status?: {
    tenant_id_saved: boolean;
    client_id_saved: boolean;
    client_secret_saved: boolean;
    runtime_loaded: boolean;
  };
  required_permission: string;
  portal_links: {
    app_registration: string;
    app_registrations: string;
    api_permissions: string;
    exchange_admin: string;
    admin_consent: string | null;
  };
  delegated_setup?: {
    redirect_uri: string;
    scopes: string;
    supported_accounts: string;
    oauth_configured?: boolean;
  };
  env_template: string;
  azure_cli_commands: string;
  exchange_policy_commands: string;
};
type GmailSetup = {
  gmail_configured: boolean;
  missing: string[];
  required_permission: string;
  redirect_uri: string;
  scopes: string;
  portal_links: {
    project: string;
    api_library: string;
    consent_screen: string;
    credentials: string;
  };
  env_template: string;
};
function GraphSetupPipeline({
  setup,
  mailboxAddress,
  onCopy,
  onDownload,
  onTestGraph,
  testingGraph,
}: {
  setup: GraphSetup | null;
  mailboxAddress: string;
  onCopy: (value: string, label: string) => void;
  onDownload: (value: string, filename: string) => void;
  onTestGraph: () => void;
  testingGraph: boolean;
}) {
  const { format, text } = useContent();
  if (!setup) {
    return (
      <Alert severity="info">
        {text("graph_ui.empty")}
      </Alert>
    );
  }
  const personalMailbox = /@(outlook\.com|hotmail\.com|live\.com|msn\.com)$/i.test(mailboxAddress.trim());
  const credentialsConfigured = personalMailbox
    ? !!setup.delegated_setup?.oauth_configured
    : !!setup.graph_configured;
  const steps = [
    {
      title: text("graph_ui.step.register.title"),
      detail: text("graph_ui.step.register.detail"),
      href: setup.portal_links.app_registration,
      label: text("graph_ui.step.register.action"),
      done: credentialsConfigured,
    },
    {
      title: personalMailbox
        ? text("graph_ui.step.permission.personal.title")
        : text("graph_ui.step.permission.title"),
      detail: personalMailbox
        ? text("graph_ui.step.permission.personal.detail")
        : setup.required_permission,
      href: setup.portal_links.api_permissions,
      label: text("graph_ui.step.permission.action"),
      done: credentialsConfigured,
    },
    {
      title: personalMailbox
        ? text("graph_ui.step.redirect.title")
        : text("graph_ui.step.scope.title"),
      detail: personalMailbox
        ? text("graph_ui.step.redirect.detail")
        : mailboxAddress || text("graph_ui.step.scope.empty"),
      href: personalMailbox
        ? setup.portal_links.app_registration
        : setup.portal_links.exchange_admin,
      label: personalMailbox
        ? text("graph_ui.step.redirect.action")
        : text("graph_ui.step.scope.action"),
      done: false,
    },
  ];
  const openSetupTabs = () => {
    (personalMailbox
      ? [setup.portal_links.app_registration, setup.portal_links.api_permissions]
      : [
          setup.portal_links.app_registration,
          setup.portal_links.api_permissions,
          setup.portal_links.exchange_admin,
          setup.portal_links.admin_consent,
        ])
      .filter(Boolean)
      .forEach((href) => window.open(href!, "_blank", "noopener"));
  };
  return (
    <Card variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Box>
          <Typography fontWeight={800}>{text("graph_ui.title")}</Typography>
          <Typography variant="body2" color="text.secondary">
            {credentialsConfigured
              ? personalMailbox
                ? text("graph_ui.personal_configured")
                : text("graph_ui.configured")
              : format("graph_ui.missing", { missing: setup.missing.join(", ") || text("graph_ui.none") })}
          </Typography>
        </Box>
        {setup.credential_status && (
          <Alert severity={setup.credential_status.runtime_loaded ? "success" : "error"}>
            Backend status: Tenant ID {setup.credential_status.tenant_id_saved ? "saved" : "missing"}; Client ID {setup.credential_status.client_id_saved ? "saved" : "missing"}; Client secret {setup.credential_status.client_secret_saved ? "saved" : "missing"}; runtime {setup.credential_status.runtime_loaded ? "loaded" : "not ready"}.
          </Alert>
        )}
        <Alert severity="info">
          {personalMailbox ? text("graph_ui.personal_info") : text("graph_ui.info")}
        </Alert>
        {setup.delegated_setup && (
          <Alert severity="warning">
            {format("graph_ui.delegated", {
              accounts: setup.delegated_setup.supported_accounts,
              redirect: setup.delegated_setup.redirect_uri,
              scopes: setup.delegated_setup.scopes,
            })}
          </Alert>
        )}
        <Button
          variant="contained"
          color="info"
          startIcon={<OpenInNew />}
          onClick={openSetupTabs}
        >
          {text("graph_ui.start")}
        </Button>
        {steps.map((step) => (
          <Box
            key={step.title}
            sx={{
              display: "grid",
              gridTemplateColumns: "auto 1fr auto",
              alignItems: "center",
              gap: 1,
            }}
          >
            <Chip
              size="small"
              color={step.done ? "success" : "warning"}
              label={step.done ? text("graph_ui.ready") : text("graph_ui.action")}
            />
            <Box>
              <Typography fontWeight={700}>{step.title}</Typography>
              <Typography variant="caption" color="text.secondary">
                {step.detail}
              </Typography>
            </Box>
            <Button
              size="small"
              variant="outlined"
              startIcon={<OpenInNew />}
              onClick={() => window.open(step.href, "_blank", "noopener")}
            >
              {step.label}
            </Button>
          </Box>
        ))}
        {!personalMailbox && setup.portal_links.admin_consent && (
          <Button
            size="small"
            variant="contained"
            color="info"
            startIcon={<OpenInNew />}
            onClick={() =>
              window.open(
                setup.portal_links.admin_consent!,
                "_blank",
                "noopener",
              )
            }
          >
            {text("graph_ui.admin_consent")}
          </Button>
        )}
        <Box>
          <Typography fontWeight={700}>{text("graph_ui.save_title")}</Typography>
          <Alert severity="info">
            Enter AZURE_CLIENT_ID, AZURE_TENANT_ID, and AZURE_CLIENT_SECRET above, then submit the mailbox. The saved secret stays hidden when you edit it.
          </Alert>
        </Box>
        {setup.graph_configured && !personalMailbox && (
          <Button
            variant="outlined"
            disabled={testingGraph}
            onClick={onTestGraph}
          >
            {testingGraph ? text("graph_ui.testing") : text("graph_ui.test")}
          </Button>
        )}
        <Box>
          <Typography fontWeight={700}>{text("graph_ui.env_title")}</Typography>
          <TextField value={setup.env_template} multiline minRows={4} fullWidth InputProps={{ readOnly: true }} />
          <Button size="small" startIcon={<ContentCopy />} onClick={() => onCopy(setup.env_template, text("graph_ui.env_copied"))}>{text("graph_ui.copy_env")}</Button>
          <Button size="small" onClick={() => onDownload(setup.env_template, "oeis-microsoft.env")}>{text("graph_ui.download_env")}</Button>
        </Box>
        {!personalMailbox && <Box>
          <Typography fontWeight={700}>{text("graph_ui.azure_title")}</Typography>
          <TextField
            value={setup.azure_cli_commands}
            multiline
            minRows={8}
            fullWidth
            InputProps={{ readOnly: true }}
          />
          <Button
            size="small"
            startIcon={<ContentCopy />}
            onClick={() =>
              onCopy(setup.azure_cli_commands, text("graph_ui.azure_copied"))
            }
          >
            {text("graph_ui.copy_azure")}
          </Button>
          <Button
            size="small"
            onClick={() =>
              onDownload(setup.azure_cli_commands, "oeis-graph-setup.sh")
            }
          >
            {text("graph_ui.download_script")}
          </Button>
        </Box>}
        <Box>
          <Typography fontWeight={700}>{text("graph_ui.env_title")}</Typography>
          <TextField
            value={setup.env_template}
            multiline
            minRows={4}
            fullWidth
            InputProps={{ readOnly: true }}
          />
          <Button
            size="small"
            startIcon={<ContentCopy />}
            onClick={() => onCopy(setup.env_template, text("graph_ui.env_copied"))}
          >
            {text("graph_ui.copy_env")}
          </Button>
          <Button
            size="small"
            onClick={() => onDownload(setup.env_template, "oeis.env")}
          >
            {text("graph_ui.download_env")}
          </Button>
        </Box>
        {!personalMailbox && <Box>
          <Typography fontWeight={700}>{text("graph_ui.exchange_title")}</Typography>
          <TextField
            value={setup.exchange_policy_commands}
            multiline
            minRows={6}
            fullWidth
            InputProps={{ readOnly: true }}
          />
          <Button
            size="small"
            startIcon={<ContentCopy />}
            onClick={() =>
              onCopy(
                setup.exchange_policy_commands,
                text("graph_ui.exchange_copied"),
              )
            }
          >
            {text("graph_ui.copy_powershell")}
          </Button>
          <Button
            size="small"
            onClick={() =>
              onDownload(
                setup.exchange_policy_commands,
                "oeis-mailbox-policy.ps1",
              )
            }
          >
            {text("graph_ui.download_powershell")}
          </Button>
        </Box>}
      </Stack>
    </Card>
  );
}
function GmailSetupPipeline({
  setup,
  onCopy,
  onDownload,
  onSaveCredentials,
}: {
  setup: GmailSetup | null;
  onCopy: (value: string, label: string) => void;
  onDownload: (value: string, filename: string) => void;
  onSaveCredentials: (clientId: string, clientSecret: string) => Promise<void>;
}) {
  const { format, text } = useContent();
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  if (!setup) return <Alert severity="info">{text("gmail_ui.empty")}</Alert>;
  const steps = [
    ["project", text("gmail_ui.step.project.title"), text("gmail_ui.step.project.detail"), text("gmail_ui.step.project.action")],
    ["api_library", text("gmail_ui.step.api.title"), setup.required_permission, text("gmail_ui.step.api.action")],
    ["consent_screen", text("gmail_ui.step.consent.title"), text("gmail_ui.step.consent.detail"), text("gmail_ui.step.consent.action")],
    ["credentials", text("gmail_ui.step.credentials.title"), format("gmail_ui.redirect", { redirect: setup.redirect_uri }), text("gmail_ui.step.credentials.action")],
  ] as const;
  const openSetupTabs = () => Object.values(setup.portal_links).forEach((href) => window.open(href, "_blank", "noopener"));
  return (
    <Card variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Box>
          <Typography fontWeight={800}>{text("gmail_ui.title")}</Typography>
          <Typography variant="body2" color="text.secondary">
            {setup.gmail_configured ? text("gmail_ui.configured") : format("gmail_ui.missing", { missing: setup.missing.join(", ") })}
          </Typography>
        </Box>
        <Alert severity="info">{text("gmail_ui.info")}</Alert>
        <Alert severity="warning">
          {format("gmail_ui.required", { permission: setup.required_permission })}<br />
          {format("gmail_ui.redirect", { redirect: setup.redirect_uri })}<br />
          {format("gmail_ui.scopes", { scopes: setup.scopes })}
        </Alert>
        <Button variant="contained" color="info" startIcon={<OpenInNew />} onClick={openSetupTabs}>
          {text("gmail_ui.start")}
        </Button>
        {steps.map(([link, title, detail, label]) => (
          <Box key={link} sx={{ display: "grid", gridTemplateColumns: "auto 1fr auto", alignItems: "center", gap: 1 }}>
            <Chip size="small" color={setup.gmail_configured ? "success" : "warning"} label={setup.gmail_configured ? text("gmail_ui.ready") : text("gmail_ui.action")} />
            <Box><Typography fontWeight={700}>{title}</Typography><Typography variant="caption" color="text.secondary">{detail}</Typography></Box>
            <Button size="small" variant="outlined" startIcon={<OpenInNew />} onClick={() => window.open(setup.portal_links[link], "_blank", "noopener")}>{label}</Button>
          </Box>
        ))}
        <Box>
          <Typography fontWeight={700}>{text("gmail_ui.save_title")}</Typography>
          <Alert severity="info">Enter the Google OAuth credentials here. They are saved in the backend environment and the secret is never displayed again.</Alert>
          <Stack spacing={1} sx={{ mt: 1 }}>
            <TextField label="Google OAuth Client ID" value={clientId} onChange={(e) => { setClientId(e.target.value); setSaved(false); }} fullWidth />
            <TextField label="Google OAuth Client Secret" type="password" value={clientSecret} onChange={(e) => { setClientSecret(e.target.value); setSaved(false); }} fullWidth />
            {saved && <Alert severity="success">Google credentials saved successfully.</Alert>}
            <Button variant="outlined" disabled={saving || saved || !clientId.trim() || !clientSecret} onClick={async () => { setSaving(true); try { await onSaveCredentials(clientId, clientSecret); setClientSecret(""); setSaved(true); } finally { setSaving(false); } }}>
              {saving ? "Saving…" : saved ? "Saved" : "Save Google credentials"}
            </Button>
          </Stack>
        </Box>
        <Box>
          <Typography fontWeight={700}>{text("gmail_ui.env_title")}</Typography>
          <TextField value={setup.env_template} multiline minRows={4} fullWidth InputProps={{ readOnly: true }} />
          <Button size="small" startIcon={<ContentCopy />} onClick={() => onCopy(setup.env_template, text("gmail_ui.env_copied"))}>{text("gmail_ui.copy_env")}</Button>
          <Button size="small" onClick={() => onDownload(setup.env_template, "oeis-gmail.env")}>{text("gmail_ui.download_env")}</Button>
        </Box>
      </Stack>
    </Card>
  );
}
function ProductionDashboard({
  data,
  readiness,
  onNavigate,
  onSync,
  canSync,
}: {
  data: Record<string, number>;
  readiness: Readiness | null;
  onNavigate: (section: string) => void;
  onSync: () => void;
  canSync: boolean;
}) {
  const { format, text } = useContent();
  const pending = Number(data.pending_replies || 0),
    overdue = Number(data.overdue || 0),
    critical = Number(data.critical || 0),
    resolved = Number(data.resolved_today || 0);
  const hasData = Object.values(data).some((value) => Number(value) > 0);
  const integration = !readiness
    ? {
        message: text("dashboard.integration.checking.message"),
        label: text("dashboard.integration.checking.label"),
        color: "info" as const,
      }
    : !readiness.integration_configured
      ? {
          message: text("dashboard.integration.graph_missing.message"),
          label: text("dashboard.integration.graph_missing.label"),
          color: "warning" as const,
        }
      : readiness.configured_mailboxes === 0
        ? {
            message: text("dashboard.integration.mailbox_missing.message"),
            label: text("dashboard.integration.mailbox_missing.label"),
            color: "warning" as const,
          }
        : readiness.error_mailboxes > 0
          ? {
              message:
                text("dashboard.integration.sync_failed.message"),
              label: format("dashboard.mailbox_error", { count: readiness.error_mailboxes }),
              color: "error" as const,
            }
          : readiness.stale_mailboxes > 0
            ? { message: "Mailbox sync is stale; dashboard counts may be incomplete", label: `${readiness.stale_mailboxes} stale mailbox${readiness.stale_mailboxes === 1 ? "" : "es"}`, color: "warning" as const }
          : readiness.warning_mailboxes > 0
            ? {
                message: "Mailbox sync temporarily unavailable - last good dashboard data still shown",
                label: `${readiness.warning_mailboxes} mailbox warning`,
                color: "warning" as const,
              }
          : !readiness.last_successful_sync
            ? {
                message:
                  text("dashboard.integration.first_sync.message"),
                label: text("dashboard.integration.first_sync.label"),
                color: "warning" as const,
              }
            : critical > 0
              ? {
                  message: text("dashboard.integration.critical.message"),
                  label: format("dashboard.critical_count", { count: critical }),
                  color: "error" as const,
                }
              : overdue > 0
                ? {
                    message: text("dashboard.integration.overdue.message"),
                    label: format("dashboard.overdue_count", { count: overdue }),
                    color: "warning" as const,
                  }
                : {
                    message: text("dashboard.integration.healthy.message"),
                    label: text("dashboard.integration.healthy.label"),
                    color: "success" as const,
                  };
  const activation = [
    {
      label: "Mail integrations",
      detail: readiness?.integration_configured
        ? "Credentials detected"
        : "Configuration required",
      complete: !!readiness?.integration_configured,
      error: false,
    },
    {
      label: "Mailbox scope",
      detail: readiness?.configured_mailboxes
        ? `${readiness.configured_mailboxes} mailbox configured`
        : "Add an organizational mailbox",
      complete: !!readiness?.configured_mailboxes,
      error: false,
    },
    {
      label: "Verified synchronization",
      detail: readiness?.last_successful_sync
        ? new Date(readiness.last_successful_sync).toLocaleString()
        : readiness?.error_mailboxes
          ? "Latest attempt failed"
          : readiness?.warning_mailboxes
            ? "Latest attempt had temporary network issue"
          : "Waiting for first run",
      complete: !!readiness?.last_successful_sync,
      error: !!readiness?.error_mailboxes,
    },
    {
      label: "Email notifications",
      detail: readiness?.smtp_configured
        ? "Report delivery available"
        : "Connect Outlook or configure SMTP",
      complete: !!readiness?.smtp_configured,
      error: false,
    },
  ];
  const completed = activation.filter((item) => item.complete).length;
  return (
    <Box className="dashboard-stage" aria-label={text("dashboard.live_aria")}>
      <SyncFreshnessAlert readiness={readiness} />
      <Box
        className={`executive-strip readiness-${integration.color}`}
        data-tour="readiness"
      >
        <Box className="posture-copy">
          <span>{text("dashboard.posture")}</span>
          <b>{integration.message}</b>
          {readiness?.last_successful_sync && (
            <small>
              {format("dashboard.last_success", { time: new Date(readiness.last_successful_sync).toLocaleString() })}
            </small>
          )}
        </Box>
        <Box className="posture-status">
          <small>
            {format("dashboard.as_of", { time: new Date().toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            }) })}
          </small>
          <Chip color={integration.color} label={integration.label} />
        </Box>
      </Box>
      <Card className="metric-ledger" data-tour="kpis">
        {Object.entries(data).map(([key, value], index) => (
          <Box className={`metric-cell metric-${index}`} key={key}>
            <Box>
              <span>{text(`kpi.${key}.label`, kpiMeta[key]?.label || key.replaceAll("_", " "))}</span>
              <i />
            </Box>
            <strong>
              {key === "average_reply_hours"
                ? `${Number(value).toFixed(1)}h`
                : String(value)}
            </strong>
            <small>{text(`kpi.${key}.note`, kpiMeta[key]?.note || text("dashboard.metric_fallback"))}</small>
          </Box>
        ))}
      </Card>
      {hasData ? (
        <Box className="charts executive-charts live-charts">
          <Card>
            <Box className="card-head">
              <Box>
                <Typography className="section-index">{text("dashboard.chart_sla_index")}</Typography>
                <Typography variant="h6">{text("dashboard.chart_sla_title")}</Typography>
                <Typography color="text.secondary">
                  {text("dashboard.chart_sla_description")}
                </Typography>
              </Box>
            </Box>
            <Box className="line">
              <Bar
                aria-label={text("dashboard.chart_sla_aria")}
                data={{
                  labels: [text("performance.pending"), text("filter.overdue"), text("performance.critical"), text("performance.resolved")],
                  datasets: [
                    {
                      label: text("dashboard.emails"),
                      data: [pending, overdue, critical, resolved],
                      backgroundColor: [
                        "#3B82F6",
                        "#F59E0B",
                        "#DC2626",
                        "#10B981",
                      ],
                      borderRadius: 3,
                    },
                  ],
                }}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: { legend: { display: false } },
                  scales: {
                    y: {
                      beginAtZero: true,
                      ticks: { precision: 0 },
                      grid: { color: "#E8EEF5" },
                    },
                    x: { grid: { display: false } },
                  },
                }}
              />
            </Box>
          </Card>
          <Card>
            <Box className="card-head">
              <Box>
                <Typography className="section-index">
                  {text("dashboard.chart_attention_index")}
                </Typography>
                <Typography variant="h6">{text("dashboard.chart_attention_title")}</Typography>
                <Typography color="text.secondary">
                  {text("dashboard.chart_attention_description")}
                </Typography>
              </Box>
            </Box>
            <Box className="donut">
              <Doughnut
                aria-label={text("dashboard.chart_attention_aria")}
                data={{
                  labels: [text("dashboard.within_sla"), text("filter.overdue"), text("filter.critical")],
                  datasets: [
                    {
                      data: [
                        Math.max(0, pending - overdue - critical),
                        overdue,
                        critical,
                      ],
                      backgroundColor: ["#2563EB", "#F59E0B", "#DC2626"],
                      borderWidth: 0,
                    },
                  ],
                }}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  cutout: "72%",
                  plugins: { legend: { position: "bottom" } },
                }}
              />
            </Box>
          </Card>
        </Box>
      ) : (
        <Box className="activation-layout">
          <Card className="activation-brief">
            <Box className="brief-head">
              <Box>
                <Typography className="section-index">
                  01 / ACTIVATION
                </Typography>
                <Typography variant="h5">Make the intelligence live</Typography>
                <Typography>
                  OEIS is installed. Complete the operational chain below before
                  using the metrics for management decisions.
                </Typography>
              </Box>
              <Box className="activation-score">
                <strong>{completed}/4</strong>
                <span>systems ready</span>
              </Box>
            </Box>
            <LinearProgress
              variant="determinate"
              value={(completed / 4) * 100}
            />
            <Box className="activation-list">
              {activation.map((item, index) => (
                <Box
                  className={`activation-row ${item.complete ? "complete" : item.error ? "blocked" : "waiting"}`}
                  key={item.label}
                >
                  <span className="step-number">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <Box>
                    {item.complete ? (
                      <CheckCircleOutline />
                    ) : item.error ? (
                      <ErrorOutline />
                    ) : (
                      <Schedule />
                    )}
                  </Box>
                  <Box>
                    <b>{item.label}</b>
                    <small>{item.detail}</small>
                  </Box>
                  <span>
                    {item.complete
                      ? "Ready"
                      : item.error
                        ? "Blocked"
                        : "Pending"}
                  </span>
                </Box>
              ))}
            </Box>
            <Box className="brief-actions">
              <Button
                variant="contained"
                endIcon={<ArrowForward />}
                onClick={() => onNavigate(canSync ? "Mailboxes" : "Audit Logs")}
              >
                {canSync ? "Review mailbox" : "Review audit log"}
              </Button>
              {canSync && (
                <Button onClick={onSync}>Retry synchronization</Button>
              )}
            </Box>
          </Card>
          <Card className="automation-brief">
            <Box className="automation-mark">
              <Bolt />
            </Box>
            <Typography className="section-index">02 / AUTOMATION</Typography>
            <Typography variant="h5">What starts after sync</Typography>
            <Typography>
              Four independent controls begin working without support-team
              input.
            </Typography>
            <Box className="automation-list">
              <Box>
                <ShieldOutlined />
                <span>
                  <b>Classification</b>
                  <small>Customer mail is separated from noise</small>
                </span>
              </Box>
              <Box>
                <CheckCircleOutline />
                <span>
                  <b>Reply matching</b>
                  <small>Headers close the correct incoming email</small>
                </span>
              </Box>
              <Box>
                <Schedule />
                <span>
                  <b>Business SLA clock</b>
                  <small>Time zones, weekends and holidays applied</small>
                </span>
              </Box>
              <Box>
                <ErrorOutline />
                <span>
                  <b>Escalation</b>
                  <small>Manager and Director notified once</small>
                </span>
              </Box>
            </Box>
          </Card>
        </Box>
      )}
    </Box>
  );
}
function ReferenceDashboard({
  data,
  employeePerformance,
  employeeConnections,
  replyRate,
  growth,
  insights,
  readiness,
  onNavigate,
  onSync,
  canSync,
}: {
  data: Record<string, number>;
  employeePerformance: any[];
  employeeConnections: any[];
  replyRate: { replied: number; pending: number; total_incoming: number; reply_rate: number };
  growth: any[];
  insights: { top_senders: any[] };
  readiness: Readiness | null;
  onNavigate: (section: string) => void;
  onSync: () => void;
  canSync: boolean;
}) {
  const { format, text } = useContent();
  const pending = Number(data.pending_replies || 0);
  const overdue = Number(data.overdue || 0);
  const critical = Number(data.critical || 0);
  const resolved = Number(data.resolved_today || 0);
  const integration = !readiness
    ? { message: text("dashboard.integration.checking.message"), label: text("dashboard.integration.checking.label"), color: "info" as const }
    : !readiness.integration_configured
      ? { message: text("dashboard.integration.graph_missing.message"), label: text("dashboard.integration.graph_missing.label"), color: "warning" as const }
      : readiness.configured_mailboxes === 0
        ? { message: text("dashboard.integration.mailbox_missing.message"), label: text("dashboard.integration.mailbox_missing.label"), color: "warning" as const }
        : readiness.error_mailboxes > 0
          ? { message: text("dashboard.integration.sync_failed.message"), label: format("dashboard.mailbox_error", { count: readiness.error_mailboxes }), color: "error" as const }
          : readiness.stale_mailboxes > 0
            ? { message: "Mailbox sync is stale; dashboard counts may be incomplete", label: `${readiness.stale_mailboxes} stale mailbox${readiness.stale_mailboxes === 1 ? "" : "es"}`, color: "warning" as const }
          : readiness.warning_mailboxes > 0
            ? { message: "Mailbox sync temporarily unavailable - last good dashboard data still shown", label: `${readiness.warning_mailboxes} mailbox warning`, color: "warning" as const }
          : !readiness.last_successful_sync
            ? { message: text("dashboard.integration.first_sync.message"), label: text("dashboard.integration.first_sync.label"), color: "warning" as const }
            : critical > 0
              ? { message: text("dashboard.integration.critical.message"), label: format("dashboard.critical_count", { count: critical }), color: "error" as const }
              : overdue > 0
                ? { message: text("dashboard.integration.overdue.message"), label: format("dashboard.overdue_count", { count: overdue }), color: "warning" as const }
                : { message: text("dashboard.integration.healthy.message"), label: text("dashboard.integration.healthy.label"), color: "success" as const };
  const activation = [
    { label: "Mail integrations", detail: readiness?.integration_configured ? "Credentials detected" : "Configuration required", complete: !!readiness?.integration_configured, error: false },
    { label: "Mailbox scope", detail: readiness?.configured_mailboxes ? `${readiness.configured_mailboxes} mailbox configured` : "Add an organizational mailbox", complete: !!readiness?.configured_mailboxes, error: false },
    { label: "Verified synchronization", detail: readiness?.last_successful_sync ? new Date(readiness.last_successful_sync).toLocaleString() : readiness?.error_mailboxes ? "Latest attempt failed" : readiness?.warning_mailboxes ? "Latest attempt had temporary network issue" : "Waiting for first run", complete: !!readiness?.last_successful_sync, error: !!readiness?.error_mailboxes },
    { label: "Email notifications", detail: readiness?.smtp_configured ? "Report delivery available" : "Connect Outlook or configure SMTP", complete: !!readiness?.smtp_configured, error: false },
  ];
  const completed = activation.filter((item) => item.complete).length;
  const metrics = [
    { key: "today", label: text("kpi.today_emails.label"), value: Number(data.today_emails || 0), note: text("kpi.today_emails.note"), hero: true },
    { key: "pending", label: text("kpi.pending_replies.label"), value: pending, note: text("kpi.pending_replies.note") },
    { key: "overdue", label: text("kpi.overdue.label"), value: overdue, note: text("kpi.overdue.note") },
    { key: "critical", label: text("kpi.critical.label"), value: critical, note: text("kpi.critical.note") },
  ];
  const analytics = [Number(data.today_emails || 0), pending, overdue, critical, Number(data.average_reply_hours || 0), resolved, Number(data.ignored_emails || 0)];
  const maxAnalytics = Math.max(1, ...analytics);
  const attention = [
    { label: "Critical conversations", value: critical, tone: "critical" },
    { label: "Overdue replies", value: overdue, tone: "overdue" },
    { label: "Pending ownership", value: pending, tone: "pending" },
    { label: "Resolved today", value: resolved, tone: "resolved" },
  ];
  const assignedTotal = employeePerformance.reduce((sum, row) => sum + Number(row.total || row.emails || 0), 0);
  const topEmployees = employeePerformance.slice(0, 5);
  const allInboxReplied = Number(replyRate.replied || 0);
  const allInboxPending = Number(replyRate.pending || 0);
  const allInboxTotal = allInboxReplied + allInboxPending;
  const allInboxReplyRate = allInboxTotal ? Math.round((allInboxReplied / allInboxTotal) * 100) : 0;
  return (
    <Box className="reference-dashboard" aria-label={text("dashboard.live_aria")}>
      <SyncFreshnessAlert readiness={readiness} />
      <Box className={`reference-posture posture-${integration.color}`} data-tour="readiness">
        <Box><span>{text("dashboard.live_posture")}</span><b>{integration.message}</b></Box>
        <Chip color={integration.color} label={integration.label} />
      </Box>
      <Box className="reference-kpis" data-tour="kpis">
        {metrics.map((metric, index) => (
          <Card className={`reference-kpi ${metric.hero ? "hero-metric" : ""}`} key={metric.key}>
            <Box className="reference-kpi-head"><span>{metric.label}</span><button aria-label={`Open ${metric.label}`} onClick={() => onNavigate(index ? "Pending Emails" : "Reports")}><ArrowForward /></button></Box>
            <strong>{metric.value}</strong><small><CheckCircleOutline />{metric.note}</small>
          </Card>
        ))}
      </Box>
      <Box className="reference-bento">
        <Card className="reference-analytics">
          <Box className="reference-card-head"><Box><span>{text("dashboard.analytics")}</span><b>{text("dashboard.analytics_title")}</b></Box><small>{text("dashboard.live_repository")}</small></Box>
          <Box className="reference-bars" aria-label={text("dashboard.analytics_aria")}>
            {analytics.map((value, index) => <Box className={`reference-bar bar-${index}`} key={index}><i style={{ height: `${Math.max(22, (value / maxAnalytics) * 100)}%` }} /><small>{["IN", "P", "O", "C", "AVG", "R", "IGN"][index]}</small><em>{index === 4 ? `${value.toFixed(1)}h` : value}</em></Box>)}
          </Box>
        </Card>
        <Card className="reference-reminder">
          <Box className="reference-card-head"><Box><span>{text("dashboard.next_move")}</span><b>{critical ? text("dashboard.resolve_critical") : overdue ? text("dashboard.clear_overdue") : readiness?.last_successful_sync ? text("dashboard.review_workload") : text("dashboard.verify_flow")}</b></Box></Box>
          <p>{critical ? format("dashboard.critical_sentence", { count: critical }) : overdue ? format("dashboard.overdue_sentence", { count: overdue }) : readiness?.last_successful_sync ? text("dashboard.review_workload_sentence") : text("dashboard.verify_sentence")}</p>
          <Button variant="contained" startIcon={<Bolt />} onClick={() => onNavigate(critical || overdue ? "Pending Emails" : canSync ? "Mailboxes" : "Audit Logs")}>{critical || overdue ? text("dashboard.open_queue") : text("dashboard.review_setup")}</Button>
        </Card>
        <Card className="reference-attention">
          <Box className="reference-card-head"><Box><span>{text("dashboard.attention_queue")}</span><b>{text("dashboard.needs_decision")}</b></Box><Button size="small" onClick={() => onNavigate("Pending Emails")}>{text("dashboard.view_all")}</Button></Box>
          <Box className="reference-attention-list">{attention.map((item, index) => <Box key={item.label}><i className={item.tone}>{index + 1}</i><Box><b>{item.label}</b><small>{item.value === 0 ? text("dashboard.no_current_items") : format("dashboard.active_items", { count: item.value, suffix: item.value === 1 ? "" : "s" })}</small></Box><strong>{item.value}</strong></Box>)}</Box>
        </Card>
        <Card className="reference-activation">
          <Box className="reference-card-head"><Box><span>{text("dashboard.control_chain")}</span><b>{text("dashboard.operational_readiness")}</b></Box><small>{format("dashboard.ready_count", { count: completed })}</small></Box>
          <Box className="reference-activation-list">{activation.map((item, index) => <Box key={item.label}><i>{String(index + 1).padStart(2, "0")}</i><Box className={item.complete ? "ready" : item.error ? "blocked" : "waiting"}>{item.complete ? <CheckCircleOutline /> : item.error ? <ErrorOutline /> : <Schedule />}</Box><Box><b>{item.label}</b><small>{item.detail}</small></Box><em>{item.complete ? text("dashboard.ready") : item.error ? text("dashboard.blocked") : text("dashboard.pending")}</em></Box>)}</Box>
        </Card>
        <Card className="reference-progress">
          <Box className="reference-card-head"><Box><span>ALL TIME · ALL MAILBOXES</span><b>Overall reply rate</b></Box></Box>
          <Box className="reference-gauge" style={{ "--progress": `${(allInboxReplyRate / 100) * 180}deg` } as React.CSSProperties}><Box><strong>{allInboxReplyRate}%</strong><small>reply rate</small></Box></Box>
          <Box className="reference-legend"><span><i />{allInboxReplied} replied</span><span><i />{allInboxTotal} received</span></Box>
          <small className="reply-rate-caption">{allInboxReplied} replied out of {allInboxTotal} customer messages requiring a reply across accessible mailboxes; ignored, observer, and duplicate copies are excluded.</small>
        </Card>
        <Card className="reference-sync">
          <Box className="sync-rings" aria-hidden="true" />
          <Box className="reference-card-head"><Box><span>{text("dashboard.mailbox_pulse")}</span><b>{readiness?.last_successful_sync ? text("dashboard.last_verified_sync") : text("dashboard.awaiting_verified_sync")}</b></Box></Box>
          <strong>{new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</strong>
          <small>{readiness?.last_successful_sync ? new Date(readiness.last_successful_sync).toLocaleString() : text("shell.delta_interval")}</small>
          {canSync ? <Button data-tour="sync" onClick={onSync} startIcon={<Sync />}>{text("top.sync_now")}</Button> : <Button onClick={() => onNavigate("Audit Logs")}>{text("dashboard.view_evidence")}</Button>}
        </Card>
        <Card className="reference-mail-tracker">
          <Box className="reference-card-head"><Box><span>MAIL TRACKER</span><b>Ownership & response flow</b></Box><Button size="small" onClick={() => onNavigate("Employee Performance")}>Details</Button></Box>
          <Box className="tracker-statuses">
            {[{ label: "Incoming", value: Number(data.today_emails || 0), tone: "in" }, { label: "Awaiting reply", value: pending, tone: "pending" }, { label: "Replied", value: resolved, tone: "resolved" }, { label: "Ignored", value: Number(data.ignored_emails || 0), tone: "ignored" }, { label: "Observer copies", value: Number(data.observer_copies || 0), tone: "ignored" }, { label: "Duplicate copies", value: Number(data.duplicate_copies || 0), tone: "ignored" }].map((item) => <Box className="tracker-status" title={`${item.label}: ${item.value}`} key={item.label}><i className={item.tone} /><strong>{item.value}</strong><small>{item.label}</small></Box>)}
          </Box>
          <Typography className="tracker-caption">{assignedTotal} tracked messages connected to employees</Typography>
          <Box className="tracker-people">{topEmployees.length ? topEmployees.map((row, index) => <Box key={row.employee || row.name || index} title={`${row.employee || row.name}: ${Number(row.pending || 0)} pending, ${Number(row.resolved || row.replied || 0)} resolved`}><span>{String(row.employee || row.name || "Employee").slice(0, 18)}</span><LinearProgress variant="determinate" value={Math.min(100, (Number(row.total || row.emails || 0) / Math.max(1, assignedTotal)) * 100)} /><b>{Number(row.total || row.emails || 0)}</b></Box>) : <Typography variant="body2" color="text.secondary">Employee ownership appears after performance data is available.</Typography>}</Box>
          {employeeConnections.length > 0 && <Box className="tracker-connections"><Typography variant="caption">Top mail connections</Typography>{employeeConnections.slice(0, 4).map((link) => <Box key={`${link.sender}-${link.employee}`} title={`${link.sender} → ${link.employee}`}><span>{String(link.sender).slice(0, 24)}</span><ArrowForward /><b>{link.employee}</b><small>{link.pending} pending · {link.replied} replied</small></Box>)}</Box>}
        </Card>
        <Card className="reference-growth">
          <Box className="reference-card-head"><Box><span>GROWTH TRACKER</span><b>14-day mail flow</b></Box><small>Incoming vs. resolved</small></Box>
          <Box className="growth-line-chart" aria-label="Fourteen day incoming, replied, pending and ignored mail trend"><Line data={{ labels: growth.map((day) => day.date.slice(5)), datasets: [{ label: "Incoming", data: growth.map((day) => day.incoming), borderColor: "#3b82f6", backgroundColor: "rgba(59,130,246,.10)", fill: true, tension: .35 }, { label: "Replied", data: growth.map((day) => day.replied), borderColor: "#10b981", backgroundColor: "transparent", tension: .35 }, { label: "Pending", data: growth.map((day) => day.pending), borderColor: "#f59e0b", backgroundColor: "transparent", tension: .35 }, { label: "Ignored", data: growth.map((day) => day.ignored), borderColor: "#94a3b8", backgroundColor: "transparent", tension: .35 }] }} options={{ responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { position: "bottom" } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "#e8eef5" } }, x: { grid: { display: false } } } }} /></Box>
        </Card>
        <Card className="reference-insights">
          <Box className="reference-card-head"><Box><span>SENDER INTELLIGENCE</span><b>Who sends the most mail?</b></Box><Button size="small" onClick={() => onNavigate("Reports")}>Reports</Button></Box>
          <Box className="sender-insights">{insights.top_senders.length ? insights.top_senders.slice(0, 6).map((sender) => <Box key={sender.sender} title={`${sender.sender}: ${sender.replied} replied of ${sender.total} total`}><Box className="sender-label"><span>{String(sender.sender).slice(0, 28)}</span><b>{sender.total}</b></Box><LinearProgress variant="determinate" value={Math.min(100, sender.total / Math.max(1, insights.top_senders[0].total) * 100)} /><Box className="sender-meta"><small>{sender.replied} replied · {sender.pending} pending · {sender.ignored} ignored</small><strong>{sender.reply_rate}% reply rate</strong></Box></Box>) : <Typography variant="body2" color="text.secondary">Sender insights appear after mail is synchronized.</Typography>}</Box>
        </Card>
      </Box>
    </Box>
  );
}

const classifications = [
  "Ignore",
  "Auto Reply",
  "Newsletter",
  "Marketing",
  "Spam",
  "OTP",
  "NoReply",
  "LinkedIn",
  "Amazon",
  "Microsoft Notifications",
  "Google Alerts",
  "Customer",
];
function SettingsEditor({
  kind,
  json,
  onChange,
  onSave,
}: {
  kind: string;
  json: string;
  onChange: (value: string) => void;
  onSave: () => void;
}) {
  const { format, text } = useContent();
  let rows: any[] = [];
  try {
    const parsed = JSON.parse(json);
    rows = Array.isArray(parsed) ? parsed : [];
  } catch {
    return (
      <Box className="settings-workspace">
        <Alert severity="error">
          {text("settings.invalid")}
        </Alert>
      </Box>
    );
  }
  const update = (index: number, key: string, value: unknown) => {
    const next = rows.map((row, rowIndex) =>
      rowIndex === index ? { ...row, [key]: value } : row,
    );
    onChange(JSON.stringify(next, null, 2));
  };
  const remove = (index: number) =>
    onChange(
      JSON.stringify(
        rows.filter((_, rowIndex) => rowIndex !== index),
        null,
        2,
      ),
    );
  const add = () => {
    const row =
      kind === "classification-rules"
        ? {
            name: "New rule",
            priority: (rows.length + 1) * 10,
            field: "subject",
            pattern: "",
            classification: "Customer",
            active: true,
          }
        : {
            mailbox_id: null,
            timezone: "Asia/Kolkata",
            workday_start: "09:00",
            workday_end: "18:00",
            weekdays: [0, 1, 2, 3, 4],
            holidays: [],
          };
    onChange(JSON.stringify([...rows, row], null, 2));
  };
  return (
    <Box className="settings-workspace">
      <Box className="settings-intro">
        <Box>
          <Typography variant="h6">
            {kind === "sla-rules"
              ? text("settings.sla.title")
              : kind === "classification-rules"
                ? text("settings.classification.title")
                : text("settings.calendars.title")}
          </Typography>
          <Typography color="text.secondary">
            {kind === "sla-rules"
              ? text("settings.sla.description")
              : kind === "classification-rules"
                ? text("settings.classification.description")
                : text("settings.calendars.description")}
          </Typography>
        </Box>
        {kind !== "sla-rules" && (
          <Button startIcon={<Add />} onClick={add}>
            {kind === "classification-rules" ? text("settings.add_rule") : text("settings.add_calendar")}
          </Button>
        )}
      </Box>
      <Stack spacing={1.5}>
        {rows.map((row, index) => (
          <Card className="setting-panel" key={row.id || `${kind}-${index}`}>
            {kind === "sla-rules" ? (
              <>
                <Box className="setting-panel-head">
                  <Chip
                    label={String(row.tier).toUpperCase()}
                    color={
                      row.tier === "critical"
                        ? "error"
                        : row.tier === "overdue"
                          ? "warning"
                          : "info"
                    }
                  />
                  <FormControlLabel
                    control={
                      <Switch
                        checked={!!row.business_hours_only}
                        onChange={(event) =>
                          update(
                            index,
                            "business_hours_only",
                            event.target.checked,
                          )
                        }
                      />
                    }
                    label={text("settings.business_hours")}
                  />
                </Box>
                <Box className="setting-grid">
                  <TextField
                    type="number"
                    label={text("settings.threshold")}
                    value={row.threshold_hours}
                    onChange={(event) =>
                      update(
                        index,
                        "threshold_hours",
                        Number(event.target.value),
                      )
                    }
                  />
                  <TextField
                    type="number"
                    label={text("settings.notify_manager")}
                    value={row.notify_manager_at_hours ?? ""}
                    onChange={(event) =>
                      update(
                        index,
                        "notify_manager_at_hours",
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                      )
                    }
                  />
                  <TextField
                    type="number"
                    label={text("settings.notify_director")}
                    value={row.notify_director_at_hours ?? ""}
                    onChange={(event) =>
                      update(
                        index,
                        "notify_director_at_hours",
                        event.target.value === ""
                          ? null
                          : Number(event.target.value),
                      )
                    }
                  />
                </Box>
              </>
            ) : kind === "classification-rules" ? (
              <>
                <Box className="setting-panel-head">
                  <Typography fontWeight={700}>{format("settings.rule_title", { number: index + 1 })}</Typography>
                  <Box>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={!!row.active}
                          onChange={(event) =>
                            update(index, "active", event.target.checked)
                          }
                        />
                      }
                      label="Active"
                    />
                    <IconButton
                      aria-label={format("settings.delete_rule", { number: index + 1 })}
                      onClick={() => remove(index)}
                    >
                      <Close />
                    </IconButton>
                  </Box>
                </Box>
                <Box className="setting-grid classification-grid">
                  <TextField
                    label={text("settings.rule_name")}
                    value={row.name || ""}
                    onChange={(event) =>
                      update(index, "name", event.target.value)
                    }
                  />
                  <TextField
                    type="number"
                    label={text("settings.priority")}
                    value={row.priority}
                    onChange={(event) =>
                      update(index, "priority", Number(event.target.value))
                    }
                  />
                  <TextField
                    select
                    label={text("settings.match_field")}
                    value={row.field}
                    onChange={(event) =>
                      update(index, "field", event.target.value)
                    }
                  >
                    <MenuItem value="sender">{text("settings.sender")}</MenuItem>
                    <MenuItem value="domain">{text("settings.domain")}</MenuItem>
                    <MenuItem value="subject">{text("settings.subject")}</MenuItem>
                  </TextField>
                  <TextField
                    select
                    label={text("settings.classification")}
                    value={row.classification}
                    onChange={(event) =>
                      update(index, "classification", event.target.value)
                    }
                  >
                    {classifications.map((value) => (
                      <MenuItem value={value} key={value}>
                        {value}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    className="pattern-field"
                    label={text("settings.regex")}
                    value={row.pattern || ""}
                    onChange={(event) =>
                      update(index, "pattern", event.target.value)
                    }
                    helperText={text("settings.regex_help")}
                  />
                </Box>
              </>
            ) : (
              <>
                <Box className="setting-panel-head">
                  <Typography fontWeight={700}>
                    {row.mailbox_id
                      ? format("settings.mailbox_calendar", { id: row.mailbox_id })
                      : text("settings.organization_default")}
                  </Typography>
                  <IconButton
                    aria-label={format("settings.delete_calendar", { number: index + 1 })}
                    onClick={() => remove(index)}
                  >
                    <Close />
                  </IconButton>
                </Box>
                <Box className="setting-grid">
                  <TextField
                    label={text("settings.timezone")}
                    value={row.timezone || ""}
                    onChange={(event) =>
                      update(index, "timezone", event.target.value)
                    }
                  />
                  <TextField
                    type="time"
                    label={text("settings.workday_start")}
                    InputLabelProps={{ shrink: true }}
                    value={row.workday_start || "09:00"}
                    onChange={(event) =>
                      update(index, "workday_start", event.target.value)
                    }
                  />
                  <TextField
                    type="time"
                    label={text("settings.workday_end")}
                    InputLabelProps={{ shrink: true }}
                    value={row.workday_end || "18:00"}
                    onChange={(event) =>
                      update(index, "workday_end", event.target.value)
                    }
                  />
                  <TextField
                    label={text("settings.weekdays")}
                    value={(row.weekdays || []).join(", ")}
                    onChange={(event) =>
                      update(
                        index,
                        "weekdays",
                        event.target.value
                          .split(",")
                          .map((value) => Number(value.trim()))
                          .filter(Number.isFinite),
                      )
                    }
                  />
                  <TextField
                    label={text("settings.holidays")}
                    value={(row.holidays || []).join(", ")}
                    onChange={(event) =>
                      update(
                        index,
                        "holidays",
                        event.target.value
                          .split(",")
                          .map((value) => value.trim())
                          .filter(Boolean),
                      )
                    }
                  />
                </Box>
              </>
            )}
          </Card>
        ))}
      </Stack>
      <Box className="settings-actions">
        <Button variant="contained" onClick={onSave}>
          {text("settings.save")}
        </Button>
        <Typography variant="caption" color="text.secondary">
          {text("settings.validation_note")}
        </Typography>
      </Box>
    </Box>
  );
}
type SyncSettings = {
  interval_seconds: number;
  scheduler_enabled: boolean;
  next_sync: string | null;
};
function SyncSettingsPanel({
  settings,
  onChange,
  onSave,
  onSync,
  saving,
  syncing,
}: {
  settings: SyncSettings;
  onChange: (value: SyncSettings) => void;
  onSave: () => void;
  onSync: () => void;
  saving: boolean;
  syncing: boolean;
}) {
  const { format, text } = useContent();
  return (
    <Box className="settings-workspace">
      <Box className="settings-intro">
        <Box>
          <Typography variant="h6">{text("settings.sync.title")}</Typography>
          <Typography color="text.secondary">{text("settings.sync.description")}</Typography>
        </Box>
      </Box>
      <Card className="setting-panel">
        <Stack spacing={2}>
          <FormControlLabel
            control={
              <Switch
                checked={settings.scheduler_enabled}
                onChange={(event) => onChange({ ...settings, scheduler_enabled: event.target.checked })}
              />
            }
            label={text("settings.sync.enabled")}
          />
          <Alert severity="info">Minimum automatic sync interval: 10 seconds.</Alert>
          <TextField
            type="number"
            label={text("settings.sync.interval")}
            value={settings.interval_seconds}
            error={settings.interval_seconds < 10}
            inputProps={{ min: 10, max: 86400, step: 1 }}
            onChange={(event) => onChange({ ...settings, interval_seconds: Number(event.target.value) || 10 })}
            helperText={settings.interval_seconds < 10 ? "Enter 10 seconds or more." : text("settings.sync.helper")}
          />
          <Typography variant="caption" color="text.secondary">
            {settings.next_sync
              ? format("settings.sync.next", { time: new Date(settings.next_sync).toLocaleString() })
              : "Automatic sync is paused."}
          </Typography>
          <Box className="settings-actions">
            <Button variant="contained" disabled={saving || settings.interval_seconds < 10} onClick={onSave}>
              {saving ? "Saving..." : text("settings.sync.save")}
            </Button>
            <Button variant="outlined" disabled={syncing} onClick={onSync} startIcon={<Sync />}>
              {syncing ? text("top.syncing") : text("settings.sync.manual")}
            </Button>
          </Box>
        </Stack>
      </Card>
    </Box>
  );
}
function VisualCoachingReview({ review }: { review: any }) {
  const factors = [
    { key: "professionalism", label: "Professional tone" },
    { key: "detail", label: "Answer detail" },
    { key: "clarity", label: "Clarity" },
    { key: "ownership", label: "Follow-through" },
    { key: "actionability", label: "Actionable next step" },
  ].map(({ key, label }) => {
    const item = review.rubric?.[key];
    return { key, label, score: typeof item?.score === "number" ? item.score as number : null, reason: String(item?.reason || "No reply evidence available") };
  });
  const scored = factors.filter((factor) => factor.score !== null).sort((a, b) => (a.score ?? 0) - (b.score ?? 0));
  const focus = scored[0]?.score !== null && (scored[0]?.score ?? 100) < 80 ? scored[0] : null;
  const strength = scored.length > 1 && (scored[scored.length - 1].score ?? 0) >= 60 ? scored[scored.length - 1] : null;
  return <Box className="coaching-visual-review">
    <Box className="coaching-brief"><Box><span className="coaching-eyebrow">CONVERSATION SNAPSHOT</span><strong>{scored.length ? `${scored.length} of 5 quality areas assessed` : "Reply quality cannot be assessed yet"}</strong><small>{scored.length ? `${5 - scored.length} areas remain unscored where evidence is missing.` : "No attributable reply evidence is available for scoring."}</small></Box><Box className="coaching-coverage" role="img" aria-label={`${scored.length} of 5 quality areas assessed`}>{factors.map((factor) => <span key={factor.key} className={factor.score === null ? "unscored" : factor.score < 60 ? "attention" : "assessed"} />)}</Box></Box>
    <Box className="coaching-factor-grid">{factors.map((factor) => <Box key={factor.key} className={`coaching-factor ${factor.score === null ? "is-unscored" : factor.score < 60 ? "needs-attention" : ""}`}><Box className="coaching-factor-top"><strong>{factor.label}</strong><b>{factor.score === null ? "Unscored" : `${factor.score}/100`}</b></Box><Box className="coaching-factor-track" role="meter" aria-label={factor.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={factor.score ?? undefined} aria-valuetext={factor.score === null ? "Unscored" : `${factor.score} out of 100`}><span style={{ width: `${factor.score ?? 0}%` }} /></Box><small>{factor.reason}</small></Box>)}</Box>
    {(focus || strength) && <Box className="coaching-takeaways">{focus && <Box className="coaching-takeaway focus"><span>COACHING PRIORITY</span><strong>{focus.label}</strong><p>{focus.reason}</p></Box>}{strength && <Box className="coaching-takeaway strength"><span>STRONGEST OBSERVED AREA</span><strong>{strength.label}</strong><p>{strength.reason}</p></Box>}</Box>}
    <details className="coaching-source"><summary>Open full review and source evidence</summary><Box className="coaching-source-body">{String(review.analysis || "No review text recorded.")}</Box></details>
  </Box>;
}

export default function ProductionApp() {
  const { format, text } = useContent();
  const [token, setToken] = useState(""),
    [authChecking, setAuthChecking] = useState(true),
    [section, setSection] = useState(
      initialView === "employee" ? "Employee Performance" : initialView === "pending" ? "Pending Emails" : sections.some((item) => item.name === initialView) ? initialView! : "Dashboard",
    ),
    [data, setData] = useState<any>(null),
    [employeePerformance, setEmployeePerformance] = useState<any[]>([]),
    [employeeConnections, setEmployeeConnections] = useState<any[]>([]),
    [replyRate, setReplyRate] = useState({ replied: 0, pending: 0, total_incoming: 0, reply_rate: 0 }),
    [growth, setGrowth] = useState<any[]>([]),
    [insights, setInsights] = useState<{ top_senders: any[] }>({ top_senders: [] }),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(false),
    [mobile, setMobile] = useState(false),
    [dialog, setDialog] = useState(false),
    [mailbox, setMailbox] = useState({
      address: "",
      display_name: "",
      provider: "microsoft",
      timezone: "Asia/Kolkata",
      status: "active",
      azure_client_id: "",
      azure_tenant_id: "",
      azure_client_secret: "",
    }),
    [editingMailboxId, setEditingMailboxId] = useState<number | null>(null),
    [search, setSearch] = useState(initialQuery.get("search") || ""),
    [mailboxes, setMailboxes] = useState<any[]>([]),
    [employees, setEmployees] = useState<any[]>([]),
    [selectedEmail, setSelectedEmail] = useState<any>(null),
    [conversation, setConversation] = useState<any>(null),
    [selectedEmployee, setSelectedEmployee] = useState<any>(null),
    [aiReviewOpen, setAiReviewOpen] = useState(false),
    [aiReviewConsent, setAiReviewConsent] = useState(false),
    [aiReviewBusy, setAiReviewBusy] = useState(false),
    [aiReviewEmployeeId, setAiReviewEmployeeId] = useState(""),
    [aiReviewPage, setAiReviewPage] = useState(1),
    [aiReviewResult, setAiReviewResult] = useState<any>(null),
    [senderReport, setSenderReport] = useState<any>(null),
    [aiReviewEnabled, setAiReviewEnabled] = useState(false),
    [aiProviderConfigured, setAiProviderConfigured] = useState(false),
    [aiSchedulerEnabled, setAiSchedulerEnabled] = useState(true),
    [employeeTrend, setEmployeeTrend] = useState<any[]>([]),
    [employeeHistory, setEmployeeHistory] = useState<any[]>([]),
    [employeeHourly, setEmployeeHourly] = useState<any[]>([]),
    [employeeDailySenders, setEmployeeDailySenders] = useState<any[]>([]),
    [employeeHourlyDate, setEmployeeHourlyDate] = useState(() => localDateKey()),
    [employeeSelectedDate, setEmployeeSelectedDate] = useState(() => localDateKey()),
    [employeePeriod, setEmployeePeriod] = useState("rolling"),
    [employeeReportPeriod, setEmployeeReportPeriod] = useState("daily"),
    [employeeMailReport, setEmployeeMailReport] = useState<any>(null),
    [replyDraft, setReplyDraft] = useState(""),
    [replyBusy, setReplyBusy] = useState(false),
    [assistantMode, setAssistantMode] = useState<"draft" | "correct" | "rewrite" | "">(""),
    [notice, setNotice] = useState(""),
    [createDialog, setCreateDialog] = useState<"employee" | "user" | null>(
      null,
    ),
    [editingPersonId, setEditingPersonId] = useState<number | null>(null),
    [person, setPerson] = useState({
      name: "",
      email: "",
      department: "General",
      password: "",
      role: "manager",
      active: true,
      mailbox_ids: [] as number[],
    });
  const [statusFilter, setStatusFilter] = useState(
      initialQuery.get("status") || "",
    ),
    [dateFilter, setDateFilter] = useState(initialQuery.get("date") || ""),
    [mailboxFilter, setMailboxFilter] = useState(
      initialQuery.get("mailbox") || "",
    ),
    [employeeFilter, setEmployeeFilter] = useState(
      initialQuery.get("employee") || "",
    ),
    [page, setPage] = useState(Number(initialQuery.get("page")) || 1),
    [settingsView, setSettingsView] = useState("sla-rules"),
    [aiConfig, setAiConfig] = useState<{provider:string;model:string;configured:Record<string,boolean>;models:Record<string,Record<string,string>>;last_check?:{ok:boolean;message:string;model:string;tested_at:string}|null}|null>(null),
    [aiKey, setAiKey] = useState(""),
    [savingAiConfig, setSavingAiConfig] = useState(false),
    [testingAiConfig, setTestingAiConfig] = useState(false),
    [aiTestResult, setAiTestResult] = useState<{ok:boolean;message:string;model:string;tested_at:string}|null>(null),
    [reportPeriod, setReportPeriod] = useState("daily"),
    [reportDimension, setReportDimension] = useState("department"),
    [performanceSort, setPerformanceSort] = useState("employee"),
    [performanceOrder, setPerformanceOrder] = useState("asc"),
    [pendingView, setPendingView] = useState<"table" | "board">("table"),
    [settingsJson, setSettingsJson] = useState("[]"),
    [readiness, setReadiness] = useState<Readiness | null>(null),
    [graphSetup, setGraphSetup] = useState<GraphSetup | null>(null),
    [gmailSetup, setGmailSetup] = useState<GmailSetup | null>(null),
    [testingGraph, setTestingGraph] = useState(false),
    [syncSettings, setSyncSettings] = useState<SyncSettings>({ interval_seconds: 10, scheduler_enabled: true, next_sync: null }),
    [savingSyncSettings, setSavingSyncSettings] = useState(false),
    [syncing, setSyncing] = useState(false),
    [tourOpen, setTourOpen] = useState(
      () => localStorage.getItem("oeis_tour_completed_v1") !== "true",
    );
  const handleTourStep = useCallback((step: TourStep) => {
    if (window.innerWidth < 900)
      setMobile(step.target === "navigation" || step.target.endsWith("-nav"));
  }, []);
  const role = tokenRole(token),
    visibleSections = sections.filter(
      (item) =>
        role === "admin" ||
        !["Mailboxes", "Users & Roles", "Settings", "AI Settings"].includes(item.name),
    );
  const displayName = (name: string) =>
    text(`nav.${sectionContentKeys[name]}.name`, name);
  const displayDescription = (name: string, fallback: string) =>
    text(`nav.${sectionContentKeys[name]}.description`, fallback);
  const navigateSection = (name: string) => {
    if (location.search !== `?view=${encodeURIComponent(name)}`)
      history.pushState(null, "", `?view=${encodeURIComponent(name)}`);
    setSelectedEmployee(null);
    setSection(name);
    setPage(1);
    setMobile(false);
  };
  const pageEyebrow = (name: string) =>
    text(`page.${sectionContentKeys[name]}.eyebrow`, sectionMeta[name]?.eyebrow);
  const pageDescription = (name: string) =>
    text(`page.${sectionContentKeys[name]}.description`, sectionMeta[name]?.description);
  const emptyTitle = (name: string) =>
    text(`empty.${sectionContentKeys[name]}.title`, emptyStateMeta[name]?.title);
  const emptyDescription = (name: string) =>
    text(`empty.${sectionContentKeys[name]}.description`, emptyStateMeta[name]?.description);
  const visibleTourSteps =
    role === "admin"
      ? tourStepKeys
      : tourStepKeys.filter(
          ([target]) =>
            !["sync", "mailboxes-nav", "users-nav", "settings-nav"].includes(
              target,
            ),
        );
  const tourSteps: TourStep[] = visibleTourSteps.map(([target, key]) => ({
    target,
    eyebrow: text(`tour.step.${key}.eyebrow`),
    title: text(`tour.step.${key}.title`),
    description: text(`tour.step.${key}.description`),
  }));
  const load = async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const pendingParams = new URLSearchParams({
        page: String(page),
        search,
        status: statusFilter,
        date_filter: dateFilter,
      });
      if (mailboxFilter) pendingParams.set("mailbox", mailboxFilter);
      if (employeeFilter) pendingParams.set("employee", employeeFilter);
      const paths: Record<string, string> = {
        Dashboard: "/dashboard/kpis",
        "Pending Emails": `/emails/pending?${pendingParams}`,
        "Employee List": "/employees",
        "Employee Performance": `/employees/performance?sort_by=${performanceSort}&order=${performanceOrder}`,
        Reports: `/reports/${reportPeriod}?dimension=${reportDimension}`,
        Mailboxes: "/mailboxes",
        Escalations: "/escalations",
        "Audit Logs": "/audit-logs",
        "Users & Roles": "/users",
        Settings: settingsView === "synchronization" ? "/system/sync-settings" : `/settings/${settingsView}`,
        "AI Settings": "/settings/ai-provider",
      };
      if (section === "Dashboard") {
        const [kpis, health, performance, connections, growthData, insightsData, rateData] = await Promise.all([
          api(paths[section], token),
          api("/system/readiness", token),
          api("/employees/performance?sort_by=total&order=desc", token),
          api("/employees/connections", token),
          api("/dashboard/growth", token),
          api("/dashboard/insights", token),
          api("/employees/reply-rate", token),
        ]);
        setData(kpis);
        setReadiness(health);
        setEmployeePerformance(Array.isArray(performance) ? performance : performance?.rows || []);
        setEmployeeConnections(Array.isArray(connections) ? connections : []);
        setGrowth(Array.isArray(growthData) ? growthData : []);
        setInsights(insightsData?.top_senders ? insightsData : { top_senders: [] });
        setReplyRate(rateData);
      } else if (section === "Reports") {
        const [reportData, aiStatus, health] = await Promise.all([api(paths[section], token), api("/reports/ai-review/status", token), api("/system/readiness", token)]);
        setData(reportData);
        setReadiness(health);
        setAiReviewEnabled(!!aiStatus.enabled);
        setAiProviderConfigured(!!aiStatus.provider_configured);
        setAiSchedulerEnabled(!!aiStatus.scheduler_enabled);
      } else if (section === "Employee List") {
        const employeeList = await api(paths[section], token);
        setData(employeeList);
        setEmployees(employeeList);
      } else if (section === "Employee Performance") {
        const [performance, employeeList] = await Promise.all([api(paths[section], token), api("/employees", token)]);
        setData(performance);
        setEmployees(employeeList);
      } else if (section === "AI Settings") {
        const config = await api(paths[section], token);
        setAiConfig(config);
        setData(config);
      } else setData(await api(paths[section], token));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    load();
  }, [
    token,
    section,
    settingsView,
    reportPeriod,
    reportDimension,
    performanceSort,
    performanceOrder,
    page,
  ]);
  useEffect(() => {
    refreshAccessToken()
      .then((accessToken) => { if (accessToken) setToken(accessToken); })
      .finally(() => setAuthChecking(false));
  }, []);
  useEffect(() => {
    const update = (event: Event) =>
      setToken((event as CustomEvent<string>).detail);
    window.addEventListener("oeis-token", update);
    return () => window.removeEventListener("oeis-token", update);
  }, []);
  useEffect(() => {
    if (!token) return;
    Promise.all([api("/mailbox-options", token), api("/employees", token)])
      .then(([m, e]) => {
        setMailboxes(m);
        setEmployees(e);
      })
      .catch(() => undefined);
  }, [token]);
  useEffect(() => {
    if (!token) return;
    api("/system/readiness", token)
      .then(setReadiness)
      .catch(() => undefined);
  }, [token]);
  useEffect(() => {
    if (!token) return;
    api("/system/sync-settings", token)
      .then(setSyncSettings)
      .catch(() => undefined);
  }, [token]);
  useEffect(() => {
    if (!token || section !== "Dashboard") return;
    const refresh = () => {
      Promise.all([
        api("/dashboard/kpis", token),
        api("/system/readiness", token),
        api("/employees/performance?sort_by=total&order=desc", token),
        api("/employees/connections", token),
        api("/dashboard/growth", token),
        api("/dashboard/insights", token),
        api("/employees/reply-rate", token),
      ])
        .then(([kpis, health, performance, connections, growthData, insightsData, rateData]) => {
          setData(kpis);
          setReadiness(health);
          setEmployeePerformance(Array.isArray(performance) ? performance : performance?.rows || []);
          setEmployeeConnections(Array.isArray(connections) ? connections : []);
          setGrowth(Array.isArray(growthData) ? growthData : []);
          setInsights(insightsData?.top_senders ? insightsData : { top_senders: [] });
          setReplyRate(rateData);
        })
        .catch(() => undefined);
    };
    const delay = Math.max(5000, Math.min(syncSettings.interval_seconds * 1000, 60000));
    const timer = window.setInterval(refresh, delay);
    return () => window.clearInterval(timer);
  }, [token, section, syncSettings.interval_seconds]);
  useEffect(() => {
    if (!token || section !== "Audit Logs") return;
    const refresh = () => {
      api("/audit-logs", token)
        .then(setData)
        .catch(() => undefined);
    };
    const delay = Math.max(5000, Math.min(syncSettings.interval_seconds * 1000, 60000));
    const timer = window.setInterval(refresh, delay);
    return () => window.clearInterval(timer);
  }, [token, section, syncSettings.interval_seconds]);
  useEffect(() => {
    if (section === "Settings" && Array.isArray(data))
      setSettingsJson(JSON.stringify(data, null, 2));
    if (section === "Settings" && settingsView === "synchronization" && data && !Array.isArray(data))
      setSyncSettings(data as SyncSettings);
  }, [section, settingsView, data]);
  useEffect(() => {
    if (!dialog || !token) return;
    const timer = window.setTimeout(() => {
      if (mailbox.provider === "gmail") {
        api("/system/gmail-setup", token).then(setGmailSetup).catch(() => setGmailSetup(null));
      } else {
        const query = mailbox.address ? `?mailbox=${encodeURIComponent(mailbox.address)}` : "";
        api(`/system/graph-setup${query}`, token).then(setGraphSetup).catch(() => setGraphSetup(null));
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [dialog, editingMailboxId, mailbox.address, mailbox.provider, token]);
  useEffect(() => {
    const current = new URLSearchParams(location.search);
    if (current.get("view") === "employee" && current.get("id") && !selectedEmployee) return;
    const query = new URLSearchParams({
      view: selectedEmployee ? "employee" : section === "Pending Emails" ? "pending" : section,
    });
    if (selectedEmployee?.id) query.set("id", String(selectedEmployee.id));
    if (section === "Pending Emails") {
      query.set("search", search); query.set("status", statusFilter); query.set("date", dateFilter); query.set("mailbox", mailboxFilter); query.set("employee", employeeFilter); query.set("page", String(page));
    }
    history.replaceState(history.state, "", `?${query}`);
  }, [
    section,
    search,
    statusFilter,
    dateFilter,
    mailboxFilter,
    employeeFilter,
    page,
    selectedEmployee?.id,
  ]);
  useEffect(() => {
    const restore = () => {
      const query = new URLSearchParams(location.search);
      const view = query.get("view");
      setSection(view === "employee" ? "Employee Performance" : view === "pending" ? "Pending Emails" : sections.some((item) => item.name === view) ? view! : "Dashboard");
      const employeeId = Number(query.get("id"));
      if (view !== "employee" || !employeeId) {
        setSelectedEmployee(null);
        return;
      }
      const employee = employeePerformance.find((row) => row.id === employeeId);
      if (employee && employee.id !== selectedEmployee?.id) void openEmployee(employee);
      else if (!employeePerformance.length) return;
    };
    window.addEventListener("popstate", restore);
    restore();
    return () => window.removeEventListener("popstate", restore);
  }, [employeePerformance, selectedEmployee?.id]);
  const rows: any[] =
    section === "Pending Emails"
      ? data?.items || []
      : section === "Reports"
        ? data?.rows || []
        : section === "Audit Logs"
          ? data || []
          : Array.isArray(data)
            ? data
            : [];
  const [departmentFilter, setDepartmentFilter] = useState("");
  const visibleRows = section === "Employee Performance" && departmentFilter
    ? rows.filter((row) => row.department === departmentFilter)
    : section === "Reports" && reportDimension === "employee" && departmentFilter
      ? rows.filter((row) => row.department === departmentFilter && (!aiReviewEmployeeId || String(row.employee_id) === aiReviewEmployeeId))
    : section === "Reports" && reportDimension === "employee" && aiReviewEmployeeId
      ? rows.filter((row) => String(row.employee_id) === aiReviewEmployeeId)
    : rows;
  const employeeListRows = employees.filter((employee) => employee.active !== false && employee.email.trim().toLowerCase().endsWith("@indianinfotech.org")).map((employee, index) => ({
    serial_number: index + 1,
    id: employee.id,
    name: employee.name?.trim() || employee.email.split("@")[0],
    email: employee.email,
  }));
  const departmentOptions = [...new Set([...departments, ...employees.map((employee) => employee.department || "General"), ...rows.map((row) => row.department || "General")])].sort();
  const departmentCount = (department: string) => rows.filter((row) => (row.department || "General") === department).length;
  const saveGmailCredentials = async (clientId: string, clientSecret: string) => {
    await api("/system/gmail-setup", token, {
      method: "POST",
      body: JSON.stringify({ google_client_id: clientId, google_client_secret: clientSecret }),
    });
    setGmailSetup(await api("/system/gmail-setup", token));
    setNotice("Google OAuth credentials saved.");
  };
  const saveMailbox = async () => {
    try {
      const path = editingMailboxId
        ? `/mailboxes/${editingMailboxId}`
        : "/mailboxes";
      const body = editingMailboxId
        ? {
            display_name: mailbox.display_name,
            timezone: mailbox.timezone,
            status: mailbox.status,
            ...(mailbox.provider === "microsoft" ? { azure_client_id: mailbox.azure_client_id || undefined, azure_tenant_id: mailbox.azure_tenant_id || undefined, azure_client_secret: mailbox.azure_client_secret || undefined } : {}),
          }
        : {
            address: mailbox.address,
            display_name: mailbox.display_name,
            provider: mailbox.provider,
            timezone: mailbox.timezone,
            ...(mailbox.provider === "microsoft" ? { azure_client_id: mailbox.azure_client_id || undefined, azure_tenant_id: mailbox.azure_tenant_id || undefined, azure_client_secret: mailbox.azure_client_secret || undefined } : {}),
          };
      await api(path, token, {
        method: editingMailboxId ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
      setDialog(false);
      setEditingMailboxId(null);
      setMailbox({
        address: "",
        display_name: "",
        provider: "microsoft",
        timezone: "Asia/Kolkata",
        status: "active",
        azure_client_id: "",
        azure_tenant_id: "",
        azure_client_secret: "",
      });
      await load();
      setMailboxes(await api("/mailboxes", token));
      setNotice(
        `Mailbox ${editingMailboxId ? "updated" : "added"} successfully.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save mailbox");
    }
  };
  const copyText = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setNotice(label);
    } catch {
      setError("Clipboard copy failed.");
    }
  };
  const downloadText = (value: string, filename: string) => {
    const href = URL.createObjectURL(
      new Blob([value.endsWith("\n") ? value : `${value}\n`], {
        type: "text/plain;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = href;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(href);
    setNotice(`${filename} downloaded.`);
  };
  const testGraphConnection = async () => {
    setTestingGraph(true);
    try {
      await api("/system/graph-check", token, {
        method: "POST",
        body: JSON.stringify({ mailbox: mailbox.address || null }),
      });
      const health = await api("/system/readiness", token);
      setReadiness(health);
      setNotice(
        mailbox.address
          ? text("notice.graph_mailbox_verified")
          : text("notice.graph_verified"),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Graph check failed");
    } finally {
      setTestingGraph(false);
    }
  };
  const createPerson = async () => {
    if (!createDialog) return;
    try {
      const base = createDialog === "employee" ? "/employees" : "/users";
      const body =
        createDialog === "employee"
          ? { name: person.name, email: person.email, department: person.department, active: person.active }
          : {
              name: person.name,
              email: person.email,
              ...(editingPersonId && !person.password ? {} : { password: person.password }),
              role: person.role,
              active: person.active,
            };
      const saved = await api(editingPersonId ? `${base}/${editingPersonId}` : base, token, {
        method: editingPersonId ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
      if (saved.reauthenticate) {
        setCreateDialog(null);
        setToken("");
        window.alert("Login updated. Sign in again with your new credentials.");
        return;
      }
      if (createDialog === "user" && person.role === "manager") {
        await api(`/users/${editingPersonId || saved.id}/mailbox-access`, token, {
          method: "PUT",
          body: JSON.stringify({ mailbox_ids: person.mailbox_ids }),
        });
      }
      setCreateDialog(null);
      setEditingPersonId(null);
      setPerson({
        name: "",
        email: "",
        department: "General",
        password: "",
        role: "manager",
        active: true,
        mailbox_ids: [],
      });
      const [m, e] = await Promise.all([api("/mailboxes", token), api("/employees", token)]);
      setMailboxes(m);
      setEmployees(e);
      if (createDialog === "employee" && section === "Employee Performance") {
        const performance = await api(`/employees/performance?sort_by=${performanceSort}&order=${performanceOrder}`, token);
        setData(performance);
        setDepartmentFilter(person.department);
      } else await load();
      setNotice(
        `${createDialog === "employee" ? "Employee" : "User"} ${editingPersonId ? "updated" : "created"} successfully.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to create record");
    }
  };
  const openEmail = async (row: any) => {
    try {
      setConversation(null);
      const detail = await api(`/emails/${row.id}`, token);
      api(`/emails/${row.id}/read`, token, { method: "PATCH" }).catch(() => undefined);
      setReplyDraft("");
      setSelectedEmail({ ...detail, content_loading: role === "admin" });
      api(`/emails/${row.id}/conversation`, token).then(setConversation).catch(() => setConversation({ source_id: row.id, error: "Conversation details are unavailable." }));
      if (role === "admin") {
        try {
          const body = await api(`/emails/${row.id}/content`, token);
          setSelectedEmail((current: any) => current?.id === row.id ? { ...current, content: body.content, content_loading: false } : current);
        } catch (e) {
          setSelectedEmail((current: any) => current?.id === row.id ? { ...current, content_error: e instanceof Error ? e.message : "Unable to load message content", content_loading: false } : current);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load email");
    }
  };
  const assistReply = async (mode: "draft" | "correct" | "rewrite") => {
    if (!selectedEmail) return;
    setAssistantMode(mode);
    setError("");
    try {
      const result = await api(`/emails/${selectedEmail.id}/rewrite`, token, {
        method: "POST",
        body: JSON.stringify({ mode, body: replyDraft }),
      });
      setReplyDraft(result.body);
      setNotice(mode === "draft" ? "AI draft ready for your review." : "Updated draft ready for your review.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI could not prepare a reply");
    } finally {
      setAssistantMode("");
    }
  };
  const sendReply = async () => {
    if (!selectedEmail || !replyDraft.trim()) return;
    setReplyBusy(true);
    setError("");
    try {
      const result = await api(`/emails/${selectedEmail.id}/reply`, token, {
        method: "POST",
        body: JSON.stringify({ body: replyDraft }),
      });
      setSelectedEmail((current: any) => current?.id === selectedEmail.id
        ? { ...current, status: "replied", replied_at: result.replied_at }
        : current);
      setReplyDraft("");
      setNotice(`Reply sent to ${result.recipient}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reply could not be sent");
    } finally {
      setReplyBusy(false);
    }
  };
  const assignEmail = async (employeeId: string) => {
    if (!selectedEmail) return;
    try {
      const suffix = employeeId ? `?employee_id=${employeeId}` : "";
      await api(`/emails/${selectedEmail.id}/assignment${suffix}`, token, {
        method: "PATCH",
      });
      setSelectedEmail({
        ...selectedEmail,
        assigned_employee_id: employeeId ? Number(employeeId) : null,
      });
      setNotice(text("notice.email_assignment_updated"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Assignment failed");
    }
  };
  const updateEmailStatus = async (status: "pending" | "ignored") => {
    if (!selectedEmail) return;
    try {
      await api(`/emails/${selectedEmail.id}/status`, token, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      });
      setSelectedEmail((current: any) => current?.id === selectedEmail.id ? { ...current, status } : current);
      setNotice(status === "ignored" ? "Email marked ignored." : "Email returned to pending.");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Email status update failed");
    }
  };
  const editMailbox = (row: any) => {
    setEditingMailboxId(row.id);
    setMailbox({
      address: row.address,
      display_name: row.display_name,
      provider: row.provider || "microsoft",
      timezone: row.timezone,
      status: row.status,
      azure_client_id: row.azure_client_id || "",
      azure_tenant_id: row.azure_tenant_id || "",
      azure_client_secret: "",
    });
    setDialog(true);
  };
  const removeMailbox = async (row: any) => {
    if (!window.confirm(`Remove mailbox ${row.address}?`)) return;
    try {
      await api(`/mailboxes/${row.id}`, token, { method: "DELETE" });
      setData((current: any) =>
        Array.isArray(current) ? current.filter((item) => item.id !== row.id) : current,
      );
      setMailboxes((current) => current.filter((item) => item.id !== row.id));
      setNotice(text("notice.mailbox_removed"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to remove mailbox");
    }
  };
  const removeEmployee = async (row: any) => {
    if (!window.confirm(`Remove employee ${row.employee || row.name}?`)) return;
    try {
      await api(`/employees/${row.id}`, token, { method: "PATCH", body: JSON.stringify({ active: false }) });
      setNotice("Employee removed.");
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to remove employee"); }
  };
  const openEmployee = async (row: any) => {
    const query = new URLSearchParams(location.search);
    if (query.get("view") === "employee" && Number(query.get("id")) === row.id) {
      history.replaceState({ employeeAnalytics: true }, "", `?view=employee&id=${row.id}`);
    } else {
      history.pushState({ employeeAnalytics: true }, "", `?view=employee&id=${row.id}`);
    }
    const today = localDateKey();
    setSelectedEmployee(row); setEmployeeTrend([]); setEmployeeHistory([]); setEmployeeHourly([]); setEmployeeDailySenders([]); setEmployeeMailReport(null); setEmployeePeriod("rolling"); setEmployeeReportPeriod("daily"); setEmployeeHourlyDate(today); setEmployeeSelectedDate(today);
    try {
      const trend = await api(`/employees/${row.id}/trend`, token);
      setEmployeeTrend(trend);
      setEmployeeHistory(trend);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load employee trend"); }
  };
  const closeEmployeeAnalytics = () => {
    if (history.state?.employeeAnalytics) history.back();
    else {
      setSelectedEmployee(null);
      history.replaceState(null, "", "?view=Employee%20Performance");
    }
  };
  const changeEmployeePeriod = async (period: string) => {
    if (!selectedEmployee?.id) return;
    setEmployeePeriod(period);
    setEmployeeHistory([]);
    try {
      const history = period === "rolling"
        ? await api(`/employees/${selectedEmployee.id}/trend`, token)
        : await api(`/employees/${selectedEmployee.id}/trend?year=${period}`, token);
      setEmployeeHistory(history);
      setEmployeeTrend(history);
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to load employee activity"); }
  };
  useEffect(() => {
    if (!selectedEmployee?.id) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const history = employeePeriod === "rolling"
          ? await api(`/employees/${selectedEmployee.id}/trend`, token)
          : await api(`/employees/${selectedEmployee.id}/trend?year=${employeePeriod}`, token);
        if (!cancelled) { setEmployeeHistory(history); setEmployeeTrend(history); }
      } catch { /* Keep the last successful calendar during a temporary connection failure. */ }
    };
    const timer = window.setInterval(refresh, 30000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [selectedEmployee?.id, token, employeePeriod]);
  useEffect(() => {
    if (!selectedEmployee?.id) return;
    let cancelled = false;
    api(`/employees/${selectedEmployee.id}/hourly-activity?day=${employeeHourlyDate}`, token)
      .then((activity) => { if (!cancelled) setEmployeeHourly(activity); })
      .catch(() => { if (!cancelled) setEmployeeHourly([]); });
    return () => { cancelled = true; };
  }, [selectedEmployee?.id, token, employeeHourlyDate]);
  useEffect(() => {
    if (!selectedEmployee?.id) return;
    let cancelled = false;
    api(`/employees/${selectedEmployee.id}/daily-senders?day=${employeeSelectedDate}`, token)
      .then((senders) => { if (!cancelled) setEmployeeDailySenders(senders); })
      .catch(() => { if (!cancelled) setEmployeeDailySenders([]); });
    return () => { cancelled = true; };
  }, [selectedEmployee?.id, token, employeeSelectedDate]);
  useEffect(() => {
    if (!selectedEmployee?.id) return;
    let cancelled = false;
    api(`/reports/${employeeReportPeriod}/employees/${selectedEmployee.id}/mail`, token)
      .then((result) => { if (!cancelled) setEmployeeMailReport(result); })
      .catch(() => { if (!cancelled) setEmployeeMailReport({ mails: [] }); });
    return () => { cancelled = true; };
  }, [selectedEmployee?.id, token, employeeReportPeriod]);

  useEffect(() => {
    if (!aiReviewOpen || aiReviewConsent || !aiReviewEmployeeId || !aiReviewEnabled) return;
    let cancelled = false;
    let fetching = false;
    const timer = window.setInterval(async () => {
      if (fetching) return;
      fetching = true;
      try {
        const result = await api(`/reports/${reportPeriod}/employees/${aiReviewEmployeeId}/ai-review?page=${aiReviewPage}&page_size=100`, token);
        if (!cancelled) setAiReviewResult(result);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Review progress could not be refreshed");
      } finally {
        fetching = false;
      }
    }, 10000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [aiReviewOpen, aiReviewConsent, aiReviewEmployeeId, aiReviewEnabled, reportPeriod, aiReviewPage, token]);

  // Keep all hooks above this point so the auth transition never changes the
  // hook order between renders.
  if (authChecking) return <Box className="loading"><CircularProgress /></Box>;
  if (!token) return <Login onLogin={setToken} />;

  const connectMailbox = async (row: any) => {
    const authWindow = window.open("about:blank", "_blank");
    if (!authWindow) {
      setError("Allow popups for OEIS, then click Connect Outlook again.");
      return;
    }
    try {
      const path = row.provider === "gmail" ? `/mailboxes/${row.id}/gmail/oauth/start` : `/mailboxes/${row.id}/oauth/start`;
      const result = await api(path, token, {
        method: "POST",
      });
      authWindow.location.href = result.auth_url;
      setNotice(`${row.provider === "gmail" ? "Google" : "Microsoft"} login opened. Finish login, then click Sync.`);
    } catch (e) {
      authWindow?.close();
      setError(e instanceof Error ? e.message : "Unable to start mailbox login");
    }
  };
  const editPerson = (kind: "employee" | "user", row: any) => {
    const source =
      kind === "employee"
        ? employees.find((employee) => employee.id === row.id) || row
        : row;
    setEditingPersonId(row.id);
    setPerson({
      name: source.name || source.employee,
      email: source.email || "",
      department: source.department || "General",
      password: "",
      role: source.role || "manager",
      active: source.active ?? true,
      mailbox_ids: source.mailbox_ids || [],
    });
    setCreateDialog(kind);
  };
  const downloadReport = async (format: "xlsx" | "csv" | "pdf", dimension = reportDimension) => {
    try {
      const params = new URLSearchParams({ dimension, format });
      if (reportDimension === "employee" && departmentFilter) params.set("department", departmentFilter);
      if (reportDimension === "employee" && aiReviewEmployeeId) params.set("employee_id", aiReviewEmployeeId);
      const response = await fetch(
        `/api/reports/${reportPeriod}/export?${params}`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!response.ok) throw new Error("Report export failed");
      const href = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = href;
      link.download = `oeis-${reportPeriod}-${dimension}.${format}`;
      link.click();
      URL.revokeObjectURL(href);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Report export failed");
    }
  };
  const viewSenderReport = async () => {
    if (!aiReviewEmployeeId) return;
    try {
      const result = await api(`/reports/${reportPeriod}?dimension=customer&employee_id=${aiReviewEmployeeId}`, token);
      setSenderReport(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sender report could not be loaded");
    }
  };
  const generateEmployeeAIReview = async (page = aiReviewPage, employeeId = aiReviewEmployeeId) => {
    if (!employeeId) return;
    setAiReviewBusy(true);
    setError("");
    try {
      const result = await api(`/reports/${reportPeriod}/employees/${employeeId}/ai-review?page=${page}&page_size=100`, token);
      setAiReviewResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI review could not be prepared");
    } finally {
      setAiReviewBusy(false);
    }
  };
  const enableDailyAIReviews = async () => {
    setAiReviewBusy(true);
    setError("");
    try {
      const result = await api("/reports/ai-review/status", token, { method: "PATCH", body: JSON.stringify({ enabled: true }) });
      setAiReviewEnabled(!!result.enabled);
      setAiProviderConfigured(!!result.provider_configured);
      setAiSchedulerEnabled(!!result.scheduler_enabled);
      setAiReviewOpen(false);
      setNotice("Continuous AI coaching reviews are enabled.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Continuous AI reviews could not be enabled");
    } finally {
      setAiReviewBusy(false);
    }
  };
  const disableDailyAIReviews = async () => {
    try {
      const result = await api("/reports/ai-review/status", token, { method: "PATCH", body: JSON.stringify({ enabled: false }) });
      setAiReviewEnabled(!!result.enabled);
      setNotice("Continuous AI coaching reviews are disabled.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Continuous AI reviews could not be disabled");
    }
  };
  const saveSettings = async () => {
    try {
      const parsed = JSON.parse(settingsJson);
      const cleaned = parsed.map(
        ({ id, ...row }: Record<string, unknown>) => row,
      );
      await api(`/settings/${settingsView}`, token, {
        method: "PATCH",
        body: JSON.stringify(cleaned),
      });
      await load();
      setNotice("Settings saved successfully.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Settings update failed");
    }
  };
  const saveSyncSettings = async () => {
    setSavingSyncSettings(true);
    try {
      const result = await api("/system/sync-settings", token, {
        method: "PATCH",
        body: JSON.stringify({
          interval_seconds: syncSettings.interval_seconds,
          scheduler_enabled: syncSettings.scheduler_enabled,
        }),
      });
      setSyncSettings(result);
      setNotice("Synchronization settings saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Synchronization settings update failed");
    } finally {
      setSavingSyncSettings(false);
    }
  };
  const saveAiConfig = async () => {
    if (!aiConfig) return;
    setSavingAiConfig(true);
    setError("");
    try {
      const saved = await api("/settings/ai-provider", token, { method: "PATCH", body: JSON.stringify({ provider: aiConfig.provider, model: aiConfig.model, api_key: aiKey || null }) });
      setAiConfig(saved);
      setAiKey("");
      setAiTestResult(null);
      setNotice(saved.reviews_queued ? `AI provider and model saved. ${saved.reviews_queued} failed review${saved.reviews_queued === 1 ? "" : "s"} queued for retry.` : "AI provider and model saved. New AI requests use this selection.");
    } catch (e) { setError(e instanceof Error ? e.message : "AI settings could not be saved"); }
    finally { setSavingAiConfig(false); }
  };
  const testAiConfig = async () => {
    setTestingAiConfig(true);
    setAiTestResult(null);
    try { const result=await api("/settings/ai-provider/test", token, { method: "POST" }); setAiTestResult(result); setAiConfig((current) => current ? { ...current, last_check: result } : current); }
    catch (e) { setAiTestResult({ ok:false, message:e instanceof Error ? e.message : "AI connection test failed", model:aiConfig?.model || "", tested_at:new Date().toISOString() }); }
    finally { setTestingAiConfig(false); }
  };
  const runSync = async () => {
    setSyncing(true);
    try {
      const result = await api("/sync/trigger", token, { method: "POST" });
      const [health, mailboxOptions] = await Promise.all([
        api("/system/readiness", token),
        api("/mailbox-options", token),
      ]);
      setReadiness(health);
      setMailboxes(mailboxOptions);
      await load();
      const fetched = Number(result.emails_fetched || 0);
      const added = Number(result.emails_new || 0);
      const failed = Number(result.failed_mailboxes || 0);
      setNotice(
        failed
          ? `Synchronization finished with ${failed} mailbox error. Fetched ${fetched}, new ${added}.`
          : `Synchronization complete. Fetched ${fetched}, new ${added}.`,
      );
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Unable to start synchronization",
      );
    } finally {
      setSyncing(false);
    }
  };
  const sendSummary = async () => {
    try {
      const result = await api("/reports/daily/send", token, { method: "POST" });
      setNotice(`Daily summary sent to ${result.recipient}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to send daily summary");
    }
  };
  const side = (
    <Box className="side" data-tour="navigation">
      <Box className="brand">
        <OeisLogo compact />
      </Box>
      <Typography className="rail-label">{text("shell.operations")}</Typography>
      {visibleSections.map(({ name, description, icon }) => (
        <Button
          key={name}
          data-tour={tourTargets[name]}
          className={section === name ? "active" : ""}
          startIcon={icon}
          onClick={() => {
            navigateSection(name);
          }}
        >
          <Box className="nav-copy">
            <b>{displayName(name)}</b>
            <small>{displayDescription(name, description)}</small>
          </Box>
        </Button>
      ))}
      <Box className="system">
        <Sync />
        <Box>
          <b>
            {readiness?.operational
              ? text("shell.integration_operational")
              : readiness?.error_mailboxes
                ? text("shell.integration_attention")
                : readiness?.warning_mailboxes
                  ? "Temporary sync warning"
                : text("shell.scheduler_configured")}
          </b>
          <small>
            {readiness?.last_successful_sync
              ? format("shell.last_sync", { time: new Date(readiness.last_successful_sync).toLocaleTimeString() })
              : text("shell.delta_interval")}
          </small>
        </Box>
      </Box>
    </Box>
  );
  return (
    <Box className="shell">
      <a className="skip-link" href="#main-content">
        {text("shell.skip")}
      </a>
      <Box className="desktop-nav">{side}</Box>
      <Drawer
        open={mobile}
        onClose={() => setMobile(false)}
        ModalProps={{
          disableAutoFocus: tourOpen,
          disableEnforceFocus: tourOpen,
          disableRestoreFocus: tourOpen,
        }}
      >
        {side}
      </Drawer>
      <Box className={`workspace${selectedEmployee ? " workspace-employee" : ""}`}>
        <Box className="top">
          <IconButton
            className="mobile-menu"
            aria-label={text("top.open_nav")}
            onClick={() => setMobile(true)}
          >
            <MenuIcon />
          </IconButton>
          <Box>
            <small>{text("top.product")}</small>
            <b>{text("top.scope")}</b>
          </Box>
          <Box className="top-right">
            <Button
              data-tour="help"
              className="guide-button"
              variant="text"
              startIcon={<HelpOutline />}
              onClick={() => setTourOpen(true)}
            >
              {text("top.guide")}
            </Button>
            <Button
              className="signout-button"
              variant="outlined"
              startIcon={<Logout />}
              onClick={async () => {
                await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
                setToken("");
              }}
            >
              {text("top.sign_out")}
            </Button>
            {role === "admin" && (
              <Button
                data-tour="sync"
                className="sync-button"
                variant="contained"
                color="info"
                startIcon={<Sync />}
                disabled={syncing}
                onClick={runSync}
              >
                {syncing ? text("top.syncing") : text("top.sync_now")}
              </Button>
            )}
          </Box>
        </Box>
      <Box className="main" id="main-content" data-tour="workspace">
        {selectedEmployee && <Box className="employee-analytics-page">
          <Box className="employee-analytics-title"><Box><Typography variant="overline">EMPLOYEE PERFORMANCE</Typography><Typography variant="h4">Activity analytics</Typography><Typography variant="body2">Assigned mail and reply contribution for the selected period</Typography></Box><Box className="employee-title-actions"><Typography variant="h5">{selectedEmployee.employee}</Typography><Button onClick={closeEmployeeAnalytics} variant="outlined">Back to employees</Button></Box></Box>
          <Box className="employee-analytics-content">
            {(() => {
              const selectedDay = employeeHistory.find((day) => day.date === employeeSelectedDate) ?? {
                date: employeeSelectedDate, received: 0, replied: 0, pending: 0, ignored: 0,
              };
              const periodTotals = ["received", "replied", "replied_by_other", "pending", "ignored"].map((key) => ({ key, value: employeeHistory.reduce((total, day) => total + Number(day[key] || 0), 0) }));
              const periodLabel = employeePeriod === "rolling" ? "Last 365 days" : employeePeriod;
              return <>
            <Box className="employee-calendar-layout">
            <Box className="employee-calendar-main">
            <Box className="contribution-panel">
              {(() => {
                const receivedTotal = Number(selectedDay?.received || 0);
                const repliedTotal = Number(selectedDay?.replied || 0);
                const completion = receivedTotal ? Math.round((repliedTotal / receivedTotal) * 100) : 0;
                return <Box className="contribution-summary">
                  <Box className="received-metric">
                    <Typography variant="overline">MAIL VOLUME</Typography>
                    <Typography variant="subtitle2">Received mail</Typography>
                    <Typography className="metric-value" variant="h4">{receivedTotal.toLocaleString()}</Typography>
                    <Typography variant="caption">Assigned on {formatIndiaDate(employeeSelectedDate, { day: "2-digit", month: "2-digit", year: "numeric" })}</Typography>
                  </Box>
                  <Box className="completion-metric">
                    <Box className="completion-heading">
                      <Box><Typography variant="overline">REPLY PERFORMANCE</Typography><Typography variant="subtitle2">Reply completion</Typography></Box>
                      <Typography className="completion-value" variant="h4">{completion}%</Typography>
                    </Box>
                    <Box className="completion-track" role="progressbar" aria-label="Reply completion" aria-valuemin={0} aria-valuemax={100} aria-valuenow={completion}><Box className="completion-fill" style={{ width: `${completion}%` }} /></Box>
                    <Typography variant="caption">{repliedTotal.toLocaleString()} of {receivedTotal.toLocaleString()} emails received that day were replied</Typography>
                  </Box>
                  <TextField className="daily-metric-date" type="date" size="small" label="Activity date (dd/mm/yyyy)" lang="en-IN" value={employeeSelectedDate} onChange={(event) => { const date = event.target.value; setEmployeeSelectedDate(date); setEmployeeHourlyDate(date); }} InputLabelProps={{ shrink: true }} />
                </Box>;
              })()}
              <GitHubCalendar key={selectedEmployee.id} data={employeeHistory.map(day => ({ date: day.date, count: Number(day.replied || 0), received: Number(day.received || 0), pending: Number(day.pending || 0), ignored: Number(day.ignored || 0) }))} selectedDate={employeeSelectedDate} onPeriodChange={changeEmployeePeriod} onDaySelect={(date) => { setEmployeeSelectedDate(date); setEmployeeHourlyDate(date); }} />
              <Typography variant="caption">Each box represents one day. Darker green means a higher percentage replied; empty days remain visible.</Typography>
            </Box>
              <Box className="employee-summary-row">
              <Box className="employee-day-status employee-summary-card" aria-label={`Mail status for ${formatIndiaDate(employeeSelectedDate, { day: "2-digit", month: "2-digit", year: "numeric" })}`}>
                <Box className="employee-summary-heading"><Typography variant="overline">SELECTED DAY</Typography><Typography variant="subtitle2">{formatIndiaDate(employeeSelectedDate, { day: "2-digit", month: "2-digit", year: "numeric" })}</Typography></Box>
                <Box className="employee-summary-content">
                  <Box className="employee-day-status-metrics">{[{ key: "replied", label: "Replied", color: "#18734e" }, { key: "pending", label: "Pending", color: "#bd7b18" }, { key: "ignored", label: "Ignored", color: "#718096" }].map(({ key, label, color }) => <Box className="employee-day-status-item" key={key}><Typography variant="caption">{label}</Typography><Typography variant="h6" sx={{ color }}>{Number(selectedDay[key] || 0).toLocaleString()}</Typography></Box>)}</Box>
                  <Box className="employee-summary-pie"><Doughnut data={{ labels: ["Replied", "Pending", "Ignored"], datasets: [{ data: [Number(selectedDay.replied || 0), Number(selectedDay.pending || 0), Number(selectedDay.ignored || 0)], backgroundColor: ["#18734e", "#bd7b18", "#94a3b8"], borderWidth: 0 }] }} options={{ responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => `${context.label}: ${Number(context.raw).toLocaleString()}` } } } }} />{Number(selectedDay.replied || 0) + Number(selectedDay.pending || 0) + Number(selectedDay.ignored || 0) > 0 && <Typography variant="caption" className="employee-pie-center">{(Number(selectedDay.replied || 0) + Number(selectedDay.pending || 0) + Number(selectedDay.ignored || 0)).toLocaleString()}<small>total</small></Typography>}</Box>
                </Box>
              </Box>
              <Box className="employee-period-summary employee-summary-card">
                <Box className="employee-summary-heading"><Typography variant="overline">PERIOD TOTALS</Typography><Typography variant="subtitle2">{periodLabel}</Typography></Box>
                <Box className="employee-summary-content">
                  <Box className="employee-period-total-list">{periodTotals.map(({ key, value }) => <Box className={`employee-period-total ${key}`} key={key}><Typography variant="caption">{key === "replied_by_other" ? "Replied by someone else" : key}</Typography><Typography variant="h5">{value.toLocaleString()}</Typography></Box>)}</Box>
                  <Box className="employee-summary-pie employee-period-pie"><Doughnut data={{ labels: ["Received", "Replied", "Replied by someone else", "Pending", "Ignored"], datasets: [{ data: periodTotals.map(({ value }) => value), backgroundColor: ["#3478f6", "#16885f", "#64748b", "#e4a323", "#94a3b8"], borderWidth: 0 }] }} options={{ responsive: true, maintainAspectRatio: false, cutout: "62%", animation: { duration: 900, animateRotate: true, animateScale: true }, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => `${context.label}: ${Number(context.raw).toLocaleString()}` } } } }} />{periodTotals.reduce((sum, item) => sum + item.value, 0) > 0 && <Typography variant="caption" className="employee-pie-center">{periodTotals.reduce((sum, item) => sum + item.value, 0).toLocaleString()}<small>total</small></Typography>}</Box>
                </Box>
              </Box>
            </Box>
            </Box>
            </Box>
            <Box className="employee-mail-report">
              <Box className="employee-mail-report-head">
                <Box><Typography variant="overline">MAIL-WISE REPORT</Typography><Typography variant="subtitle2">Why each mail appears in this review</Typography><Typography variant="caption">Every received mail assigned to {selectedEmployee.employee}, with the status and evidence used in coaching visibility.</Typography></Box>
                <TextField select size="small" label="Report template" value={employeeReportPeriod} onChange={(event) => setEmployeeReportPeriod(event.target.value)} sx={{ minWidth: 150 }}>
                  <MenuItem value="daily">Daily · today</MenuItem><MenuItem value="weekly">Weekly · 7 days</MenuItem><MenuItem value="monthly">Monthly · month</MenuItem>
                </TextField>
              </Box>
              <Box className="employee-mail-report-summary"><Chip label={`${employeeMailReport?.mails?.length || 0} mails`} /><Typography variant="caption">AI reviews are evidence-led: classification, SLA urgency, reply status, and received time are shown so an admin can understand how the review was formed.</Typography></Box>
              <Box className="employee-mail-list">
                {employeeMailReport?.mails?.length ? employeeMailReport.mails.map((mail: any) => <Box className="employee-mail-row" key={mail.id}>
                  <Box className="employee-mail-main"><Typography variant="subtitle2" noWrap>{mail.subject}</Typography><Typography variant="caption" noWrap>{mail.sender} · {mail.received_at ? new Date(mail.received_at).toLocaleString() : "—"}</Typography></Box>
                  <Chip size="small" label={mail.status_label || mail.status} color={mail.status === "replied" && mail.replied_by_you !== false ? "success" : mail.status === "pending" ? "warning" : "default"} />
                  <Box className="employee-mail-reason"><Typography variant="caption">Reason / evidence</Typography><Typography variant="body2">{mail.reason}</Typography></Box>
                </Box>) : <Typography variant="body2" color="text.secondary">No received mail for this employee in the selected template period.</Typography>}
              </Box>
            </Box>
            <Box className="employee-chart-grid">
              <Box className="employee-chart-card">
                <Typography variant="subtitle2">Received from · {formatIndiaDate(employeeSelectedDate, { day: "2-digit", month: "2-digit", year: "numeric" })}</Typography>
                <Box className="daily-sender-list">
                  {employeeDailySenders.length ? employeeDailySenders.map((sender) => <Box className="daily-sender-row" key={sender.sender} title={`${sender.sender}: ${sender.count} received`}><Box className="daily-sender-label"><Typography variant="body2" noWrap>{sender.sender}</Typography><Typography variant="subtitle2">{sender.count}</Typography></Box><LinearProgress variant="determinate" value={Math.max(4, sender.count / employeeDailySenders[0].count * 100)} /></Box>) : <Typography variant="body2" color="text.secondary">No received emails from senders on this day.</Typography>}
                </Box>
              </Box>
              <Box className="employee-chart-card">
                <Box className="hourly-chart-heading"><Box><Typography variant="subtitle2">Mail received by time</Typography><Typography variant="caption">{formatIndiaDate(employeeHourlyDate, { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" })} · mailbox local time</Typography></Box><TextField type="date" size="small" label="Activity date (dd/mm/yyyy)" lang="en-IN" value={employeeHourlyDate} onChange={(event) => setEmployeeHourlyDate(event.target.value)} InputLabelProps={{ shrink: true }} /></Box>
                <Line data={{ labels: employeeHourly.map((slot) => { const minutes = slot.slot * 30; const hour = Math.floor(minutes / 60); const minute = minutes % 60; return `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${hour >= 12 ? "PM" : "AM"}`; }), datasets: [{ label: "Received", data: employeeHourly.map((slot) => slot.received), borderColor: "#2f6fed", backgroundColor: "rgba(47,111,237,.10)", fill: true, tension: .25, pointRadius: 2, pointHoverRadius: 5 }] }} options={{ responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => `${context.parsed.y} email${context.parsed.y === 1 ? "" : "s"} received` } } }, scales: { x: { title: { display: true, text: "Time email was received" }, ticks: { maxRotation: 45, minRotation: 35, autoSkip: true, maxTicksLimit: 10 } }, y: { beginAtZero: true, ticks: { precision: 0, stepSize: 1 }, title: { display: true, text: "Emails received" } } } }} />
              </Box>
            </Box>
              </>;
            })()}
          </Box>
        </Box>}
        {!selectedEmployee && <Box>
          <Box className="hero">
            <Box>
              <Typography className="date">
                {pageEyebrow(section)}
              </Typography>
              <Typography variant="h4" component="h1">
                {displayName(section)}
              </Typography>
              <Typography color="text.secondary">
                {pageDescription(section)}
              </Typography>
            </Box>
            {section === "Mailboxes" && (
              <Button
                variant="contained"
                color="info"
                onClick={() => {
                  setEditingMailboxId(null);
                  setGraphSetup(null);
                  setGmailSetup(null);
                  setMailbox({
                    address: "",
                    display_name: "",
                    provider: "microsoft",
                    timezone: "Asia/Kolkata",
                    status: "active",
                    azure_client_id: "",
                    azure_tenant_id: "",
                    azure_client_secret: "",
                  });
                  setDialog(true);
                }}
              >
                <Add sx={{ mr: 1 }} /> {text("action.add_mailbox")}
              </Button>
            )}
            {role === "admin" && ["Employee List", "Employee Performance"].includes(section) && (
              <Button
                variant="contained"
                color="info"
                startIcon={<Add />}
                onClick={() => {
                  setEditingPersonId(null);
                  setPerson({
                    name: "",
                    email: "",
                    department: departmentFilter || "Sales",
                    password: "",
                    role: "manager",
                    active: true,
                    mailbox_ids: [],
                  });
                  setCreateDialog("employee");
                }}
              >
                {text("action.add_employee")}
              </Button>
            )}
            {section === "Users & Roles" && (
              <Button
                variant="contained"
                color="info"
                startIcon={<Add />}
                onClick={() => {
                  setEditingPersonId(null);
                  setPerson({
                    name: "",
                    email: "",
                    department: "General",
                    password: "",
                    role: "manager",
                    active: true,
                    mailbox_ids: [],
                  });
                  setCreateDialog("user");
                }}
              >
                {text("action.add_user")}
              </Button>
            )}
          </Box>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          {loading ? (
            <Box className="loading inline">
              <CircularProgress />
            </Box>
          ) : section === "Dashboard" && data ? (
            <ReferenceDashboard
              data={data}
              employeePerformance={employeePerformance}
              employeeConnections={employeeConnections}
              replyRate={replyRate}
              growth={growth}
              insights={insights}
              readiness={readiness}
              onNavigate={navigateSection}
              onSync={runSync}
              canSync={role === "admin"}
            />
          ) : (
            <Card className="table-card">
              {section === "Pending Emails" && (
                <Box className="toolbar">
                  <TextField
                    size="small"
                    label={text("filter.search")}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                  />
                  <TextField
                    select
                    size="small"
                    label={text("filter.status")}
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    sx={{ minWidth: 140 }}
                  >
                    <MenuItem value="">{text("filter.pending")}</MenuItem>
                    <MenuItem value="critical">{text("filter.critical")}</MenuItem>
                    <MenuItem value="overdue">{text("filter.overdue")}</MenuItem>
                    <MenuItem value="replied">{text("filter.replied")}</MenuItem>
                    <MenuItem value="ignored">Ignored</MenuItem>
                    <MenuItem value="observer_copy">Observer copy</MenuItem>
                    <MenuItem value="duplicate_copy">Duplicate copy</MenuItem>
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label={text("filter.date")}
                    value={dateFilter}
                    onChange={(e) => setDateFilter(e.target.value)}
                    sx={{ minWidth: 140 }}
                  >
                    <MenuItem value="">{text("filter.any_date")}</MenuItem>
                    <MenuItem value="today">{text("filter.today")}</MenuItem>
                    <MenuItem value="yesterday">{text("filter.yesterday")}</MenuItem>
                    <MenuItem value="week">{text("filter.week")}</MenuItem>
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label={text("filter.mailbox")}
                    value={mailboxFilter}
                    onChange={(e) => setMailboxFilter(e.target.value)}
                    sx={{ minWidth: 180 }}
                  >
                    <MenuItem value="">{text("filter.all_mailboxes")}</MenuItem>
                    {mailboxes.map((m) => (
                      <MenuItem key={m.id} value={String(m.id)}>
                        {m.display_name}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label={text("filter.employee")}
                    value={employeeFilter}
                    onChange={(e) => setEmployeeFilter(e.target.value)}
                    sx={{ minWidth: 180 }}
                  >
                    <MenuItem value="">{text("filter.all_employees")}</MenuItem>
                    {employees.map((e) => (
                      <MenuItem key={e.id} value={String(e.id)}>
                        {e.name}
                      </MenuItem>
                    ))}
                  </TextField>
                  <Button onClick={load}>{text("filter.apply")}</Button>
                  <Button variant={pendingView === "board" ? "contained" : "text"} onClick={() => setPendingView((value) => value === "table" ? "board" : "table")}>{pendingView === "board" ? "List view" : "Board view"}</Button>
                  <Button
                    onClick={() => {
                      setSearch("");
                      setStatusFilter("");
                      setDateFilter("");
                      setMailboxFilter("");
                      setEmployeeFilter("");
                      setPage(1);
                    }}
                  >
                    {text("filter.clear")}
                  </Button>
                </Box>
              )}
              {section === "Reports" && (
                <Box className="toolbar">
                  <TextField
                    select
                    size="small"
                    label={text("report.period")}
                    value={reportPeriod}
                    onChange={(e) => { setReportPeriod(e.target.value); setAiReviewEmployeeId(""); setAiReviewPage(1); setAiReviewResult(null); }}
                    sx={{ minWidth: 130 }}
                  >
                    <MenuItem value="daily">{text("report.daily")}</MenuItem>
                    <MenuItem value="weekly">{text("report.weekly")}</MenuItem>
                    <MenuItem value="monthly">{text("report.monthly")}</MenuItem>
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label={text("report.dimension")}
                    value={reportDimension}
                    onChange={(e) => { setReportDimension(e.target.value); setAiReviewEmployeeId(""); setAiReviewPage(1); setAiReviewResult(null); }}
                    sx={{ minWidth: 150 }}
                  >
                    <MenuItem value="department">Department-wise</MenuItem>
                    <MenuItem value="employee">{text("report.employee")}</MenuItem>
                    <MenuItem value="customer">{text("report.customer")}</MenuItem>
                    <MenuItem value="mailbox">{text("report.mailbox")}</MenuItem>
                  </TextField>
                  {reportDimension === "employee" && (
                    <>
                      <Box className="department-switcher" role="group" aria-label="Filter report by department">
                        {["All departments", ...departmentOptions].map((department) => {
                          const value = department === "All departments" ? "" : department;
                          const count = value ? rows.filter((row) => row.department === value).length : rows.length;
                          return <Button key={department} variant={departmentFilter === value ? "contained" : "outlined"} onClick={() => { setDepartmentFilter(value); setAiReviewEmployeeId(""); }}>{department}<Chip size="small" label={count} /></Button>;
                        })}
                      </Box>
                      <TextField select size="small" label="Employee" value={aiReviewEmployeeId} onChange={(event) => { setAiReviewEmployeeId(event.target.value); setAiReviewPage(1); }} sx={{ minWidth: 210 }}>
                        <MenuItem value="">All employees</MenuItem>
                        {rows.filter((row) => row.employee_id && (!departmentFilter || row.department === departmentFilter)).map((row) => <MenuItem key={row.employee_id} value={String(row.employee_id)}>{row.dimension} · {row.department}</MenuItem>)}
                      </TextField>
                      <Button disabled={!aiReviewEmployeeId} onClick={viewSenderReport}>View sender counts</Button>
                      <Button disabled={!aiReviewEmployeeId} onClick={() => { setAiReviewConsent(false); setAiReviewResult(null); setAiReviewPage(1); setAiReviewOpen(true); void generateEmployeeAIReview(1); }}>View AI coaching report</Button>
                      {aiReviewEnabled ? (
                        <>
                          {role === "admin" && <Button color="warning" onClick={disableDailyAIReviews}>Disable continuous AI reviews</Button>}
                        </>
                      ) : role === "admin" ? (
                        <>
                          <Button disabled={!aiProviderConfigured || !aiSchedulerEnabled} onClick={() => { setAiReviewConsent(true); setAiReviewResult(null); setAiReviewOpen(true); }}>Enable continuous AI reviews</Button>
                          {!aiProviderConfigured && <Typography variant="caption">Configure the AI provider to enable reviews.</Typography>}
                          {aiProviderConfigured && !aiSchedulerEnabled && <Typography variant="caption">Enable the backend scheduler and restart the app to run continuous reviews.</Typography>}
                        </>
                      ) : (
                        <Typography variant="caption">Continuous AI reviews are not enabled.</Typography>
                      )}
                    </>
                  )}
                  <Button onClick={() => downloadReport("xlsx")}>
                    {text("report.export_excel")}
                  </Button>
                  <Button onClick={() => downloadReport("csv")}>
                    Export CSV
                  </Button>
                  <Button onClick={() => downloadReport("pdf")}>
                    {text("report.export_pdf")}
                  </Button>
                  {role === "admin" && (
                    <Button onClick={sendSummary} disabled={!readiness?.smtp_configured}>
                      {text("report.send_daily")}
                    </Button>
                  )}
                  {role === "admin" && !readiness?.smtp_configured && <Typography variant="caption">Connect an Outlook mailbox to email the report.</Typography>}
                </Box>
              )}
              {section === "Reports" && <Alert severity="info" sx={{ mb: 2 }}>
                {reportPeriod === "daily" ? "Today" : reportPeriod === "weekly" ? "Last 7 days" : "This month"} · Inbox copies received since {formatMailboxDateTime(data?.period_start)}. Ignored, observer, and duplicate copies are separate report columns; reply rate uses replied and pending obligations.
                {rows.every((row) => Number(row.total_received) === 0) && <> No incoming mail was received in this period.{data?.latest_received_at && <> Latest received mail: {formatMailboxDateTime(data.latest_received_at)}.</>} Choose a longer period to see earlier mail.</>}
              </Alert>}
              {section === "Employee Performance" && (
                <Box className="toolbar performance-toolbar">
                  <Box className="department-switcher" role="group" aria-label="Filter employees by department">
                    {["All departments", ...departmentOptions].map((department) => {
                      const value = department === "All departments" ? "" : department;
                      const count = value ? departmentCount(value) : rows.length;
                      return <Button key={department} variant={departmentFilter === value ? "contained" : "outlined"} onClick={() => setDepartmentFilter(value)}>{department}<Chip size="small" label={count} /></Button>;
                    })}
                  </Box>
                  <TextField
                    select
                    size="small"
                    label={text("performance.sort_by")}
                    value={performanceSort}
                    onChange={(e) => setPerformanceSort(e.target.value)}
                    sx={{ minWidth: 180 }}
                  >
                    <MenuItem value="employee">{text("performance.employee")}</MenuItem>
                    <MenuItem value="total">{text("performance.total")}</MenuItem>
                    <MenuItem value="average_reply_time">
                      {text("performance.average")}
                    </MenuItem>
                    <MenuItem value="pending">{text("performance.pending")}</MenuItem>
                    <MenuItem value="critical">{text("performance.critical")}</MenuItem>
                    <MenuItem value="resolved">{text("performance.resolved")}</MenuItem>
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label={text("performance.order")}
                    value={performanceOrder}
                    onChange={(e) => setPerformanceOrder(e.target.value)}
                    sx={{ minWidth: 130 }}
                  >
                    <MenuItem value="asc">{text("performance.ascending")}</MenuItem>
                    <MenuItem value="desc">{text("performance.descending")}</MenuItem>
                  </TextField>
                </Box>
              )}
              {section === "Settings" && (
                <Box>
                  <Box className="toolbar">
                    {[
                      [text("settings.tab.sla"), "sla-rules"],
                      [text("settings.tab.classification"), "classification-rules"],
                      [text("settings.tab.calendars"), "business-calendars"],
                      [text("settings.tab.sync"), "synchronization"],
                    ].map(([label, value]) => (
                      <Button
                        key={value}
                        variant={settingsView === value ? "contained" : "text"}
                        onClick={() => {
                          setSettingsView(value);
                        }}
                      >
                        {label}
                      </Button>
                    ))}
                  </Box>
                  {settingsView === "synchronization" ? (
                    <SyncSettingsPanel
                      settings={syncSettings}
                      onChange={setSyncSettings}
                      onSave={saveSyncSettings}
                      onSync={runSync}
                      saving={savingSyncSettings}
                      syncing={syncing}
                    />
                  ) : (
                    <SettingsEditor
                      kind={settingsView}
                      json={settingsJson}
                      onChange={setSettingsJson}
                      onSave={saveSettings}
                    />
                  )}
                </Box>
              )}
              {section === "AI Settings" && aiConfig && (
                <Box sx={{ p: 3, display: "grid", gap: 2, maxWidth: 680 }}>
                  <Typography variant="h6">AI provider and model</Typography>
                  <Typography color="text.secondary">Choose where new AI drafts and employee reviews are sent. Each provider has its own usage limit.</Typography>
                  <TextField select label="Provider" value={aiConfig.provider} onChange={(e) => { const provider=e.target.value; setAiConfig({ ...aiConfig, provider, model:Object.keys(aiConfig.models[provider])[0] }); setAiKey(""); }}>
                    {Object.keys(aiConfig.models).map((provider) => <MenuItem key={provider} value={provider}>{provider === "openrouter" ? "OpenRouter" : provider === "nvidia" ? "NVIDIA" : "Gemini"}{aiConfig.configured[provider] ? " · key saved" : " · add key"}</MenuItem>)}
                  </TextField>
                  <TextField select label="Model" value={aiConfig.model} onChange={(e) => setAiConfig({ ...aiConfig, model:e.target.value })}>
                    {!aiConfig.models[aiConfig.provider]?.[aiConfig.model] && <MenuItem value={aiConfig.model}>{aiConfig.model} (current)</MenuItem>}
                    {Object.entries(aiConfig.models[aiConfig.provider] || {}).map(([id, label]) => <MenuItem key={id} value={id}>{label}</MenuItem>)}
                  </TextField>
                  <TextField label={`${aiConfig.provider === "openrouter" ? "OpenRouter" : aiConfig.provider === "nvidia" ? "NVIDIA" : "Gemini"} API key`} type="password" autoComplete="new-password" value={aiKey} onChange={(e) => setAiKey(e.target.value)} helperText={aiConfig.configured[aiConfig.provider] ? "A key is saved. Leave blank to keep it." : "Add a key before saving this provider."} />
                  <Button variant="contained" disabled={savingAiConfig || (!aiConfig.configured[aiConfig.provider] && !aiKey.trim())} onClick={saveAiConfig}>{savingAiConfig ? "Saving…" : "Save AI settings"}</Button>
                  <Button variant="outlined" disabled={testingAiConfig || savingAiConfig} onClick={testAiConfig}>{testingAiConfig ? "Testing…" : "Test saved connection"}</Button>
                  <Typography variant="caption">Save your provider and model first. This test sends only synthetic text and may use a few provider tokens.</Typography>
                  {aiTestResult && <Alert severity={aiTestResult.ok ? "success" : "error"}>{aiTestResult.message} Model: {aiTestResult.model}. Tested {new Date(aiTestResult.tested_at).toLocaleString()}.</Alert>}
                  {!aiTestResult && aiConfig.last_check && <Alert severity={aiConfig.last_check.ok ? "success" : "warning"}>Last automatic or manual check: {aiConfig.last_check.message} Model: {aiConfig.last_check.model}. Tested {new Date(aiConfig.last_check.tested_at).toLocaleString()}.{!aiConfig.last_check.ok && " Check the saved key or model, then retry."}</Alert>}
                  <Typography variant="caption">When scheduling is enabled, OEIS tests the saved model once daily with synthetic text. It never changes your provider or model automatically.</Typography>
                </Box>
              )}
              {section !== "Settings" && section !== "AI Settings" && (
                <>
                  {section === "Mailboxes" && <SyncFreshnessAlert readiness={readiness} />}
                  {section === "Employee List" ? (
                    <Box>
                      <Chip size="small" label={`${employeeListRows.length} active employees`} sx={{ mb: 2 }} />
                      <DataTable
                        rows={employeeListRows}
                        emptyTitle={emptyTitle(section)}
                        emptyDescription={emptyDescription(section)}
                        onEdit={role === "admin" ? (row) => editPerson("employee", row) : undefined}
                        onDelete={role === "admin" ? removeEmployee : undefined}
                      />
                    </Box>
                  ) : section === "Employee Performance" ? (
                    <DataTable
                      rows={visibleRows}
                      emptyTitle={emptyTitle(section)}
                      emptyDescription={departmentFilter ? `No employees are listed in ${departmentFilter} yet.` : emptyDescription(section)}
                      onSelect={openEmployee}
                      onEdit={role === "admin" ? (row) => editPerson("employee", row) : undefined}
                      onDelete={role === "admin" ? removeEmployee : undefined}
                    />
                  ) : section === "Pending Emails" && pendingView === "board" ? <MailKanban rows={rows} onSelect={openEmail} /> : <DataTable
                    rows={visibleRows}
                    dimensionLabel={section === "Reports" ? reportDimension === "customer" ? "Sender" : reportDimension[0].toUpperCase()+reportDimension.slice(1) : undefined}
                    emptyTitle={emptyTitle(section)}
                    emptyDescription={emptyDescription(section)}
                    onSelect={
                      section === "Pending Emails"
                        ? openEmail
                          : section === "Reports" && reportDimension === "employee"
                            ? (row) => { const employeeId = String(row.employee_id || ""); setAiReviewEmployeeId(employeeId); setAiReviewPage(1); setAiReviewResult(null); setAiReviewConsent(false); setAiReviewOpen(true); void generateEmployeeAIReview(1, employeeId); }
                          : section === "Reports" && reportDimension === "department"
                            ? (row) => { setReportDimension("employee"); setDepartmentFilter(row.dimension); setAiReviewEmployeeId(""); }
                          : section === "Employee Performance"
                            ? openEmployee
                          : section === "Mailboxes"
                          ? editMailbox
                          : section === "Employee Performance" &&
                              role === "admin"
                            ? (row) => editPerson("employee", row)
                            : section === "Users & Roles"
                              ? (row) => editPerson("user", row)
                              : undefined
                    }
                    onConnect={section === "Mailboxes" ? connectMailbox : undefined}
                    onEdit={section === "Mailboxes" ? editMailbox : section === "Employee Performance" ? (row) => editPerson("employee", row) : undefined}
                    onDelete={section === "Mailboxes" ? removeMailbox : section === "Employee Performance" ? removeEmployee : undefined}
                  />}
                  {section === "Pending Emails" &&
                    data?.total > data?.page_size && (
                      <Box className="pagination">
                        <Typography variant="caption">
                          {format("hint.matching", { total: data.total })}
                        </Typography>
                        <Pagination
                          page={page}
                          count={Math.ceil(data.total / data.page_size)}
                          onChange={(_, value) => setPage(value)}
                          color="primary"
                        />
                      </Box>
                    )}
                  {section === "Mailboxes" && rows.length > 0 && (
                    <Typography className="table-hint">
                      {text("hint.mailboxes")}
                    </Typography>
                  )}
                  {section === "Employee Performance" && rows.length > 0 && (
                    <Typography className="table-hint">
                      {text("hint.performance")}
                    </Typography>
                  )}
                  {section === "Users & Roles" && rows.length > 0 && (
                    <Typography className="table-hint">
                      {text("hint.users")}
                    </Typography>
                  )}
                  {section === "Pending Emails" && rows.length > 0 && (
                    <Typography className="table-hint">
                      {text("hint.pending")}
                    </Typography>
                  )}
                </>
              )}
            </Card>
          )}
        </Box>}
      </Box>
      <Dialog open={dialog} onClose={() => setDialog(false)}>
        <DialogTitle>
          {editingMailboxId
            ? text("dialog.mailbox.edit")
            : text("dialog.mailbox.add")}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1, minWidth: 380 }}>
            <TextField
              select
              label={text("dialog.mailbox.provider")}
              disabled={!!editingMailboxId}
              value={mailbox.provider}
              onChange={(e) => setMailbox({ ...mailbox, provider: e.target.value })}
            >
              <MenuItem value="microsoft">{text("dialog.mailbox.microsoft")}</MenuItem>
              <MenuItem value="gmail">{text("dialog.mailbox.gmail")}</MenuItem>
            </TextField>
            <TextField
              label={text("dialog.mailbox.address")}
              disabled={!!editingMailboxId}
              value={mailbox.address}
              onChange={(e) =>
                setMailbox({ ...mailbox, address: e.target.value })
              }
            />
            <TextField
              label={text("dialog.mailbox.display")}
              value={mailbox.display_name}
              onChange={(e) =>
                setMailbox({ ...mailbox, display_name: e.target.value })
              }
            />
            {mailbox.provider === "microsoft" && <>
              <Typography variant="subtitle2">Microsoft Azure app credentials</Typography>
              <TextField label="AZURE_CLIENT_ID" value={mailbox.azure_client_id} onChange={(e) => setMailbox({ ...mailbox, azure_client_id: e.target.value })} />
              <TextField label="AZURE_TENANT_ID" value={mailbox.azure_tenant_id} onChange={(e) => setMailbox({ ...mailbox, azure_tenant_id: e.target.value })} />
              <TextField label="AZURE_CLIENT_SECRET" type="password" autoComplete="new-password" value={mailbox.azure_client_secret} onChange={(e) => setMailbox({ ...mailbox, azure_client_secret: e.target.value })} helperText={editingMailboxId ? "Leave blank to keep the saved secret." : "Encrypted when you submit the mailbox."} />
            </>}
            <TextField
              select
              label={text("dialog.mailbox.timezone")}
              value={mailbox.timezone}
              onChange={(e) =>
                setMailbox({ ...mailbox, timezone: e.target.value })
              }
            >
              <MenuItem value="Asia/Kolkata">Asia/Kolkata</MenuItem>
              <MenuItem value="UTC">UTC</MenuItem>
            </TextField>
            {editingMailboxId && (
              <TextField
                select
                label={text("dialog.mailbox.sync_status")}
                value={mailbox.status}
                onChange={(e) =>
                  setMailbox({ ...mailbox, status: e.target.value })
                }
              >
                <MenuItem value="active">{text("status.active")}</MenuItem>
                <MenuItem value="paused">{text("dialog.mailbox.paused")}</MenuItem>
                <MenuItem value="error">{text("dialog.mailbox.error")}</MenuItem>
              </TextField>
            )}
            {mailbox.provider === "gmail" ? (
                <GmailSetupPipeline
                  setup={gmailSetup}
                  onCopy={copyText}
                  onDownload={downloadText}
                  onSaveCredentials={saveGmailCredentials}
                />
              ) : !editingMailboxId ? (
                <GraphSetupPipeline
                  setup={graphSetup}
                  mailboxAddress={mailbox.address}
                  onCopy={copyText}
                  onDownload={downloadText}
                  onTestGraph={testGraphConnection}
                  testingGraph={testingGraph}
                />
              ) : null}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(false)}>{text("dialog.cancel")}</Button>
          <Button variant="contained" onClick={saveMailbox}>
            {editingMailboxId ? text("dialog.save_changes") : text("action.add_mailbox")}
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={!!createDialog} onClose={() => setCreateDialog(null)}>
        <DialogTitle>
          {editingPersonId ? text("dialog.edit") : text("dialog.add")}{" "}
          {createDialog === "employee"
            ? text("dialog.person.employee")
            : text("dialog.person.user")}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1, minWidth: 380 }}>
            <TextField
              label={text("dialog.person.name")}
              value={person.name}
              onChange={(e) => setPerson({ ...person, name: e.target.value })}
            />
            <TextField
              label={text("dialog.person.email")}
              type="email"
              value={person.email}
              onChange={(e) => setPerson({ ...person, email: e.target.value })}
            />
            {createDialog === "employee" && (
              <TextField select label="Department" value={person.department} onChange={(e) => setPerson({ ...person, department: e.target.value })} required>
                {departments.map((department) => <MenuItem key={department} value={department}>{department}</MenuItem>)}
              </TextField>
            )}
            {createDialog === "user" && (
              <>
                <TextField
	                  label={
	                    editingPersonId
	                      ? text("dialog.person.new_password")
	                      : text("dialog.person.temp_password")
	                  }
                  type="password"
	                  helperText={
	                    editingPersonId
	                      ? text("dialog.person.keep_password")
	                      : text("dialog.person.min_password")
	                  }
                  value={person.password}
                  onChange={(e) =>
                    setPerson({ ...person, password: e.target.value })
                  }
                />
                <TextField
                  select
                  label={text("dialog.person.role")}
                  value={person.role}
                  onChange={(e) =>
                    setPerson({ ...person, role: e.target.value })
                  }
                >
                  <MenuItem value="manager">{text("dialog.person.manager")}</MenuItem>
                  <MenuItem value="admin">{text("dialog.person.admin")}</MenuItem>
                </TextField>
                {person.role === "manager" && (
                  <TextField
                    select
                    label="Allowed mailboxes"
                    value={person.mailbox_ids.map(String)}
                    SelectProps={{ multiple: true }}
                    onChange={(event) => {
                      const rawValue = event.target.value;
                      const values = Array.isArray(rawValue)
                        ? rawValue
                        : String(rawValue).split(",");
                      setPerson({ ...person, mailbox_ids: values.map(Number) });
                    }}
                    helperText="No selection means this Manager cannot view mailbox data."
                  >
                    {mailboxes.map((allowedMailbox) => (
                      <MenuItem key={allowedMailbox.id} value={String(allowedMailbox.id)}>
                        {allowedMailbox.display_name || allowedMailbox.address}
                      </MenuItem>
                    ))}
                  </TextField>
                )}
              </>
            )}
            <FormControlLabel
              control={
                <Switch
                  checked={person.active}
                  onChange={(e) =>
                    setPerson({ ...person, active: e.target.checked })
                  }
                />
              }
              label={text("dialog.person.active")}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialog(null)}>{text("dialog.cancel")}</Button>
          <Button variant="contained" onClick={createPerson}>
            {editingPersonId ? text("dialog.save_changes") : text("dialog.create")}
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={aiReviewOpen} onClose={() => { if (!aiReviewBusy) setAiReviewOpen(false); }} maxWidth="md" fullWidth>
        <DialogTitle>{aiReviewResult ? `AI coaching review · ${aiReviewResult.employee}` : aiReviewConsent ? "Enable continuous AI coaching reviews" : "AI coaching report"}</DialogTitle>
        <DialogContent dividers>
          {aiReviewResult ? (
            <Stack spacing={2}>
              <Box className="admin-work-snapshot"><Box className="admin-snapshot-title"><Typography variant="overline">ADMIN WORK SNAPSHOT</Typography><Typography variant="subtitle2">{aiReviewResult.employee} · {aiReviewResult.department}</Typography><Typography variant="caption">{aiReviewResult.period} review period · conversation evidence processed separately</Typography></Box><Box className="admin-snapshot-metrics"><Box><small>Reviewed</small><strong>{aiReviewResult.reviewed_count}</strong><span>{aiReviewResult.conversation_count ? Math.round(aiReviewResult.reviewed_count / aiReviewResult.conversation_count * 100) : 0}% complete</span></Box><Box><small>Waiting</small><strong>{aiReviewResult.pending_count}</strong><span>Needs mailbox sync or review</span></Box><Box><small>Failed</small><strong>{aiReviewResult.failed_count}</strong><span>{aiReviewResult.failed_count ? "Needs retry" : "No failed reviews"}</span></Box><Box><small>Visible mail</small><strong>{aiReviewResult.conversation_count}</strong><span>Assigned customer conversations</span></Box></Box></Box>
              <Box className="admin-review-charts"><Box className="admin-chart-card"><Typography variant="subtitle2">Review status</Typography><Box className="admin-doughnut"><Doughnut data={{ labels: ["Reviewed", "Waiting", "Failed"], datasets: [{ data: [aiReviewResult.reviewed_count, aiReviewResult.pending_count, aiReviewResult.failed_count], backgroundColor: ["#16885f", "#e4a323", "#d14343"], borderWidth: 0 }] }} options={{ responsive: true, maintainAspectRatio: false, cutout: "68%", plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } } } }} /></Box></Box><Box className="admin-chart-card admin-progress-chart"><Typography variant="subtitle2">Conversation coverage</Typography><Bar data={{ labels: ["Reviewed", "Waiting", "Failed"], datasets: [{ data: [aiReviewResult.reviewed_count, aiReviewResult.pending_count, aiReviewResult.failed_count], backgroundColor: ["#16885f", "#e4a323", "#d14343"], borderRadius: 7, barThickness: 22 }] }} options={{ indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 } }, y: { grid: { display: false } } } }} /></Box></Box>
              <Box className="handling-score-panel"><Box className="handling-score-circle" role="img" aria-label={aiReviewResult.work_score?.score == null ? `${aiReviewResult.work_score?.assessed_points || 0} of 100 points assessed` : `Coaching score ${aiReviewResult.work_score.score} out of 100`}><Doughnut data={{ labels: ["Earned", "Assessed but not earned", "Unscored"], datasets: [{ data: [aiReviewResult.work_score?.earned_points ?? 0, Math.max(0,(aiReviewResult.work_score?.assessed_points ?? 0)-(aiReviewResult.work_score?.earned_points ?? 0)), 100-(aiReviewResult.work_score?.assessed_points ?? 0)], backgroundColor: ["#16885f", "#e8eef5", "#f0c46c"], borderWidth: 0 }] }} options={{ responsive: true, maintainAspectRatio: false, cutout: "78%", plugins: { legend: { display: false } } }} /><Box className="handling-score-center"><strong>{aiReviewResult.work_score?.score ?? "—"}</strong><small>{aiReviewResult.work_score?.score == null ? `${aiReviewResult.work_score?.assessed_points || 0}/100 assessed` : "out of 100"}</small></Box></Box><Box className="handling-score-details"><Typography variant="overline">EVIDENCE-BASED COACHING SCORE</Typography><Typography variant="h6">Reply handling and answer quality</Typography><Typography variant="caption">{aiReviewResult.work_score?.sample_size || 0} customer mails · 10 reply completion + 30 professionalism + 20 detail + 10 speed + 10 clarity + 10 follow-through + 10 actionable next step.</Typography><Box className="handling-factor-list">{aiReviewResult.work_score?.factors?.map((factor: any) => <Box key={factor.label} className="handling-factor"><Box><b>{factor.label}</b><span>{factor.value == null ? "Unscored" : `${factor.value}/100`} · {factor.weight} points</span></Box><LinearProgress variant="determinate" value={factor.value ?? 0} /><small>{factor.detail}</small></Box>)}</Box></Box></Box>
              <Alert severity="info">The full /100 appears only when every factor has evidence. Missing reply text stays unscored. This coaching indicator needs admin review before any personnel decision.</Alert>
              <Typography variant="caption">Each conversation is reviewed separately after new mail or replies sync. Background checks run every 30 seconds; this view refreshes automatically.</Typography>
              {aiReviewBusy && <LinearProgress />}
              {!aiReviewResult.conversation_count && <Typography color="text.secondary">No customer conversations were assigned to this employee during this period.</Typography>}
              {aiReviewResult.reviews.map((review: any, index: number) => (
                <Card key={`${review.subject}-${index}`} variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle2">{review.subject}</Typography>
                  <Typography variant="caption" color="text.secondary">From {review.sender} · {formatMailboxDateTime(review.received_at)} · {review.mailbox}</Typography>
                  {review.analyzed_at && <Typography variant="caption" color="text.secondary">{review.status === "ready" ? "Reviewed" : "Last attempt"} {new Date(review.analyzed_at).toLocaleString()}</Typography>}
                  {review.status === "ready" ? <VisualCoachingReview review={review} /> : <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{review.status === "failed" ? review.error === "ai_provider_http_404" ? "The selected AI model is unavailable for this API key. Open AI Settings, choose an available model, and save to retry failed reviews." : ["ai_provider_http_402", "ai_provider_http_429"].includes(review.error) ? "AI provider limit reached. Open AI Settings to choose another provider or model; review will retry automatically." : "Review temporarily unavailable. Automatic retry starts within a minute." : "Queued for background review after mailbox synchronization."}</Typography>}
                </Card>
              ))}
              {aiReviewResult.total_pages > 1 && <Pagination page={aiReviewResult.page} count={aiReviewResult.total_pages} onChange={(_, page) => { setAiReviewPage(page); void generateEmployeeAIReview(page); }} color="primary" />}
              {error && <Alert severity="error">{error}</Alert>}
            </Stack>
          ) : !aiReviewConsent ? (
            <Stack spacing={2} alignItems="center" sx={{ py: 4 }}>
              {aiReviewBusy && <><CircularProgress /><Typography>Loading the saved coaching reviews…</Typography></>}
              {error && <Alert severity="error">{error}</Alert>}
            </Stack>
          ) : (
            <Stack spacing={2}>
              <Typography>After you approve, OEIS will review new or changed employee conversations throughout the day, checking for changes every 30 seconds and save the AI findings. Monthly reports will load those saved findings instead of asking the AI to reread the month’s mail.</Typography>
              {!aiSchedulerEnabled && <Alert severity="warning">The application scheduler is disabled. Enable the backend scheduler and restart the app before enabling continuous reviews.</Alert>}
              <Typography variant="body2">Conversation text is sent to the AI provider configured for reply assistance. OEIS stores the findings and processing status, but not message bodies. The provider’s own data handling follows its configured terms. Changed conversations are processed one at a time; conversations awaiting synchronization or review stay visible as waiting. Long conversations are reviewed in smaller sections and combined into saved findings.</Typography>
              <Alert severity="warning">AI observations can be incomplete or mistaken. Review cited examples and the original conversations. This report is for coaching visibility only and must not be used as a character judgment, score, or salary decision.</Alert>
              {error && <Alert severity="error">{error}</Alert>}
            </Stack>
          )}
        </DialogContent>
        <DialogActions>
          <Button disabled={aiReviewBusy} onClick={() => setAiReviewOpen(false)}>{aiReviewResult ? "Close" : text("dialog.cancel")}</Button>
          {aiReviewConsent && !aiReviewEnabled && role === "admin" && <Button variant="contained" disabled={aiReviewBusy || !aiProviderConfigured || !aiSchedulerEnabled} startIcon={<AutoAwesome />} onClick={enableDailyAIReviews}>{aiReviewBusy ? "Enabling…" : "Approve and enable continuous reviews"}</Button>}
        </DialogActions>
      </Dialog>
      <Dialog open={!!senderReport} onClose={() => setSenderReport(null)} maxWidth="lg" fullWidth>
        <DialogTitle>Sender counts · {rows.find((row) => String(row.employee_id) === aiReviewEmployeeId)?.dimension} · {reportPeriod}</DialogTitle>
        <DialogContent dividers><DataTable rows={senderReport?.rows || []} dimensionLabel="Sender" emptyTitle="No mail in this period" emptyDescription="Sender counts include received mail assigned to this employee." /></DialogContent>
        <DialogActions>
          <Button onClick={() => downloadReport("csv", "customer")}>Export CSV</Button>
          <Button onClick={() => downloadReport("xlsx", "customer")}>Export Excel</Button>
          <Button onClick={() => downloadReport("pdf", "customer")}>Export PDF</Button>
          <Button onClick={() => setSenderReport(null)}>Close</Button>
        </DialogActions>
      </Dialog>
      <Drawer
        anchor="right"
        open={!!selectedEmail}
        onClose={() => { setSelectedEmail(null); setReplyDraft(""); }}
      >
        <Box className="detail production-detail">
          <Box className="detail-head">
            <Chip
              label={selectedEmail?.sla_tier || text("detail.email")}
              color={selectedEmail?.sla_tier === "critical" ? "error" : "info"}
            />
            <IconButton
              aria-label={text("detail.close")}
              onClick={() => setSelectedEmail(null)}
            >
              <Close />
            </IconButton>
          </Box>
          {selectedEmail && (
            <>
              <Typography variant="h5">{selectedEmail.subject}</Typography>
              <Box className="preview">
                <small>{text("detail.sender")}</small>
                <b>{selectedEmail.sender}</b>
                <small>{text("detail.receiver")}</small>
                <b>{selectedEmail.receiver}</b>
                <small>{text("detail.received")}</small>
                <b>{formatMailboxDateTime(selectedEmail.received_time, selectedEmail.mailbox_timezone)}</b>
                {selectedEmail.replied_at && (
                  <>
                    <small>Replied At</small>
                    <b>{formatMailboxDateTime(selectedEmail.replied_at, selectedEmail.mailbox_timezone)}</b>
                  </>
                )}
                <small>{text("detail.classification_status")}</small>
                <b>
                  {selectedEmail.classification} · {replyStatusLabel(selectedEmail.status)}
                </b>
                <small>{text("detail.pending_hours")}</small>
                <b>{Number(selectedEmail.pending_hours).toFixed(2)}</b>
                <small>{text("detail.internet_message_id")}</small>
                <span className="technical-value">
                  {selectedEmail.internet_message_id || text("detail.unavailable")}
                </span>
                <small>{text("detail.conversation_id")}</small>
                <span className="technical-value">
                  {selectedEmail.conversation_id || text("detail.unavailable")}
                </span>
              </Box>
              {conversation?.source_id === selectedEmail.id && <Box sx={{ mt: 2, mb: 2 }}>
                {conversation.error ? <Alert severity="warning">{conversation.error}</Alert> : <Card variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle1">Conversation · {conversation.customer_message_count} customer messages · {conversation.completed_rounds} completed rounds · {conversation.pending_obligations} pending obligations</Typography>
                  {conversation.partial_grouping && <Alert severity="info" sx={{ mt: 1 }}>Partial grouping: {conversation.grouping_note}</Alert>}
                  {conversation.messages.map((message: any, index: number) => <Box key={message.id} sx={{ mt: 1.5, pt: 1, borderTop: index ? "1px solid #e5e7eb" : "none" }}>
                    <Typography variant="body2"><strong>Round {index + 1}:</strong> {message.subject} · {formatMailboxDateTime(message.received_at, selectedEmail.mailbox_timezone)}</Typography>
                    <Typography variant="caption">To: {message.to_employees.join(", ") || "No tracked employee"} · {message.status === "replied" ? `Replied by ${message.responder || "unknown"} at ${formatMailboxDateTime(message.replied_at, selectedEmail.mailbox_timezone)} · ${Number(message.reply_hours || 0).toFixed(2)} business hours` : "Awaiting reply"}</Typography>
                    {message.handover_from && <Typography variant="caption" display="block">Handover from {message.handover_from} to {message.responder}</Typography>}
                  </Box>)}
                </Card>}
              </Box>}
              {role === "admin" && (
                <Box className="email-content">
                  <Typography variant="subtitle2">{text("detail.message_content", "Message content")}</Typography>
                  {selectedEmail.content_loading ? (
                    <Box className="email-content-loading"><CircularProgress size={20} /> {text("detail.loading_content", "Loading message...")}</Box>
                  ) : selectedEmail.content_error ? (
                    <Alert severity="error">{selectedEmail.content_error}</Alert>
                  ) : (
                    <Typography component="div">{selectedEmail.content || text("detail.empty_content", "This message has no readable text content.")}</Typography>
                  )}
                </Box>
              )}
              {role === "admin" && selectedEmail.folder === "inbox" && (
                <Box className="reply-composer">
                  <Box className="reply-composer-head">
                    <Box>
                      <Typography variant="subtitle1">Reply to customer</Typography>
                      <Typography variant="body2">To: {selectedEmail.sender}</Typography>
                    </Box>
                    <Stack direction="row" spacing={1} alignItems="center">
                      {selectedEmail.status === "replied" && <Chip size="small" color="success" label="Replied" />}
                      {["ignored", "observer_copy", "duplicate_copy"].includes(selectedEmail.status) && <Chip size="small" color="default" label={replyStatusLabel(selectedEmail.status)} />}
                      {selectedEmail.status === "ignored" ? (
                        <Button size="small" onClick={() => updateEmailStatus("pending")}>Restore</Button>
                      ) : (
                        <Button size="small" color="warning" onClick={() => updateEmailStatus("ignored")}>Ignore</Button>
                      )}
                    </Stack>
                  </Box>
                  <TextField
                    fullWidth
                    multiline
                    minRows={6}
                    maxRows={14}
                    label="Your reply"
                    value={replyDraft}
                    onChange={(event) => setReplyDraft(event.target.value)}
                    disabled={replyBusy || !!assistantMode}
                    inputProps={{ maxLength: 10000 }}
                  />
                  <Box className="reply-ai-actions">
                    <Button size="small" startIcon={assistantMode === "draft" ? <CircularProgress size={16} /> : <AutoAwesome />} onClick={() => assistReply("draft")} disabled={!!assistantMode || replyBusy || !!selectedEmail.content_error || !!selectedEmail.content_loading}>
                      Draft with AI
                    </Button>
                    <Button size="small" startIcon={assistantMode === "correct" ? <CircularProgress size={16} /> : <AutoFixHigh />} onClick={() => assistReply("correct")} disabled={!replyDraft.trim() || !!assistantMode || replyBusy || !!selectedEmail.content_error || !!selectedEmail.content_loading}>
                      Fix grammar
                    </Button>
                    <Button size="small" startIcon={assistantMode === "rewrite" ? <CircularProgress size={16} /> : <AutoFixHigh />} onClick={() => assistReply("rewrite")} disabled={!replyDraft.trim() || !!assistantMode || replyBusy || !!selectedEmail.content_error || !!selectedEmail.content_loading}>
                      Rewrite
                    </Button>
                  </Box>
                  <Typography className="reply-review-note" variant="caption">Email context is sent to the configured AI service. Review every suggestion before sending.</Typography>
                  {error && <Alert severity="error">{error}</Alert>}
                  <Button variant="contained" startIcon={replyBusy ? <CircularProgress size={16} color="inherit" /> : <Send />} onClick={sendReply} disabled={!replyDraft.trim() || replyBusy || !!assistantMode}>
                    {replyBusy ? "Sending…" : "Send reply"}
                  </Button>
                </Box>
              )}
              <TextField
                select
                fullWidth
                disabled={role !== "admin"}
                label={
                  role === "admin"
                    ? text("detail.assigned_employee")
                    : text("detail.assigned_employee_admin")
                }
                value={
                  selectedEmail.assigned_employee_id
                    ? String(selectedEmail.assigned_employee_id)
                    : ""
                }
                onChange={(e) => assignEmail(e.target.value)}
              >
                <MenuItem value="">
                  <em>{text("detail.unassigned")}</em>
                </MenuItem>
                {employees.map((employee) => (
                  <MenuItem key={employee.id} value={String(employee.id)}>
                    {employee.name}
                  </MenuItem>
                ))}
              </TextField>
            </>
          )}
        </Box>
      </Drawer>
      <Snackbar
        open={!!notice}
        autoHideDuration={3500}
        onClose={() => setNotice("")}
        message={notice}
      />
      <GuidedTour
        open={tourOpen}
        steps={tourSteps}
        onClose={() => setTourOpen(false)}
        onStepChange={handleTourStep}
      />
      </Box>
    </Box>
  );
}
