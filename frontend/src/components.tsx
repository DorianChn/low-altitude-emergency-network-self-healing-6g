import { useId, useLayoutEffect, useRef, type CSSProperties, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import gsap from "gsap";
import { useReplay } from "./useReplay";
import { useCurrentPageData } from "./useCurrentPageData";
import { eventLabel, formatTime, strategyLabel } from "./presentation";
import {
  STRATEGIES,
  type ReplayEvent,
  type StateSnapshot,
  type StrategyId,
} from "./types";

const NAV_ITEMS = [
  { to: "/", label: "总览", end: true },
  { to: "/command", label: "数字孪生" },
  { to: "/decision", label: "自愈决策" },
  { to: "/lab", label: "实验室" },
  { to: "/research", label: "研究证据" },
  { to: "/demo", label: "现场演示" },
];

export function AppHeader() {
  const { health, replay, error } = useReplay();
  const { pathname } = useLocation();
  const { current } = useCurrentPageData();
  const currentOwner = pathname === "/demo" ? "phase6-demo" : pathname === "/research" ? "research" : null;
  const pageData = currentOwner && current?.ownerId === currentOwner ? current : null;
  if (currentOwner) {
    const loading = !pageData || pageData.status === "loading";
    const pageError = pageData?.status === "error";
    const label = pathname === "/demo" ? "当前演示回放" : "当前研究数据";
    const source = pageData?.sourceLabel ?? (pathname === "/demo" ? "正在读取场景与逐帧记录" : "正在读取阶段汇总");
    const seedLabel = pageData?.seed === null || pageData?.seed === undefined
      ? pageData?.mode === "multi-seed" ? "多种子汇总" : null
      : `单条轨迹 seed ${pageData.seed}`;
    return (
      <header className="topbar">
        <Link className="brand" to="/" aria-label="6G RESCUE 项目首页">
          <span className="brand-mark" aria-hidden="true">6</span>
          <span className="brand-word">6G / RESCUE</span>
          <span className="brand-system">低空应急网络智能自愈</span>
        </Link>
        <nav className="main-nav" aria-label="主导航">
          {NAV_ITEMS.map((item) => <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>{item.label}</NavLink>)}
        </nav>
        <div className="topbar-status" data-testid="current-page-context" aria-live="polite">
          <span className={`status-led ${pageError ? "is-error" : ""}`} />
          <span>{pageError ? `${label}不可用` : loading ? source : label}</span>
          {!loading && <span className="topbar-seed">{pageData?.scenarioLabel ?? pageData?.sourceId}</span>}
          {seedLabel && <span className="topbar-context-kind">{seedLabel}</span>}
          {pageData?.status === "error" && <span className="topbar-context-error">{pageData.error}</span>}
        </div>
      </header>
    );
  }
  return (
    <header className="topbar">
      <Link className="brand" to="/" aria-label="6G RESCUE 项目首页">
        <span className="brand-mark" aria-hidden="true">6</span>
        <span className="brand-word">6G / RESCUE</span>
        <span className="brand-system">低空应急网络智能自愈</span>
      </Link>
      <nav className="main-nav" aria-label="主导航">
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}>
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className="topbar-status">
        <span className={`status-led ${error ? "is-error" : ""}`} />
        <span>{error ? "历史回放数据不可用" : health?.live_stream === false ? "历史预计算回放" : "正在读取历史回放"}</span>
        {replay && <span className="topbar-seed">单条轨迹 seed {replay.seed}</span>}
      </div>
    </header>
  );
}

