import Image from "next/image";

const failures = [
  {
    title: "Operators cannot be everywhere at once.",
    body: "Harbors, perimeters, installations, and disaster zones keep changing while teams are already stretched thin.",
  },
  {
    title: "Observation consumes the mission.",
    body: "Keeping a person, vessel, or area in frame takes attention away from command decisions and response coordination.",
  },
  {
    title: "Awareness breaks at the handoff.",
    body: "A target is located, then lost while humans shift from searching to tracking to acting.",
  },
];

const capabilities = [
  "Detect",
  "Designate",
  "Deploy",
  "Track",
  "Maintain awareness",
];

const telemetry = [
  ["LINK", "ONLINE"],
  ["MISSION", "TRACK"],
  ["ASSETS", "02"],
  ["CONTACTS", "17"],
];

const domains = [
  {
    label: "Sea",
    mission: "Maritime vessel monitoring",
    value: "Harbor security, coastal monitoring, vessel observation, and search and rescue coordination.",
  },
  {
    label: "Land",
    mission: "Perimeter security and force protection",
    value: "Route observation, missing person search, disaster response, and small unit overwatch.",
  },
  {
    label: "Air",
    mission: "Installation and infrastructure awareness",
    value: "Airfield security, wildfire assessment, utility inspection, and large-area monitoring.",
  },
];

const markets = [
  "Defense ISR",
  "Public safety",
  "Port security",
  "Emergency response",
  "Infrastructure inspection",
  "Environmental monitoring",
];

const trackNodes = [
  { label: "Leader", x: "18%", y: "72%", tone: "dark" },
  { label: "Vessel", x: "64%", y: "34%", tone: "accent" },
  { label: "Follower", x: "76%", y: "58%", tone: "ok" },
  { label: "Operator", x: "35%", y: "48%", tone: "muted" },
];

