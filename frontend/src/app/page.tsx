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
  { step: "Detect", desc: "Autonomous object detection across video feeds" },
  { step: "Designate", desc: "Operator marks what matters" },
  { step: "Deploy", desc: "Companion drone follows on command" },
  { step: "Track", desc: "Persistent lock on designated targets" },
  { step: "Maintain awareness", desc: "Continuous situational picture" },
];

const domains = [
  {
    label: "Sea",
    mission: "Maritime vessel monitoring",
    value: "Harbor security, coastal monitoring, vessel observation, and search and rescue coordination.",
    image: "https://images.unsplash.com/photo-1559827260-dc66d52bef19?w=1200&q=85",
    alt: "Drone aerial view of coastline and harbor operations",
  },
  {
    label: "Land",
    mission: "Perimeter security and force protection",
    value: "Route observation, missing person search, disaster response, and small unit overwatch.",
    image: "/desert-canyon-aerial.png",
    alt: "Aerial drone surveillance of desert canyon terrain",
  },
  {
    label: "Air",
    mission: "Installation and infrastructure awareness",
    value: "Airfield security, wildfire assessment, utility inspection, and large-area monitoring.",
    image: "https://images.unsplash.com/photo-1473968512647-3e447244af8f?w=1200&q=85",
    alt: "Drone flying over terrain during aerial reconnaissance",
  },
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
              href="https://strvx.com/book"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden border border-text bg-text px-4 py-2 font-mono text-[10px] uppercase tracking-[0.26em] text-bg transition-colors hover:bg-cta sm:inline-flex"
            >
              Request demo
            </a>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section id="top" className="relative min-h-[82vh] overflow-hidden border-b border-border pt-24 md:min-h-[88vh]">
        <Image
          src="/hero-drone-city.png"
          alt="DJI Mavic drone flying over city skyline at dusk"
          fill
          priority
          sizes="100vw"
          className="object-cover object-center"
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,var(--bg)_0%,oklch(0.965_0.010_95_/_0.82)_25%,oklch(0.965_0.010_95_/_0.35)_55%,transparent_100%)]" />

        <div className="relative z-10 mx-auto flex min-h-[calc(82vh-6rem)] max-w-7xl flex-col justify-center px-5 pb-8 md:min-h-[calc(88vh-6rem)] md:px-8">
          <div className="max-w-3xl">
            <div className="mb-6 flex items-center gap-4">
              <div className="flex items-center gap-2 border border-border-strong bg-surface/80 px-3 py-1.5 backdrop-blur-sm">
                <Image src="/bow-capital-logo.png" alt="Bow Capital" width={14} height={14} className="h-3.5 w-3.5 brightness-0" />
                <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-text-muted">
                  Built at UCSD &middot; Bow Capital Hackathon
                </p>
              </div>
            </div>
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

          <div className="mt-8 grid max-w-3xl grid-cols-1 border border-border-strong bg-bg backdrop-blur-sm sm:grid-cols-3 md:mt-12">
            {["Persistent", "Human-led", "Mission-aware"].map((item) => (
              <div key={item} className="border-b border-border px-3 py-4 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0 md:px-5">
                <p className="font-mono text-[10px] uppercase tracking-[0.24em] text-text">{item}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Problem */}
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

      {/* Capability */}
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
            <div className="border border-border-strong bg-bg">
              {capabilities.map((cap, index) => (
                <div key={cap.step} className="flex items-start gap-5 border-b border-border px-5 py-4 last:border-b-0">
                  <span className="mt-0.5 font-mono text-[11px] uppercase tracking-[0.28em] text-accent">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <span className="text-xl font-semibold leading-none">{cap.step}</span>
                    <p className="mt-1.5 text-sm leading-snug text-text-muted">{cap.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Operator view — single featured image */}
      <section className="relative overflow-hidden border-b border-border bg-surface">
        <div className="relative mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-[0.9fr_1.1fr] md:px-8">
          <div className="self-center">
            <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
              Live mission surface
            </p>
            <h2 className="mt-5 text-4xl font-semibold leading-none md:text-6xl">
              Command view, target track, and world model in one operating picture.
            </h2>
            <p className="mt-8 max-w-xl text-lg leading-8 text-text-muted">
              Real-time feeds, local-frame mapping, and AI-driven detection fused into a single tactical interface.
            </p>
          </div>
          <div className="tac-corners relative overflow-hidden border border-border-strong bg-bg p-2 shadow-[0_26px_90px_oklch(0.12_0.03_130_/_0.12)]">
            <div className="relative aspect-[16/10] overflow-hidden border border-border bg-surface">
              <Image
                src="/desert-canyon-aerial.png"
                alt="Drone reconnaissance feed showing terrain surveillance"
                fill
                sizes="(min-width: 768px) 50vw, 100vw"
                className="object-cover object-center"
              />
              <div className="absolute inset-0 bg-[linear-gradient(180deg,transparent_0%,oklch(0.965_0.010_95_/_0.03)_60%,oklch(0.965_0.010_95_/_0.40)_100%)]" />
              <div className="absolute bottom-4 left-4 right-4 grid grid-cols-3 border border-border-strong bg-bg">
                {[
                  ["MISSION", "TRACK"],
                  ["ASSETS", "02"],
                  ["CONTACTS", "17"],
                ].map(([label, value]) => (
                  <div key={label} className="border-r border-border px-3 py-3 last:border-r-0">
                    <p className="font-mono text-[9px] uppercase tracking-[0.28em] text-text-muted">{label}</p>
                    <p className="mt-1 font-mono text-sm font-semibold uppercase tracking-[0.16em] text-text">{value}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Mission domains — image cards */}
      <section id="missions" className="border-b border-border">
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
            {domains.map((domain) => (
              <article key={domain.label} className="group border border-border-strong bg-bg transition-all duration-200 hover:border-accent hover:-translate-y-0.5 hover:shadow-[0_20px_70px_oklch(0.12_0.03_130_/_0.10)]">
                <div className="relative h-48 overflow-hidden border-b border-border">
                  <Image
                    src={domain.image}
                    alt={domain.alt}
                    fill
                    sizes="(min-width: 768px) 33vw, 100vw"
                    className="object-cover transition-transform duration-500 group-hover:scale-105"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-bg/20 to-transparent" />
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

      {/* Markets — text only, no image */}
      <section className="border-b border-border bg-surface">
        <div className="mx-auto grid max-w-7xl gap-10 px-5 py-20 md:grid-cols-[1fr_1fr] md:px-8">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
              Dual-use market
            </p>
            <h2 className="mt-5 text-4xl font-semibold leading-none md:text-6xl">
              Humans maintain command. SkyGuardian maintains awareness.
            </h2>
          </div>
          <div className="self-end">
            <p className="max-w-lg text-lg leading-8 text-text-muted">
              One autonomy platform across defense ISR, public safety, port security, emergency response, infrastructure inspection, and environmental monitoring.
            </p>
            <div className="mt-8 grid grid-cols-3 border border-border-strong bg-bg">
              {["Same platform", "Mission changes", "Awareness persists"].map((item) => (
                <p
                  key={item}
                  className="border-r border-border px-4 py-3.5 font-mono text-[9px] uppercase tracking-[0.24em] text-text-muted last:border-r-0"
                >
                  {item}
                </p>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Roadmap — text only, no images */}
      <section id="roadmap" className="border-b border-border">
        <div className="mx-auto max-w-7xl px-5 py-20 md:px-8">
          <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
            Roadmap
          </p>
          <h2 className="mt-5 max-w-3xl text-4xl font-semibold leading-none md:text-6xl">
            From single asset to persistent network.
          </h2>

          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {[
              {
                label: "Today",
                body: "Leader drone detects, designates, deploys, tracks, and maintains situational awareness.",
              },
              {
                label: "Tomorrow",
                body: "Multiple coordinated assets hand off observation and keep teams oriented across larger areas.",
              },
              {
                label: "Future",
                body: "Mission-aware swarms form persistent observation networks with specialized autonomous roles.",
              },
            ].map((item, index) => (
              <article key={item.label} className="tac-corners border border-border-strong bg-surface p-6">
                <div className="flex items-center gap-4">
                  <span className="font-mono text-[11px] uppercase tracking-[0.28em] text-accent">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">{item.label}</p>
                </div>
                <p className="mt-6 text-2xl font-semibold leading-tight">{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Team */}
      <section id="team" className="border-b border-border bg-surface">
        <div className="mx-auto max-w-7xl px-5 py-20 md:px-8">
          <p className="font-mono text-[11px] uppercase tracking-[0.42em] text-accent">
            Our team
          </p>
          <h2 className="mt-5 max-w-3xl text-4xl font-semibold leading-none md:text-6xl">
            Deep robotics and military connections to execute.
          </h2>

          {/* Founders */}
          <div className="mt-12 grid gap-4 md:grid-cols-2">
            {[
              {
                name: "Alex Battikha",
                role: "Co-Founder & CEO",
                image: "/headshot-alex.png",
                points: [
                  "10+ yrs robotics; world champion (1st of 7,100+ teams)",
                  "1 of 9 globally selected as an Irwin Jacobs full-ride scholar",
                  "Patent-pending leader-follower system w/ Johns Hopkins",
                ],
              },
              {
                name: "Nicolas Dos Santos",
                role: "Co-Founder & CEO",
                image: "/headshot-nick.png",
                points: [
                  "TS clearance — access to top-tier government contracts",
                  "Incoming at Amazon",
                  "6+ hackathon winner; ex-founder",
                ],
              },
            ].map((person) => (
              <article key={person.name} className="tac-corners border border-border-strong bg-bg p-6">
                <div className="flex items-center gap-5">
                  <div className="relative h-20 w-20 shrink-0 overflow-hidden rounded-full border border-border-strong bg-surface">
                    <Image src={person.image} alt={person.name} fill sizes="80px" className="object-cover" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold leading-tight">{person.name}</h3>
                    <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.28em] text-accent">{person.role}</p>
                  </div>
                </div>
                <ul className="mt-5 space-y-2">
                  {person.points.map((point) => (
                    <li key={point} className="flex items-start gap-2 text-sm leading-snug text-text-muted">
                      <span className="mt-1.5 block h-1 w-1 shrink-0 bg-accent" />
                      {point}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>

          {/* Advisors & Legal */}
          <div className="mt-4 grid gap-4 md:grid-cols-3">
            {[
              {
                name: "David Resilien",
                role: "Advisor · Defense",
                image: null,
                initials: "DR",
                points: [
                  "Ex-Marine, 20+ yrs",
                  "Deep Marines & DoD connections",
                  "Multi-time startup founder",
                ],
              },
              {
                name: "CJ Mavor",
                role: "Advisor · Business",
                image: null,
                initials: "CJ",
                points: [
                  "Ex-founder, multiple successful startups",
                  "15+ yrs at Berkshire Hathaway",
                ],
              },
              {
                name: "Andre Jun Kim",
                role: "Legal · Gov & Defense",
                image: null,
                initials: "AK",
                points: [
                  "Retired Marine, 20+ yrs",
                  "Extensive DoD & government-contract experience",
                ],
              },
            ].map((person) => (
              <article key={person.name} className="tac-corners border border-border-strong bg-bg p-6">
                <div className="flex items-center gap-4">
                  <div className="relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full border border-border-strong bg-surface">
                    {person.image ? (
                      <Image src={person.image} alt={person.name} fill sizes="64px" className="object-cover" />
                    ) : (
                      <span className="font-mono text-sm font-semibold text-text-dim">{person.initials}</span>
                    )}
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold leading-tight">{person.name}</h3>
                    <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.28em] text-accent">{person.role}</p>
                  </div>
                </div>
                <ul className="mt-4 space-y-2">
                  {person.points.map((point) => (
                    <li key={point} className="flex items-start gap-2 text-sm leading-snug text-text-muted">
                      <span className="mt-1.5 block h-1 w-1 shrink-0 bg-accent" />
                      {point}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section id="demo" className="relative overflow-hidden">
        <Image
          src="https://images.unsplash.com/photo-1508444845599-5c89863b1c44?w=1920&q=85"
          alt="Military drone in flight during reconnaissance"
          fill
          sizes="100vw"
          className="object-cover"
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,var(--bg)_0%,oklch(0.965_0.010_95_/_0.88)_30%,oklch(0.965_0.010_95_/_0.75)_60%,oklch(0.965_0.010_95_/_0.50)_100%)]" />
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
                className="border border-border-strong bg-bg px-5 py-3 text-center font-mono text-[11px] uppercase tracking-[0.28em] text-text transition-colors hover:border-text"
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