export function PageTransition({ children, className = "" }: { children: ReactNode; className?: string }) {
  const root = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const node = root.current;
    if (!node) return;
    let observer: IntersectionObserver | null = null;
    const context = gsap.context(() => {
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      // Background tabs throttle requestAnimationFrame; don't leave the page frozen mid-reveal.
      if (reduced || document.visibilityState === "hidden") return;

      gsap.fromTo(node, { autoAlpha: 0, y: 9 }, {
        autoAlpha: 1,
        y: 0,
        duration: 0.42,
        ease: "power3.out",
        clearProps: "transform",
      });

      const entering = Array.from(node.querySelectorAll<HTMLElement>("[data-enter]"));
      if (entering.length) {
        gsap.fromTo(entering, { autoAlpha: 0, y: 20 }, {
          autoAlpha: 1,
          y: 0,
          duration: 0.72,
          ease: "power3.out",
          stagger: 0.065,
          delay: 0.08,
          clearProps: "all",
        });
      }

      const pulsing = node.querySelectorAll("[data-gsap-pulse]");
      if (pulsing.length) {
        gsap.to(pulsing, {
          scale: 1.035,
          opacity: 0.82,
          duration: 8,
          ease: "sine.inOut",
          repeat: -1,
          yoyo: true,
          stagger: 0.7,
        });
      }

      const revealNodes = Array.from(node.querySelectorAll<HTMLElement>("[data-reveal]"));
      if ("IntersectionObserver" in window && revealNodes.length) {
        const seen = new WeakSet<Element>();
        const revealObserver = new IntersectionObserver((entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting || seen.has(entry.target)) return;
            seen.add(entry.target);
            gsap.fromTo(entry.target, { autoAlpha: 0, y: 22 }, {
              autoAlpha: 1,
              y: 0,
              duration: 0.62,
              ease: "power3.out",
              clearProps: "all",
            });
            revealObserver.unobserve(entry.target);
          });
        }, { threshold: 0.12, rootMargin: "0px 0px -5% 0px" });
        observer = revealObserver;
        revealNodes.forEach((element) => revealObserver.observe(element));
      }
    }, node);
    return () => {
      observer?.disconnect();
      context.revert();
    };
  }, [className]);

  return (
    <main ref={root} className={className}>
      {children}
    </main>
  );
}

export function OfflineNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`offline-notice ${compact ? "compact" : ""}`} role="note">
      <span className="offline-mark">SIM</span>
      <span>离线仿真数据 · 非真实 6G 网络测试</span>
    </div>
  );
}

export function DataState({ title = "仿真数据暂不可用" }: { title?: string }) {
  const { loading, error } = useReplay();
  return (
    <div className="data-state" role={error ? "alert" : "status"}>
      <span className="data-state-symbol" aria-hidden="true">{loading ? "···" : "!"}</span>
      <h2>{loading ? "正在读取仿真回放" : title}</h2>
      <p>{loading ? "正在从 FastAPI 读取真实实验 JSON 和种子轨迹。" : error ?? "尚无可用数据。"}</p>
      {!loading && <p className="data-state-help">请确认 Python API 已启动，且 `results/phase2_20_seed_results.json` 与种子回放文件存在。</p>}
    </div>
  );
}

export function StrategyPicker({ compact = false }: { compact?: boolean }) {
  const { selectedStrategy, setSelectedStrategy } = useReplay();
  return (
    <label className={`strategy-picker ${compact ? "compact" : ""}`}>
      <span>策略</span>
      <select value={selectedStrategy} onChange={(event) => setSelectedStrategy(event.target.value as StrategyId)}>
        {STRATEGIES.map((strategy) => <option key={strategy} value={strategy}>{strategyLabel(strategy)}</option>)}
      </select>
    </label>
  );
}