export default function LandingPage() {
  return (
    <main className="min-h-screen overflow-x-hidden bg-bg text-text">
      <header className="fixed left-0 right-0 top-0 z-30 border-b border-border bg-bg/88 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-5 py-4 md:px-8">
          <a href="#top" className="flex items-center gap-3" aria-label="SkyGuardian home">
            <Image
              src="/skyguardian-lockup.png"
              alt="SkyGuardian"
              width={260}
              height={50}
              priority
              className="h-8 w-auto md:h-9"
            />
          </a>
          <nav className="hidden items-center gap-8 font-mono text-[10px] uppercase tracking-[0.32em] text-text-muted lg:flex">
            <a href="#problem" className="transition-colors hover:text-text">
              Problem
            </a>
            <a href="#capability" className="transition-colors hover:text-text">
              Capability
            </a>
            <a href="#missions" className="transition-colors hover:text-text">
              Missions
            </a>
            <a href="#roadmap" className="transition-colors hover:text-text">
              Roadmap
            </a>
          </nav>
          <div className="flex items-center gap-3">
            <a
              href="/operator"
              className="hidden border border-border-strong bg-surface px-4 py-2 font-mono text-[10px] uppercase tracking-[0.26em] text-text transition-colors hover:border-text sm:inline-flex"
            >
              Operator
            </a>
            <a
              href="#demo"
              className="hidden border border-text bg-text px-4 py-2 font-mono text-[10px] uppercase tracking-[0.26em] text-bg transition-colors hover:bg-cta sm:inline-flex"
            >
              Request demo
            </a>
          </div>
        </div>
      </header>

      <section id="top" className="relative min-h-[82vh] overflow-hidden border-b border-border pt-24 md:min-h-[88vh]">
        <Image
          src="/mission-map-preview.png"
          alt="SkyGuardian operator map showing persistent local-frame tracking"
          fill
          priority
          sizes="100vw"
          className="object-cover object-center opacity-[0.24]"
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,var(--bg)_0%,oklch(0.965_0.010_95_/_0.94)_34%,oklch(0.965_0.010_95_/_0.54)_72%,transparent_100%)]" />
        <div className="absolute inset-0 hud-grid opacity-60" />
        <div className="scanline-field absolute inset-0" />
        <DroneFlight />

        <div className="relative z-10 mx-auto flex min-h-[calc(82vh-6rem)] max-w-7xl flex-col justify-center px-5 pb-8 md:min-h-[calc(88vh-6rem)] md:px-8">
          <div className="grid items-center gap-10 lg:grid-cols-[0.9fr_0.8fr]">
            <div className="w-full max-w-4xl">
              <p className="mb-6 font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
                Sea / Land / Air
              </p>
              <h1 className="max-w-3xl break-words text-5xl font-semibold leading-[0.92] tracking-normal text-text md:text-8xl">
                SkyGuardian
              </h1>
              <p className="mt-7 max-w-[20rem] text-2xl leading-tight text-text-muted md:max-w-2xl md:text-4xl">
                <span className="block">Deploy a second pair of eyes.</span>
                <span className="block">Keep your first on the mission.</span>
              </p>
              <p className="mt-8 max-w-[20rem] text-base leading-7 text-text-muted md:max-w-xl md:text-lg">
                SkyGuardian gives human operators an autonomous aerial teammate for persistent situational awareness across maritime, land, and infrastructure missions.
              </p>
              <div className="mt-10 flex flex-col gap-3 sm:flex-row">
                <a
                  href="#capability"
                  className="w-full border border-text bg-text px-5 py-3 text-center font-mono text-[11px] uppercase tracking-[0.28em] text-bg transition-colors hover:bg-cta sm:w-auto"
                >
                  See capability
                </a>
                <a
                  href="/operator"
                  className="w-full border border-border-strong bg-surface/80 px-5 py-3 text-center font-mono text-[11px] uppercase tracking-[0.28em] text-text transition-colors hover:border-text sm:w-auto"
                >
                  Open operator UI
                </a>
              </div>
            </div>

            <HeroTelemetry />
          </div>

          <div className="mt-8 grid max-w-3xl grid-cols-1 border border-border-strong bg-surface/80 sm:grid-cols-3 md:mt-12">
            {["Persistent", "Human-led", "Mission-aware"].map((item) => (
              <div key={item} className="border-b border-border px-3 py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0 md:px-5">
                <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-text-dim">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="problem" className="border-b border-border bg-surface">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-[0.9fr_1.4fr] md:px-8">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
              The failure
            </p>
            <h2 className="mt-5 max-w-[20rem] text-3xl font-semibold leading-none md:max-w-none md:text-6xl">
              Awareness does not fail all at once.
            </h2>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            {failures.map((item) => (
              <article key={item.title} className="tac-corners border border-border-strong bg-bg p-5 shadow-[0_18px_60px_oklch(0.12_0.03_130_/_0.06)]">
                <h3 className="text-xl font-semibold leading-tight">{item.title}</h3>
                <p className="mt-5 text-sm leading-6 text-text-muted">{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="capability" className="border-b border-border">
        <div className="mx-auto grid max-w-7xl gap-12 px-5 py-20 md:grid-cols-[1.1fr_0.9fr] md:px-8">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
              The solution
            </p>
            <h2 className="mt-5 max-w-4xl text-4xl font-semibold leading-none md:text-7xl">
              Persistent situational awareness through human-machine teaming.
            </h2>
            <p className="mt-8 max-w-2xl text-lg leading-8 text-text-muted">
              The operator identifies what matters. SkyGuardian maintains observation while the team continues the broader mission.
            </p>
          </div>
          <div className="self-end">
            <MissionDiagram />
          </div>
        </div>
      </section>

      <section className="relative overflow-hidden border-b border-border bg-surface">
        <div className="absolute inset-0 hud-grid opacity-50" />
        <div className="relative mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-[0.9fr_1.1fr] md:px-8">
          <div className="self-center">
            <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
              Live mission surface
            </p>
            <h2 className="mt-5 text-4xl font-semibold leading-none md:text-6xl">
              Command view, target track, and world model in one operating picture.
            </h2>
            <p className="mt-8 max-w-xl text-lg leading-8 text-text-muted">
              The landing page now shows the actual SkyGuardian interface as a mission artifact, not a generic product mockup.
            </p>
          </div>
          <div className="tac-corners relative overflow-hidden border border-border-strong bg-bg p-2 shadow-[0_26px_90px_oklch(0.12_0.03_130_/_0.12)]">
            <div className="relative aspect-[16/10] overflow-hidden border border-border bg-surface">
              <Image
                src="/mission-map-preview.png"
                alt="SkyGuardian local-frame operator view"
                fill
                sizes="(min-width: 768px) 50vw, 100vw"
                className="object-cover object-center"
              />
              <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent_0%,oklch(0.965_0.010_95_/_0.05)_55%,oklch(0.965_0.010_95_/_0.55)_100%)]" />
              <div className="mission-scan absolute inset-x-0 top-0 h-20" />
              <div className="absolute bottom-4 left-4 right-4 grid grid-cols-3 border border-border-strong bg-bg/88 backdrop-blur-sm">
                {telemetry.slice(1).map(([label, value]) => (
                  <div key={label} className="border-r border-border px-3 py-3 last:border-r-0">
                    <p className="font-mono text-[9px] uppercase tracking-[0.28em] text-text-dim">{label}</p>
                    <p className="mt-1 font-mono text-sm font-semibold uppercase tracking-[0.16em] text-text">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="missions" className="border-b border-border bg-surface">
        <div className="mx-auto max-w-7xl px-5 py-20 md:px-8">
          <div className="flex flex-col justify-between gap-6 md:flex-row md:items-end">
            <div>
              <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
                Mission domains
              </p>
              <h2 className="mt-5 max-w-3xl text-4xl font-semibold leading-none md:text-6xl">
                The environment changes. The capability remains constant.
              </h2>
            </div>
            <p className="max-w-md text-base leading-7 text-text-muted">
              One platform supports defense, public safety, infrastructure, and environmental missions without redesigning the core workflow.
            </p>
          </div>

          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {domains.map((domain, index) => (
              <article key={domain.label} className="domain-card border border-border-strong bg-bg">
                <div className="relative h-44 overflow-hidden border-b border-border">
                  <DomainVisual index={index} />
                  <div className="absolute left-5 top-4 border border-border-strong bg-bg/85 px-3 py-2 backdrop-blur-sm">
                    <p className="font-mono text-[11px] uppercase tracking-[0.36em] text-accent">
                      Domain {domain.label}
                    </p>
                  </div>
                </div>
                <div className="p-5">
                  <h3 className="text-3xl font-semibold leading-none">{domain.mission}</h3>
                  <p className="mt-8 text-sm leading-6 text-text-muted">{domain.value}</p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-border">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-[0.8fr_1.2fr] md:px-8">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
              Dual-use market
            </p>
            <h2 className="mt-5 text-4xl font-semibold leading-none md:text-6xl">
              Humans maintain command. SkyGuardian maintains awareness.
            </h2>
          </div>
          <div className="grid grid-cols-2 border border-border-strong bg-surface md:grid-cols-3">
            {markets.map((market) => (
              <div key={market} className="market-tile relative min-h-32 overflow-hidden border-b border-r border-border px-4 py-5 last:border-r-0">
                <div className="absolute inset-x-0 bottom-0 h-px bg-accent/40" />
                <p className="relative font-mono text-[10px] uppercase tracking-[0.24em] text-text-muted">
                  {market}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="roadmap" className="border-b border-border bg-surface">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-3 md:px-8">
          {[
            ["Today", "Leader drone detects, designates, deploys, tracks, and maintains situational awareness."],
            ["Tomorrow", "Multiple coordinated assets hand off observation and keep teams oriented across larger areas."],
            ["Future", "Mission-aware swarms form persistent observation networks with specialized autonomous roles."],
          ].map(([label, body], index) => (
            <article key={label} className="roadmap-card border border-border-strong bg-bg p-6">
              <div className="mb-8 h-24 border border-border bg-surface">
                <RoadmapVisual index={index} />
              </div>
              <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">{label}</p>
              <p className="mt-8 text-2xl font-semibold leading-tight">{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="demo" className="relative overflow-hidden">
        <div className="absolute inset-0 hud-grid opacity-70" />
        <div className="orbital-backdrop absolute right-[-18rem] top-[-8rem] hidden h-[44rem] w-[44rem] md:block" />
        <div className="relative mx-auto max-w-7xl px-5 py-20 md:px-8">
          <div className="max-w-4xl">
            <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
              Get started
            </p>
            <h2 className="mt-5 text-5xl font-semibold leading-none md:text-8xl">
              Observation should be delegated when possible.
            </h2>
            <p className="mt-8 max-w-2xl text-lg leading-8 text-text-muted">
              SkyGuardian is built for the moments when teams need to keep moving, keep deciding, and keep the target in sight.
            </p>
            <div className="mt-10 flex flex-col gap-3 sm:flex-row">
              <a
                href="/operator"
                className="border border-text bg-text px-5 py-3 text-center font-mono text-[11px] uppercase tracking-[0.28em] text-bg transition-colors hover:bg-cta"
              >
                Open operator UI
              </a>
              <a
                href="#top"
                className="border border-border-strong bg-surface/85 px-5 py-3 text-center font-mono text-[11px] uppercase tracking-[0.28em] text-text transition-colors hover:border-text"
              >
                Back to top
              </a>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}

function DroneFlight() {
  return (
    <div className="drone-flight" aria-hidden="true">
      <div className="drone-path drone-path-a" />
      <div className="drone-path drone-path-b" />
      <div className="drone-waypoint drone-waypoint-1" />
      <div className="drone-waypoint drone-waypoint-2" />
      <div className="drone-waypoint drone-waypoint-3" />
      <div className="drone-unit">
        <div className="drone-beam" />
        <div className="drone-shadow" />
        <div className="drone-frame">
          <span className="drone-arm drone-arm-x" />
          <span className="drone-arm drone-arm-y" />
          <span className="drone-rotor drone-rotor-1" />
          <span className="drone-rotor drone-rotor-2" />
          <span className="drone-rotor drone-rotor-3" />
          <span className="drone-rotor drone-rotor-4" />
          <span className="drone-core" />
        </div>
        <div className="drone-label">
          <span>Follower drone</span>
          <strong>Tracking</strong>
        </div>
      </div>
    </div>
  );
}

function HeroTelemetry() {
  return (
    <div className="hero-visual tac-corners hidden border border-border-strong bg-surface/78 p-4 shadow-[0_24px_90px_oklch(0.12_0.03_130_/_0.12)] backdrop-blur-sm lg:block">
      <div className="grid grid-cols-2 border border-border bg-bg/85">
        {telemetry.map(([label, value]) => (
          <div key={label} className="border-b border-r border-border px-4 py-3 even:border-r-0 [&:nth-last-child(-n+2)]:border-b-0">
            <p className="font-mono text-[9px] uppercase tracking-[0.3em] text-text-dim">{label}</p>
            <p className="mt-1 font-mono text-lg font-semibold uppercase tracking-[0.12em] text-text">{value}</p>
          </div>
        ))}
      </div>
      <div className="relative mt-4 aspect-square overflow-hidden border border-border bg-bg">
        <div className="absolute inset-0 hud-grid opacity-80" />
        <div className="radar-rings absolute inset-8" />
        <div className="radar-sweep absolute inset-8" />
        <div className="absolute left-[49%] top-[49%] h-4 w-4 -translate-x-1/2 -translate-y-1/2 border border-text bg-text" />
        {trackNodes.map((node) => (
          <div
            key={node.label}
            className={`track-node track-node-${node.tone}`}
            style={{ left: node.x, top: node.y }}
          >
            <span>{node.label}</span>
          </div>
        ))}
        <div className="signal-path signal-path-a" />
        <div className="signal-path signal-path-b" />
      </div>
    </div>
  );
}

function MissionDiagram() {
  return (
    <div className="grid gap-4">
      <div className="relative min-h-[28rem] overflow-hidden border border-border-strong bg-surface">
        <div className="absolute inset-0 hud-grid opacity-70" />
        <div className="absolute left-5 top-5 right-5 flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.3em] text-text-dim">
          <span>Mission loop</span>
          <span>Live</span>
        </div>
        <div className="orbital-diagram absolute left-1/2 top-1/2 h-72 w-72 -translate-x-1/2 -translate-y-1/2">
          <span className="orbit orbit-1" />
          <span className="orbit orbit-2" />
          <span className="orbit orbit-3" />
          <span className="orbit-core">SG</span>
        </div>
        <div className="absolute bottom-0 left-0 right-0 border-t border-border bg-bg/85 backdrop-blur-sm">
          {capabilities.map((step, index) => (
            <div key={step} className="flex items-center gap-5 border-b border-border px-5 py-4 last:border-b-0">
              <span className="font-mono text-[11px] uppercase tracking-[0.28em] text-accent">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="text-xl font-semibold leading-none">{step}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function DomainVisual({ index }: { index: number }) {
  const labels = [
    ["Harbor", "Vessel", "Guardian"],
    ["Patrol", "Subject", "Overwatch"],
    ["Install", "Asset", "Guardian"],
  ][index];

  return (
    <div className="domain-visual absolute inset-0">
      <div className="absolute inset-0 hud-grid opacity-70" />
      <div className={`domain-sweep domain-sweep-${index}`} />
      <div className="absolute left-[14%] top-[62%] h-4 w-4 border border-text bg-text" />
      <div className="absolute left-[58%] top-[36%] h-5 w-5 border border-accent bg-accent/20" />
      <div className="absolute left-[78%] top-[58%] h-4 w-4 border border-ok bg-ok/20" />
      <div className="absolute left-5 bottom-4 right-5 grid grid-cols-3 border border-border bg-bg/85 backdrop-blur-sm">
        {labels.map((label) => (
          <p key={label} className="border-r border-border px-2 py-2 font-mono text-[8px] uppercase tracking-[0.22em] text-text-muted last:border-r-0">
            {label}
          </p>
        ))}
      </div>
    </div>
  );
}

function RoadmapVisual({ index }: { index: number }) {
  return (
    <div className="relative h-full overflow-hidden">
      <div className="absolute inset-0 hud-grid opacity-60" />
      <div className={`roadmap-line roadmap-line-${index}`} />
      <div className="absolute left-[14%] top-1/2 h-3 w-3 -translate-y-1/2 bg-text" />
      <div className="absolute left-[48%] top-1/2 h-3 w-3 -translate-y-1/2 border border-accent bg-accent/20" />
      <div className="absolute left-[82%] top-1/2 h-3 w-3 -translate-y-1/2 border border-ok bg-ok/20" />
    </div>
  );
}
