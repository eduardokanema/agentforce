# AgentForce UI

React + Vite dashboard for browsing missions, mission details, and task details.

## Prerequisites

- Node 18+
- Python 3.11+
- A running backend via `mission serve` for local development

## Dev Workflow

From the repository root:

```bash
mission serve
```

In a separate shell:

```bash
cd ui
npm install
npm run dev
```

The Vite dev server proxies `/api` and `/ws` to `http://localhost:8080` by default.

## Custom Backend

Point the UI at a remote backend by overriding the API and WebSocket base URLs:

```bash
VITE_API_BASE_URL=http://remote:8080 VITE_WS_URL=ws://remote:8080/ws npm run dev
```

## Build

```bash
npm run build
```

The production output is written to `ui/dist/`.

## Component Structure

- `src/main.tsx` mounts the app and global styles.
- `src/App.tsx` defines the router for the missions, mission detail, and task detail pages.
- `src/pages/` contains the route-level screens.
- `src/components/` contains shared UI pieces:
  - `Breadcrumb`
  - `ConnectionBanner`
  - `StatusBadge`
  - `MissionProgressBar`
  - `AgentChip`
  - `StatsBar`
  - `EventLogTable`
  - `TerminalPanel`
- `src/hooks/` contains the data and live-stream hooks:
  - `useMissionList`
  - `useMission`
  - `useTaskStream`
- `src/lib/` contains the API client, WebSocket client, and shared types.

## WebSocket Message Protocol

The dashboard connects to `ws://<host>/ws` and exchanges JSON messages.

### Client to Server

| Type | Fields | Meaning |
| --- | --- | --- |
| `subscribe_all` | none | Subscribe to global mission list updates. |
| `subscribe` | `mission_id` | Subscribe to one mission’s live updates. |
| `ping` | none | Application-level keepalive. The server replies with `{"type":"pong"}`. |

### Server to Client

| Type | Fields | Meaning |
| --- | --- | --- |
| `mission_list` | `missions` | Full mission summary snapshot for the global list. |
| `mission_list_update` | `missions` | Legacy compatibility alias accepted by the UI client. |
| `mission_state` | `mission_id`, `state` | Full mission state update for one mission. |
| `stream_line` | `mission_id`, `task_id`, `line`, `seq` | Live task output line for the subscribed mission. |
| `task_stream_line` | `mission_id`, `task_id`, `line`, `seq` | Legacy compatibility alias accepted by the UI client. |
| `task_stream_done` | `mission_id`, `task_id` | Task stream finished for the subscribed mission. |
| `pong` | none | Reply to an application-level `ping` message. |

### Transport-Level Ping/Pong

The WebSocket transport also responds to RFC 6455 ping control frames with a pong control frame.