export function ReplayControls({ compact = false }: { compact?: boolean }) {
  const {
    replay,
    selectedTime,
    setSelectedTime,
    isPlaying,
    togglePlayback,
    playbackRate,
    setPlaybackRate,
    jumpToEvent,
    timelineEvents,
  } = useReplay();
  if (!replay) return null;
  const progress = replay.duration_s ? selectedTime / replay.duration_s : 0;

  return (
    <section className={`replay-controls ${compact ? "compact" : ""}`} aria-label="仿真回放控制">
      <div className="replay-head">
        <div className="replay-readout">
          <span className="replay-time">{formatTime(selectedTime)}</span>
          <span className="replay-duration">/ {formatTime(replay.duration_s)}</span>
        </div>
        <div className="replay-mode">SEED {replay.seed} <i /> {timelineEvents.length} 条事件</div>
      </div>
      <div className="replay-range-wrap">
        <input
          className="replay-range"
          type="range"
          min={0}
          max={replay.duration_s}
          step={replay.time_step_s}
          value={selectedTime}
          onChange={(event) => setSelectedTime(Number(event.target.value))}
          aria-label={`回放时间 ${formatTime(selectedTime)}，共 ${formatTime(replay.duration_s)}`}
          style={{ "--range-progress": `${progress * 100}%` } as CSSProperties}
        />
        <div className="replay-ticks" aria-hidden="true">
          {timelineEvents.filter((event) => isKeyEvent(event)).map((event, index) => (
            <span key={`${event.event_type}-${event.time_s}-${index}`} style={{ left: `${event.time_s / replay.duration_s * 100}%` }} />
          ))}
        </div>
      </div>
      <div className="replay-actions">
        <div className="replay-buttons">
          <button className="icon-button subtle" type="button" onClick={() => jumpToEvent(-1)} aria-label="跳到上一个事件" title="上一个事件">
            <Icon name="back" />
          </button>
          <button className="play-button" type="button" onClick={togglePlayback} aria-label={isPlaying ? "暂停回放" : "继续回放"}>
            <Icon name={isPlaying ? "pause" : "play"} />
            <span>{isPlaying ? "暂停" : "继续"}</span>
          </button>
          <button className="icon-button subtle" type="button" onClick={() => jumpToEvent(1)} aria-label="跳到下一个事件" title="下一个事件">
            <Icon name="next" />
          </button>
        </div>
        <label className="rate-picker">
          <span>速度</span>
          <select value={playbackRate} onChange={(event) => setPlaybackRate(Number(event.target.value))} aria-label="回放速度">
            <option value={0.5}>0.5×</option>
            <option value={1}>1×</option>
            <option value={2}>2×</option>
            <option value={4}>4×</option>
          </select>
        </label>
        <span className="key-hint">SPACE 播放 <b>←</b> <b>→</b> 单步</span>
      </div>
    </section>
  );
}

