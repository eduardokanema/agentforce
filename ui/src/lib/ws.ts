import type { MissionState, MissionSummary } from './types';

export interface MissionListEvent {
  type: 'mission_list';
  missions: MissionSummary[];
}

export interface MissionListUpdateEvent {
  type: 'mission_list_update';
  missions: MissionSummary[];
}

export interface MissionStateEvent {
  type: 'mission_state';
  mission_id: string;
  state: MissionState;
}

export interface StreamLineEvent {
  type: 'stream_line';
  mission_id: string;
  task_id: string;
  line: string;
  seq: number;
  done?: boolean;
}

export interface TaskStreamLineEvent {
  type: 'task_stream_line';
  mission_id: string;
  task_id: string;
  line: string;
  seq: number;
  done?: boolean;
}

export interface TaskStreamDoneEvent {
  type: 'task_stream_done';
  mission_id: string;
  task_id: string;
}

type WsInboundEvent =
  | MissionListEvent
  | MissionListUpdateEvent
  | MissionStateEvent
  | StreamLineEvent
  | TaskStreamLineEvent
  | TaskStreamDoneEvent;

type WsEventType = WsInboundEvent['type'];
type WsEventHandler<K extends WsEventType> = (event: Extract<WsInboundEvent, { type: K }>) => void;
type WsAnyHandler = (event: WsInboundEvent) => void;
type ConnectionState = 'connecting' | 'open' | 'closed';
type ConnectionStateHandler = (state: ConnectionState) => void;
type OutboundMessage =
  | { type: 'subscribe_all' }
  | { type: 'subscribe'; mission_id: string };

const DEFAULT_WS_URL = 'ws://localhost:8080/ws';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isMissionSummary(value: unknown): value is MissionSummary {
  return isRecord(value)
    && isString(value.mission_id)
    && isString(value.name)
    && isString(value.status)
    && isNumber(value.done_tasks)
    && isNumber(value.total_tasks)
    && isNumber(value.pct)
    && isString(value.duration)
    && isString(value.worker_agent)
    && isString(value.worker_model)
    && isString(value.started_at);
}

function isMissionState(value: unknown): value is MissionState {
  return isRecord(value)
    && isString(value.mission_id)
    && isRecord(value.spec)
    && isRecord(value.task_states)
    && Array.isArray(value.event_log)
    && isString(value.started_at)
    && isNumber(value.total_retries)
    && isNumber(value.total_human_interventions)
    && isNumber(value.total_tokens_used)
    && isNumber(value.estimated_cost_usd)
    && isRecord(value.caps_hit)
    && isString(value.working_dir)
    && isString(value.worker_agent)
    && isString(value.worker_model);
}

function isInboundEvent(value: unknown): value is WsInboundEvent {
  if (!isRecord(value) || !isString(value.type)) {
    return false;
  }

  switch (value.type) {
    case 'mission_list':
    case 'mission_list_update':
      return Array.isArray(value.missions) && value.missions.every(isMissionSummary);
    case 'mission_state':
      return isString(value.mission_id) && isMissionState(value.state);
    case 'stream_line':
    case 'task_stream_line':
      return isString(value.mission_id)
        && isString(value.task_id)
        && isString(value.line)
        && isNumber(value.seq);
    case 'task_stream_done':
      return isString(value.mission_id) && isString(value.task_id);
    default:
      return false;
  }
}

export class AgentForceWs {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelayMs = 1000;
  private readonly handlers = new Map<WsEventType, Set<WsAnyHandler>>();
  private readonly connectionHandlers = new Set<ConnectionStateHandler>();
  private readonly pendingSubscriptions = new Set<string>();
  private _connectionState: ConnectionState = 'closed';

  constructor(private readonly url: string = import.meta.env.VITE_WS_URL ?? DEFAULT_WS_URL) {
    this.connect();
  }

  get connectionState(): ConnectionState {
    return this._connectionState;
  }

  on<K extends WsEventType>(type: K, handler: WsEventHandler<K>): void {
    const handlers = this.handlers.get(type) ?? new Set<WsAnyHandler>();
    handlers.add(handler as unknown as WsAnyHandler);
    this.handlers.set(type, handlers);
  }

  off<K extends WsEventType>(type: K, handler: WsEventHandler<K>): void {
    const handlers = this.handlers.get(type);
    if (!handlers) {
      return;
    }

    handlers.delete(handler as unknown as WsAnyHandler);
    if (handlers.size === 0) {
      this.handlers.delete(type);
    }
  }

  onConnectionState(handler: ConnectionStateHandler): void {
    this.connectionHandlers.add(handler);
    handler(this._connectionState);
  }

  offConnectionState(handler: ConnectionStateHandler): void {
    this.connectionHandlers.delete(handler);
  }

  subscribe(missionId: string): void {
    this.pendingSubscriptions.add(missionId);
    this.send({ type: 'subscribe', mission_id: missionId });
  }

  connect(): void {
    if (typeof WebSocket === 'undefined') {
      return;
    }

    if (this.socket && (this.socket.readyState === WebSocket.CONNECTING || this.socket.readyState === WebSocket.OPEN)) {
      return;
    }

    this.clearReconnectTimer();
    this.setConnectionState('connecting');
    const socket = new WebSocket(this.url);
    this.socket = socket;

    socket.addEventListener('open', () => {
      if (this.socket !== socket) {
        return;
      }

      this.reconnectDelayMs = 1000;
      this.setConnectionState('open');
      this.sendRaw({ type: 'subscribe_all' });
      for (const missionId of this.pendingSubscriptions) {
        this.sendRaw({ type: 'subscribe', mission_id: missionId });
      }
    });

    socket.addEventListener('message', (event) => {
      this.handleMessage(event.data);
    });

    socket.addEventListener('close', () => {
      if (this.socket !== socket) {
        return;
      }

      this.socket = null;
      this.setConnectionState('closed');
      this.scheduleReconnect();
    });

    socket.addEventListener('error', () => {
      // The close handler will handle reconnect scheduling.
    });
  }

  private setConnectionState(state: ConnectionState): void {
    if (this._connectionState === state) {
      return;
    }

    this._connectionState = state;
    for (const handler of this.connectionHandlers) {
      handler(state);
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) {
      return;
    }

    const delay = this.reconnectDelayMs;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
    this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, 30_000);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private send(message: OutboundMessage): void {
    this.sendRaw(message);
  }

  private sendRaw(message: OutboundMessage): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return;
    }

    this.socket.send(JSON.stringify(message));
  }

  private handleMessage(data: unknown): void {
    if (!isString(data)) {
      return;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(data) as unknown;
    } catch {
      return;
    }

    if (!isInboundEvent(parsed)) {
      return;
    }

    this.dispatch(parsed);
  }

  private dispatch(event: WsInboundEvent): void {
    const handlers = this.handlers.get(event.type);
    if (!handlers) {
      return;
    }

    for (const handler of handlers) {
      handler(event);
    }
  }
}

export const wsClient = new AgentForceWs();
