"use client";

import { useCallback, useEffect, useRef, useState } from "react";
// useRef + useState used together to debounce/dedupe detection log appends.
import type {
  Command,
  DetectionBox,
  Entity,
  FollowState,
  Health,
  IntentMessage,
  ServerMessage,
} from "./contracts";

export type ConnectionState =
  | { kind: "disconnected" }
  | { kind: "connecting" }
  | { kind: "connected" }
  | { kind: "failed"; reason: string };

export interface DetectionLayer {
  source: string;       // "leader" (recon) | "follower" (companion)
  boxes: DetectionBox[];
  imageW: number;
  imageH: number;
  t: number;
}

export interface DetectionEvent {
  t: number;
  source: string;
  boxes: DetectionBox[];
}

export interface WorldClientState {
  connection: ConnectionState;
  entities: Entity[];
  stage: string;
  lastError: string | null;
  health: Health | null;
  detections: Record<string, DetectionLayer>;
  detectionLog: DetectionEvent[];
  followState: FollowState | null;
  /** Increments each time the server signals the buildings layer changed,
   *  so map components can re-fetch /map/buildings. */
  buildingsVersion: number;
  send: (cmd: Command) => void;
}

const RECONNECT_DELAY_MS = 1000;

/**
 * Single WS connection to the laptop brain. Mirrors mobile/Sources/WorldClient.swift:
 * one durable subscription, decode-and-publish, send intents back.
 */
export function useWorldClient(url: string): WorldClientState {
  const [connection, setConnection] = useState<ConnectionState>({ kind: "disconnected" });
  const [entities, setEntities] = useState<Entity[]>([]);
  const [stage, setStage] = useState<string>("—");
  const [lastError, setLastError] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [detections, setDetections] = useState<Record<string, DetectionLayer>>({});
  const [detectionLog, setDetectionLog] = useState<DetectionEvent[]>([]);
  const [followState, setFollowState] = useState<FollowState | null>(null);
  const [buildingsVersion, setBuildingsVersion] = useState(0);
  const lastLoggedT = useRef<Record<string, number>>({});

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);

  const open = useCallback(() => {
    if (stoppedRef.current) return;
    setConnection({ kind: "connecting" });
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      setConnection({ kind: "failed", reason: String(err) });
      scheduleReconnect();
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => setConnection({ kind: "connected" });
    ws.onclose = () => {
      setConnection({ kind: "disconnected" });
      scheduleReconnect();
    };
    ws.onerror = () => {
      // onclose follows; surface as a fault transiently.
      setConnection({ kind: "failed", reason: "socket error" });
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as ServerMessage;
        apply(msg);
      } catch {
        // Ignore malformed frames; never guess.
      }
    };
  }, [url]);

  const scheduleReconnect = useCallback(() => {
    if (stoppedRef.current) return;
    if (reconnectRef.current != null) return;
    reconnectRef.current = window.setTimeout(() => {
      reconnectRef.current = null;
      open();
    }, RECONNECT_DELAY_MS);
  }, [open]);

  const apply = useCallback((msg: ServerMessage) => {
    switch (msg.type) {
      case "world_snapshot":
        setEntities(msg.entities);
        break;
      case "mission_state":
        setStage(msg.stage);
        setLastError(msg.last_error);
        break;
      case "health":
        setHealth(msg);
        break;
      case "follow_state":
        setFollowState(msg);
        break;
      case "buildings_updated":
        setBuildingsVersion((v) => v + 1);
        break;
      case "detections":
        setDetections((prev) => ({
          ...prev,
          [msg.source]: {
            source: msg.source,
            boxes: msg.boxes,
            imageW: msg.image_w,
            imageH: msg.image_h,
            t: msg.t,
          },
        }));
        // Append to log only when this is a new perception frame (the WS
        // broadcaster re-sends the same boxes every cycle until perception
        // updates) and at least one box was detected. Keep last 80.
        if (
          msg.boxes.length > 0 &&
          msg.t !== lastLoggedT.current[msg.source]
        ) {
          lastLoggedT.current[msg.source] = msg.t;
          setDetectionLog((prev) =>
            [{ t: msg.t, source: msg.source, boxes: msg.boxes }, ...prev].slice(0, 80),
          );
        }
        break;
    }
  }, []);

  const send = useCallback((command: Command) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const intent: IntentMessage = {
      type: "intent",
      command,
      source: "dashboard",
      t: Date.now() / 1000,
    };
    ws.send(JSON.stringify(intent));
  }, []);

  useEffect(() => {
    stoppedRef.current = false;
    open();
    return () => {
      stoppedRef.current = true;
      if (reconnectRef.current != null) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [open]);

  return { connection, entities, stage, lastError, health, detections, detectionLog, followState, buildingsVersion, send };
}