export function CityTwinScene({
  frame,
  className = "",
  showUsers = true,
  labels = true,
  replaySeed,
  worldWidthKm,
  worldHeightKm,
}: {
  frame: StateSnapshot;
  className?: string;
  showUsers?: boolean;
  labels?: boolean;
  replaySeed?: number;
  worldWidthKm?: number;
  worldHeightKm?: number;
}) {
  const { replay } = useReplay();
  const sceneId = useId().replaceAll(":", "");
  const worldWidth = worldWidthKm ?? replay?.configuration.base.city_width_km ?? 10;
  const worldHeight = worldHeightKm ?? replay?.configuration.base.city_height_km ?? 10;
  const seed = replaySeed ?? replay?.seed ?? "未知";
  const scale = 560 / Math.max(worldWidth, worldHeight);
  const left = (1000 - worldWidth * scale) / 2;
  const top = 72;
  const toPoint = (x: number, y: number) => ({
    x: left + x * scale,
    y: top + (worldHeight - y) * scale,
  });
  const dronePoint = toPoint(frame.drone.x_km, frame.drone.y_km);
  const stationPoints = new Map(frame.stations.map((station) => [station.id, toPoint(station.x_km, station.y_km)]));
  const userPoints = new Map(frame.users.map((user) => [user.id, toPoint(user.x_km, user.y_km)]));
  const radius = (km: number) => km * scale;

  return (
    <div className={`city-scene ${className}`}>
      <div className="scene-meta scene-coordinate">仿真区域 <span>{worldWidth.toFixed(0)} × {worldHeight.toFixed(0)} km</span></div>
      <div className="scene-meta scene-time">T+{formatTime(frame.time_s)}</div>
        <svg data-ui="simulation-city-twin" viewBox="0 0 1000 720" role="img" aria-label={`种子 ${seed} 的仿真网络状态，时间 ${formatTime(frame.time_s)}`}>
        <defs>
          <radialGradient id={`scene-halo-${sceneId}`} cx="53%" cy="54%" r="54%">
            <stop offset="0" stopColor="#b74426" stopOpacity=".18" />
            <stop offset=".56" stopColor="#7b1e27" stopOpacity=".07" />
            <stop offset="1" stopColor="#140e10" stopOpacity="0" />
          </radialGradient>
          <pattern id={`scene-grid-${sceneId}`} width={scale * 2} height={scale * 2} patternUnits="userSpaceOnUse">
            <path d={`M ${scale * 2} 0 L 0 0 0 ${scale * 2}`} fill="none" stroke="#ecd4c7" strokeOpacity=".085" strokeWidth="1" />
            <path d={`M ${scale} 0 V ${scale * 2} M 0 ${scale} H ${scale * 2}`} fill="none" stroke="#ecd4c7" strokeOpacity=".035" strokeWidth="1" />
          </pattern>
          <filter id={`node-glow-${sceneId}`} x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <rect width="1000" height="720" fill={`url(#scene-halo-${sceneId})`} />
        <rect x={left} y={top} width={worldWidth * scale} height={worldHeight * scale} fill={`url(#scene-grid-${sceneId})`} opacity=".9" />
        <g className="city-context" aria-hidden="true">
          <path className="city-roads" d={`M ${left + 92} ${top + 44} L ${left + 92} ${top + worldHeight * scale - 28} M ${left + 245} ${top + 88} L ${left + 245} ${top + worldHeight * scale - 42} M ${left + 418} ${top + 24} L ${left + 418} ${top + worldHeight * scale - 30} M ${left + 505} ${top + 56} L ${left + 505} ${top + worldHeight * scale - 38}`} />
          <path className="city-roads" d={`M ${left + 28} ${top + 155} L ${left + worldWidth * scale - 28} ${top + 155} M ${left + 18} ${top + 330} L ${left + worldWidth * scale - 18} ${top + 330} M ${left + 80} ${top + 472} L ${left + worldWidth * scale - 80} ${top + 472} M ${left + 42} ${top + 98} L ${left + worldWidth * scale - 44} ${top + 98}`} />
          <path className="city-blocks" d={`M ${left + 188} ${top + 78} l 72 0 0 48 -72 0 z M ${left + 276} ${top + 182} l 96 0 0 68 -96 0 z M ${left + 44} ${top + 366} l 92 0 0 66 -92 0 z M ${left + 332} ${top + 374} l 112 0 0 84 -112 0 z M ${left + 441} ${top + 105} l 78 0 0 35 -78 0 z M ${left + 146} ${top + 255} l 82 0 0 45 -82 0 z M ${left + 380} ${top + 276} l 66 0 0 50 -66 0 z M ${left + 213} ${top + 433} l 54 0 0 29 -54 0 z`} />
        </g>
        <g className="coordinate-labels" aria-hidden="true">
          {[0, 2, 4, 6, 8, 10].map((mark) => {
            const x = left + mark * scale;
            const y = top + (worldHeight - mark) * scale;
            return <g key={mark}><text x={x} y={top + worldHeight * scale + 25}>{mark}</text><text x={left - 25} y={y + 4}>{mark}</text></g>;
          })}
          <text x={left + 2} y={top - 14}>X / KM</text>
          <text x={left - 52} y={top + 4}>Y</text>
        </g>
        {frame.stations.map((station) => {
          const point = stationPoints.get(station.id)!;
          return (
            <g key={`coverage-${station.id}`} className={station.healthy ? "coverage-ring" : "coverage-ring failed"}>
              <circle cx={point.x} cy={point.y} r={radius(station.coverage_radius_km)} />
            </g>
          );
        })}
        <g className="network-links">
          {frame.links.map((link, index) => {
            const from = link.source_id === frame.drone.id ? dronePoint : stationPoints.get(link.source_id);
            const to = link.target_id === frame.drone.id ? dronePoint : userPoints.get(link.target_id);
            if (!from || !to) return null;
            return <line key={`${link.user_id}-${link.kind}-${index}`} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className={`link-line ${link.kind}`} />;
          })}
        </g>
        {showUsers && <g className="user-nodes">
          {frame.users.map((user) => {
            const point = userPoints.get(user.id)!;
            return (
              <g key={user.id} className={`user-node ${user.group} ${user.connected ? "connected" : "disconnected"}`}>
                {user.group === "rescue" && <circle className="user-ring" cx={point.x} cy={point.y} r={7.5} />}
                <circle cx={point.x} cy={point.y} r={user.group === "rescue" ? 4.5 : 2.7} />
                <title>{`${user.id} · ${user.group === "rescue" ? "救援用户" : "普通用户"} · ${user.connected ? "已连接" : "未连接"}${user.latency_ms === null ? "" : ` · ${user.latency_ms.toFixed(1)} ms`}`}</title>
              </g>
            );
          })}
        </g>}
        {frame.stations.map((station) => {
          const point = stationPoints.get(station.id)!;
          return (
            <g key={station.id} className={`station-node ${station.healthy ? "healthy" : "failed"}`} transform={`translate(${point.x} ${point.y})`}>
              <circle className="station-halo" r="17" />
              <path d="M -9 -8 L 9 -8 L 9 8 L -9 8 Z M 0 -4 L 0 4 M -5 0 L 5 0" />
              {labels && <text x="15" y="-12">{station.id.replace("bs-", "BS / ").toUpperCase()}</text>}
              <title>{`${station.id} · ${station.healthy ? "正常" : "故障"} · ${station.capacity_mbps} Mbps`}</title>
            </g>
          );
        })}
        <g className={`drone-node ${frame.drone.active ? "active" : "idle"}`} transform={`translate(${dronePoint.x} ${dronePoint.y})`} filter={frame.drone.active ? `url(#node-glow-${sceneId})` : undefined}>
          <circle className="drone-radius" r={radius(frame.drone.access_radius_km)} />
          <path className="drone-arms" d="M -15 -11 L 15 11 M -15 11 L 15 -11 M -15 -11 h -6 v 6 M 15 -11 h 6 v 6 M -15 11 h -6 v -6 M 15 11 h 6 v -6" />
          <circle className="drone-core" r="5" />
          {labels && <text x="18" y="27">UAV RELAY</text>}
          <title>{`${frame.drone.id} · ${frame.drone.active ? "中继已启用" : "待命"} · 电量 ${frame.drone.battery_wh.toFixed(1)} Wh · 回传${frame.drone.backhaul_available ? "可用" : "中断"}`}</title>
        </g>
      </svg>
      <div className="scene-legend">
        <span><i className="legend-dot station-ok" />地面基站</span>
        <span><i className="legend-dot station-down" />故障节点</span>
        <span><i className="legend-dot rescue" />救援终端</span>
        <span><i className="legend-dot user" />普通用户</span>
        <span className="scene-legend-note">地图为抽象城市平面；节点、链路和位置来自仿真帧</span>
      </div>
    </div>
  );
}

export function EventTimeline({ maxItems = 16 }: { maxItems?: number }) {
  const { timelineEvents, selectedTime, setSelectedTime } = useReplay();
  const nearbyIndex = timelineEvents.findIndex((event) => event.time_s >= selectedTime);
  const windowStart = Math.max(0, Math.min(
    nearbyIndex < 0 ? timelineEvents.length - maxItems : nearbyIndex - Math.floor(maxItems / 3),
    timelineEvents.length - maxItems,
  ));
  const visible = timelineEvents.slice(windowStart, windowStart + maxItems);
  return (
    <div className="event-timeline">
      {visible.map((event, index) => (
        <button
          type="button"
          key={`${event.event_type}-${event.time_s}-${index}`}
          className={`event-row ${event.time_s === selectedTime ? "selected" : ""}`}
          onClick={() => setSelectedTime(event.time_s)}
          title={`跳转到 ${formatTime(event.time_s)}`}
        >
          <span className={`event-dot ${eventTone(event.event_type)}`} />
          <span className="event-time">{formatTime(event.time_s)}</span>
          <span className="event-copy">
            <b>{eventLabel(event)}</b>
            <small>{eventTarget(event)}</small>
          </span>
          <Icon name="chevron" />
        </button>
      ))}
      {timelineEvents.length > maxItems && <div className="event-more">显示 {windowStart + 1}–{Math.min(windowStart + maxItems, timelineEvents.length)} / {timelineEvents.length} 条 · 可用时间轴浏览</div>}
      {timelineEvents.length === 0 && <div className="empty-inline">该策略没有记录事件。</div>}
    </div>
  );
}

export function StatValue({ value, unit = "", digits = 1 }: { value: number | null | undefined; unit?: string; digits?: number }) {
  if (value === null || value === undefined || !Number.isFinite(value)) return <>未记录</>;
  const formatted = Number.isInteger(value) ? value.toLocaleString("zh-CN") : value.toLocaleString("zh-CN", { maximumFractionDigits: digits, minimumFractionDigits: digits });
  return <>{formatted}{unit && <small className="unit"> {unit}</small>}</>;
}

export function Icon({ name }: { name: "back" | "next" | "play" | "pause" | "chevron" | "arrow" | "pulse" | "layers" | "route" | "time" | "close" }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths: Record<typeof name, React.ReactNode> = {
    back: <path d="M14.5 5 7.5 12l7 7M8 12h9" {...common} />,
    next: <path d="m9.5 5 7 7-7 7M16 12H7" {...common} />,
    play: <path d="m8 5 11 7-11 7V5Z" fill="currentColor" />,
    pause: <path d="M8 5v14M16 5v14" {...common} strokeWidth={2.6} />,
    chevron: <path d="m9 5 7 7-7 7" {...common} />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" {...common} />,
    pulse: <path d="M3 12h4l2.2-6 4.3 12 2.2-6H21" {...common} />,
    layers: <path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5" {...common} />,
    route: <><circle cx="6" cy="18" r="2" {...common} /><circle cx="18" cy="6" r="2" {...common} /><path d="M8 18h3a3 3 0 0 0 3-3v-3a3 3 0 0 1 3-3h1" {...common} /></>,
    time: <><circle cx="12" cy="12" r="9" {...common} /><path d="M12 7v5l3 2" {...common} /></>,
    close: <path d="m6 6 12 12M18 6 6 18" {...common} />,
  };
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function eventTarget(event: ReplayEvent): string {
  if (typeof event.target_id === "string") return event.target_id;
  if (event.event_type === "traffic_change" && typeof event.value === "number") return `业务倍率 ${event.value.toFixed(2)}×`;
  if (event.event_type === "optimizer_decision") {
    const destination = Array.isArray(event.destination_km) ? event.destination_km.map((value) => Number(value).toFixed(1)).join(", ") : null;
    return destination ? `部署目标 ${destination} km` : String(event.reason ?? "策略决策");
  }
  if (event.event_type === "drone_state_update") return `电量 ${Number(event.battery_remaining_wh ?? 0).toFixed(1)} Wh`;
  return String(event.source ?? "仿真事件");
}

function eventTone(type: string): string {
  if (type.includes("failure")) return "red";
  if (type.includes("recovery")) return "mint";
  if (type.includes("optimizer")) return "orange";
  return "neutral";
}

function isKeyEvent(event: ReplayEvent): boolean {
  return event.source === "configured_event_schedule" || event.event_type === "optimizer_decision";
}
