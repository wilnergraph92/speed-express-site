function Er() {
  return d.jsxs("svg", {
    width: "34",
    height: "34",
    viewBox: "0 0 40 40",
    "aria-hidden": "true",
    children: [
      d.jsx("circle", { cx: "20", cy: "20", r: "17", fill: "#6C5CE7" }),
      d.jsx("path", {
        d: "M28.4 15.4c-2-2.5-5-3.9-8.4-3.6-5 .4-8.8 4.8-8.3 9.7.5 5 5 8.7 9.9 8.2 3.5-.3 6.4-2.7 7.4-5.9",
        fill: "none",
        stroke: "#fff",
        strokeWidth: "3.4",
        strokeLinecap: "round",
      }),
    ],
  });
}
function vf({ label: h, icon: E, active: _, badge: r, onClick: U }) {
  return d.jsxs("a", {
    href: "#",
    onClick: (R) => {
      (R.preventDefault(), U?.());
    },
    "aria-current": _ ? "page" : void 0,
    className: `group flex items-center gap-3 rounded-xl px-3.5 py-[11px] text-[14px] font-medium transition-all duration-200 ${_ ? "bg-gradient-to-r from-[#6C5CE7] to-[#8071F0] text-white shadow-lg shadow-[#6C5CE7]/30" : "text-[#A69FD0] hover:bg-white/[.06] hover:text-white"}`,
    children: [
      d.jsx(E, { size: 18, strokeWidth: _ ? 2.2 : 1.9 }),
      d.jsx("span", { className: "flex-1", children: h }),
      r &&
        d.jsx("span", {
          className:
            "grid h-[19px] min-w-[19px] place-items-center rounded-md bg-[#FF4757] px-1 text-[11px] font-bold leading-none text-white",
          children: r,
        }),
    ],
  });
}
function H0({ onNavigate: h }) {
  return d.jsxs("div", {
    className: "flex h-full flex-col px-5 pb-5 pt-6",
    children: [
      d.jsxs("div", {
        className: "flex items-center justify-between px-1.5",
        children: [
          d.jsxs("a", {
            href: "#",
            onClick: (E) => E.preventDefault(),
            className: "flex items-center gap-2.5",
            children: [
              d.jsx(Er, {}),
              d.jsx("span", {
                className:
                  "text-[19px] font-semibold tracking-tight text-white",
                children: "ShipFast",
              }),
            ],
          }),
          d.jsx("button", {
            type: "button",
            "aria-label": "Collapse sidebar",
            className: "text-[#8D87C0] transition-colors hover:text-white",
            children: d.jsx(vr, { size: 19 }),
          }),
          d.jsx("button", {
            type: "button",
            "aria-label": "Close menu",
            onClick: h,
            className:
              "-mr-1 rounded-lg p-1.5 text-[#8D87C0] transition-colors hover:text-white lg:hidden",
            children: d.jsx(xr, { size: 18 }),
          }),
        ],
      }),
      d.jsx("p", {
        className:
          "mb-3 mt-9 px-2.5 text-[11px] font-semibold tracking-[0.16em] text-[#7A73B0]",
        children: "OVERVIEW",
      }),
      d.jsx("nav", {
        className: "flex flex-col gap-1.5",
        "aria-label": "Main navigation",
        children: zr.map((E) => d.jsx(vf, { ...E, onClick: h }, E.label)),
      }),
      d.jsxs("div", {
        className:
          "mt-auto flex flex-col gap-1.5 border-t border-white/10 pt-4",
        children: [
          d.jsx(vf, { label: "Help", icon: fr, onClick: h }),
          d.jsx(vf, { label: "Log Out", icon: hr, onClick: h }),
        ],
      }),
    ],
  });
}
function Ar({ open: h, onClose: E }) {
  return d.jsxs(d.Fragment, {
    children: [
      d.jsx("aside", {
        className:
          "hidden w-[280px] shrink-0 bg-gradient-to-b from-[#1B1450] via-[#160F42] to-[#120D33] lg:block",
        children: d.jsx(H0, {}),
      }),
      d.jsxs("div", {
        className: `fixed inset-0 z-50 lg:hidden ${h ? "" : "pointer-events-none"}`,
        children: [
          d.jsx("div", {
            "aria-hidden": "true",
            onClick: E,
            className: `absolute inset-0 bg-[#0B0824]/60 backdrop-blur-[2px] transition-opacity duration-300 ${h ? "opacity-100" : "opacity-0"}`,
          }),
          d.jsx("aside", {
            className: `absolute inset-y-0 left-0 w-[280px] bg-gradient-to-b from-[#1B1450] via-[#160F42] to-[#120D33] shadow-2xl transition-transform duration-300 ease-out ${h ? "translate-x-0" : "-translate-x-full"}`,
            "aria-hidden": !h,
            children: d.jsx(H0, { onNavigate: E }),
          }),
        ],
      }),
    ],
  });
}
const Tr =
  "https://images.pexels.com/photos/7717254/pexels-photo-7717254.jpeg?auto=compress&cs=tinysrgb&fit=crop&w=160&h=160";
function B0({ children: h, label: E }) {
  return d.jsx("button", {
    type: "button",
    "aria-label": E,
    className:
      "relative grid h-10 w-10 place-items-center rounded-xl bg-[#F3F4FA] text-[#4A4768] transition-colors hover:bg-[#ECEBFA] hover:text-[#191345]",
    children: h,
  });
}
function _r({ onMenu: h }) {
  const [E, _] = ql.useState(!1);
  return d.jsxs("header", {
    className:
      "flex h-[68px] shrink-0 items-center gap-3 rounded-2xl bg-white px-3.5 shadow-[0_12px_32px_-16px_rgba(63,50,150,0.18)] sm:px-5",
    children: [
      d.jsx("button", {
        type: "button",
        onClick: h,
        "aria-label": "Open menu",
        className:
          "-ml-0.5 rounded-lg p-2 text-[#4A4768] transition-colors hover:bg-[#F3F4FA] lg:hidden",
        children: d.jsx(mr, { size: 20 }),
      }),
      d.jsx("h1", {
        className:
          "whitespace-nowrap text-[21px] font-semibold tracking-tight text-[#191345]",
        children: "Dashboard",
      }),
      d.jsx("div", {
        className: "flex min-w-0 flex-1 justify-center px-1 sm:px-3",
        children: d.jsxs("label", {
          className:
            "group flex h-11 w-full max-w-[430px] items-center gap-2.5 rounded-xl border border-transparent bg-[#F3F4FA] px-4 transition-all focus-within:border-[#6C5CE7]/35 focus-within:bg-white focus-within:ring-2 focus-within:ring-[#6C5CE7]/20",
          children: [
            d.jsx(br, {
              size: 16,
              className:
                "shrink-0 text-[#9B9AB8] transition-colors group-focus-within:text-[#6C5CE7]",
            }),
            d.jsx("input", {
              type: "search",
              placeholder: "Search here...",
              className:
                "w-full bg-transparent text-[13.5px] font-medium text-[#191345] outline-none placeholder:font-normal placeholder:text-[#9B9AB8]",
            }),
          ],
        }),
      }),
      d.jsxs("div", {
        className: "flex shrink-0 items-center gap-2 sm:gap-2.5",
        children: [
          d.jsxs(B0, {
            label: "Notifications",
            children: [
              d.jsx(nr, { size: 18 }),
              d.jsx("span", {
                className:
                  "absolute right-[9px] top-[9px] h-2 w-2 rounded-full bg-[#FF4757] ring-2 ring-[#F3F4FA]",
              }),
            ],
          }),
          d.jsx(B0, { label: "Settings", children: d.jsx(pr, { size: 18 }) }),
          d.jsxs("button", {
            type: "button",
            className:
              "ml-0.5 flex items-center gap-2.5 rounded-xl p-1.5 pr-2 transition-colors hover:bg-[#F3F4FA] sm:pr-2.5",
            children: [
              d.jsxs("span", {
                className: "relative shrink-0",
                children: [
                  E
                    ? d.jsx("span", {
                        className:
                          "grid h-9 w-9 place-items-center rounded-full bg-[#6C5CE7] text-[13px] font-semibold text-white",
                        children: "EH",
                      })
                    : d.jsx("img", {
                        src: Tr,
                        alt: "Esther Howard",
                        width: 36,
                        height: 36,
                        referrerPolicy: "no-referrer",
                        onError: () => _(!0),
                        className: "h-9 w-9 rounded-full object-cover",
                      }),
                  d.jsx("span", {
                    className:
                      "absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full bg-[#22C55E] ring-2 ring-white",
                  }),
                ],
              }),
              d.jsx("span", {
                className:
                  "hidden text-[13.5px] font-semibold leading-none text-[#191345] md:block",
                children: "Esther Howard",
              }),
              d.jsx(w0, {
                size: 15,
                className: "hidden text-[#8A89A6] md:block",
              }),
            ],
          }),
        ],
      }),
    ],
  });
}
function Na({ children: h, delay: E = 0, className: _ = "" }) {
  const r = ql.useRef(null),
    [U, R] = ql.useState(!1);
  return (
    ql.useEffect(() => {
      const V = r.current;
      if (!V) return;
      const K = new IntersectionObserver(
        ([j]) => {
          j.isIntersecting && (R(!0), K.disconnect());
        },
        { threshold: 0.12, rootMargin: "0px 0px -32px 0px" },
      );
      return (K.observe(V), () => K.disconnect());
    }, []),
    d.jsx("div", {
      ref: r,
      className: `reveal ${U ? "reveal-in" : ""} ${_}`,
      style: { transitionDelay: `${E}ms` },
      children: h,
    })
  );
}
function rd({ up: h }) {
  return d.jsxs("span", {
    className: `inline-flex items-center gap-0.5 rounded-md px-1.5 py-[3px] text-[11px] font-bold leading-none ${h ? "bg-[#DCF6E9] text-[#12B76A]" : "bg-[#FFE4E6] text-[#F04452]"}`,
    children: [
      "10%",
      h
        ? d.jsx(Ln, { size: 11, strokeWidth: 3.2 })
        : d.jsx(ur, { size: 11, strokeWidth: 3.2 }),
    ],
  });
}
function xf({ options: h, align: E = "right" }) {
  const [_, r] = ql.useState(!1),
    [U, R] = ql.useState(h[0]),
    V = ql.useRef(null);
  return (
    ql.useEffect(() => {
      const K = (j) => {
        V.current && !V.current.contains(j.target) && r(!1);
      };
      return (
        document.addEventListener("mousedown", K),
        () => document.removeEventListener("mousedown", K)
      );
    }, []),
    d.jsxs("div", {
      ref: V,
      className: "relative shrink-0",
      children: [
        d.jsxs("button", {
          type: "button",
          onClick: () => r((K) => !K),
          "aria-haspopup": "listbox",
          "aria-expanded": _,
          className: `flex h-9 items-center gap-2 rounded-xl border border-[#E4E5F1] bg-white px-3.5 text-[12.5px] font-semibold text-[#3d3a5c] transition-colors hover:border-[#c9cbdf] hover:bg-[#fafafe] ${_ ? "border-[#c9cbdf] bg-[#fafafe]" : ""}`,
          children: [
            d.jsx(cr, { size: 15, className: "text-[#6C5CE7]" }),
            U,
            d.jsx(w0, {
              size: 14,
              className: `text-[#8A89A6] transition-transform duration-200 ${_ ? "rotate-180" : ""}`,
            }),
          ],
        }),
        _ &&
          d.jsx("div", {
            role: "listbox",
            className: `animate-pop absolute top-[calc(100%+6px)] z-30 w-36 rounded-xl border border-[#E9EAF4] bg-white p-1.5 shadow-xl shadow-[#4b3fb8]/10 ${E === "right" ? "right-0" : "left-0"}`,
            children: h.map((K) =>
              d.jsx(
                "button",
                {
                  type: "button",
                  role: "option",
                  "aria-selected": K === U,
                  onClick: () => {
                    (R(K), r(!1));
                  },
                  className: `w-full rounded-lg px-3 py-2 text-left text-[13px] font-medium transition-colors ${K === U ? "bg-[#F0EEFF] text-[#5A4BD1]" : "text-[#4a4768] hover:bg-[#F5F5FB]"}`,
                  children: K,
                },
                K,
              ),
            ),
          }),
      ],
    })
  );
}
function Mr(h) {
  let E = `M ${h[0][0]} ${h[0][1]}`;
  for (let _ = 0; _ < h.length - 1; _++) {
    const r = h[Math.max(0, _ - 1)],
      U = h[_],
      R = h[_ + 1],
      V = h[Math.min(h.length - 1, _ + 2)],
      K = U[0] + (R[0] - r[0]) / 6,
      j = U[1] + (R[1] - r[1]) / 6,
      T = R[0] - (V[0] - U[0]) / 6,
      J = R[1] - (V[1] - U[1]) / 6;
    E += ` C ${K.toFixed(1)} ${j.toFixed(1)}, ${T.toFixed(1)} ${J.toFixed(1)}, ${R[0]} ${R[1]}`;
  }
  return E;
}
const Nr = [
  {
    label: "Total Shipment",
    value: "3,024",
    up: !0,
    icon: ir,
    tint: "bg-[#EEECFE] text-[#6C5CE7]",
    cls: "sm:border-r",
  },
  {
    label: "On Going Air Freight",
    value: "2147",
    up: !1,
    icon: gr,
    tint: "bg-[#FEF1E4] text-[#FF9F43]",
    cls: "border-t sm:border-t-0",
  },
  {
    label: "On Going Ocean Freight",
    value: "7120",
    up: !1,
    icon: cd,
    tint: "bg-[#FFEBEB] text-[#FF6B6B]",
    cls: "border-t sm:border-r",
  },
  {
    label: "On Going Road Freight",
    value: "8892",
    up: !0,
    icon: od,
    tint: "bg-[#E4F9EC] text-[#2BC96F]",
    cls: "border-t",
  },
];
function jr() {
  return d.jsx("section", {
    "aria-label": "Shipment statistics",
    className: "card h-full overflow-hidden",
    children: d.jsx("div", {
      className: "grid h-full grid-cols-1 sm:grid-cols-2",
      children: Nr.map((h) =>
        d.jsxs(
          "div",
          {
            className: `flex flex-col justify-center border-[#ECECF5] px-6 py-5 sm:px-7 sm:py-6 ${h.cls}`,
            children: [
              d.jsxs("div", {
                className: "flex items-start justify-between gap-3",
                children: [
                  d.jsx("p", {
                    className:
                      "pt-1 text-[13px] font-medium leading-5 text-[#8A89A6]",
                    children: h.label,
                  }),
                  d.jsx("span", {
                    className: `grid h-11 w-11 shrink-0 place-items-center rounded-full ${h.tint}`,
                    children: d.jsx(h.icon, { size: 21, strokeWidth: 1.9 }),
                  }),
                ],
              }),
              d.jsx("p", {
                className:
                  "mt-1 text-[30px] font-semibold tracking-tight text-[#191345]",
                children: h.value,
              }),
              d.jsxs("div", {
                className: "mt-3 flex flex-wrap items-center gap-2",
                children: [
                  d.jsx(rd, { up: h.up }),
                  d.jsx("span", {
                    className: "text-[12.5px] font-medium text-[#8A89A6]",
                    children: "From Last Month",
                  }),
                ],
              }),
            ],
          },
          h.label,
        ),
      ),
    }),
  });
}
const Dr = ["Dec 28", "Dec 29", "Dec 30", "Dec 31", "Jan 1", "Jan 2", "Jan 3"],
  R0 = [20, 55, 52, 36, 74, 44, 86],
  Cr = 580,
  Or = 190,
  q0 = 24,
  Ur = 556,
  md = R0.map((h, E) => [
    q0 + (E * (Ur - q0)) / (R0.length - 1),
    176 - h * 1.5,
  ]),
  Hr = Mr(md);
function Br() {
  return d.jsxs("section", {
    "aria-label": "Recurring revenue",
    className: "card flex h-full flex-col p-6",
    children: [
      d.jsxs("div", {
        className: "flex items-start justify-between gap-4",
        children: [
          d.jsxs("div", {
            children: [
              d.jsx("p", {
                className: "text-[13px] font-medium text-[#8A89A6]",
                children: "Recurring Revenue",
              }),
              d.jsxs("div", {
                className: "mt-1.5 flex flex-wrap items-center gap-2.5",
                children: [
                  d.jsx("span", {
                    className:
                      "text-[26px] font-semibold tracking-tight text-[#191345]",
                    children: "$156,098",
                  }),
                  d.jsx(rd, { up: !0 }),
                ],
              }),
            ],
          }),
          d.jsx(xf, { options: ["This Week", "Last Week", "This Month"] }),
        ],
      }),
      d.jsxs("div", {
        className: "mt-5 min-h-[180px] flex-1",
        children: [
          d.jsxs("svg", {
            viewBox: `0 0 ${Cr} ${Or}`,
            preserveAspectRatio: "none",
            className: "h-full w-full",
            role: "img",
            "aria-label": "Recurring revenue line chart for this week",
            children: [
              md.map(([h], E) =>
                d.jsx(
                  "line",
                  {
                    x1: h,
                    y1: 8,
                    x2: h,
                    y2: 168,
                    stroke: "#E9EAF4",
                    strokeWidth: 1,
                    strokeDasharray: "3 5",
                  },
                  E,
                ),
              ),
              d.jsx("path", {
                d: Hr,
                fill: "none",
                stroke: "#6C5CE7",
                strokeWidth: 2.4,
                strokeLinecap: "round",
                strokeLinejoin: "round",
                pathLength: 1,
                className: "line-draw",
                vectorEffect: "non-scaling-stroke",
              }),
            ],
          }),
          d.jsx("div", {
            className: "mt-2 flex pl-[4.1%] pr-[4.1%] justify-between",
            children: Dr.map((h) =>
              d.jsx(
                "span",
                {
                  className: "text-[11px] font-medium text-[#9B9AB8]",
                  children: h,
                },
                h,
              ),
            ),
          }),
        ],
      }),
    ],
  });
}
const Y0 = [
    { d: "Sat", v: 88, done: 262, rej: 16 },
    { d: "Sun", v: 44, done: 140, rej: 8 },
    { d: "Mon", v: 58, done: 187, rej: 12 },
    { d: "Tue", v: 80, done: 280, rej: 23, hot: !0 },
    { d: "Wed", v: 55, done: 176, rej: 10 },
    { d: "Thu", v: 77, done: 254, rej: 14 },
    { d: "Fri", v: 62, done: 208, rej: 11 },
  ],
  G0 = [100, 80, 60, 40, 20, 0];
function Rr() {
  return d.jsxs("section", {
    "aria-label": "Shipment over time",
    className: "card flex h-full flex-col p-6",
    children: [
      d.jsxs("div", {
        className: "flex items-center justify-between gap-4",
        children: [
          d.jsx("h2", {
            className:
              "text-[19px] font-semibold tracking-tight text-[#191345]",
            children: "Shipment over time",
          }),
          d.jsx(xf, { options: ["This Week", "This Month", "This Year"] }),
        ],
      }),
      d.jsxs("div", {
        className: "mt-5 flex min-h-[240px] flex-1 gap-2",
        children: [
          d.jsx("div", {
            className: "relative w-9 shrink-0",
            "aria-hidden": "true",
            children: G0.map((h) =>
              d.jsxs(
                "span",
                {
                  className:
                    "absolute right-1 -translate-y-1/2 text-[11px] font-medium leading-none text-[#9B9AB8]",
                  style: { top: `${100 - h}%` },
                  children: [h, "%"],
                },
                h,
              ),
            ),
          }),
          d.jsxs("div", {
            className: "relative flex-1",
            children: [
              G0.map((h) =>
                d.jsx(
                  "div",
                  {
                    "aria-hidden": "true",
                    className:
                      "absolute inset-x-0 border-t border-dashed border-[#EBECF4]",
                    style: { top: `${100 - h}%` },
                  },
                  h,
                ),
              ),
              d.jsx("div", {
                className:
                  "absolute inset-0 flex items-end justify-between px-2 sm:px-4",
                children: Y0.map((h, E) => {
                  const _ = E >= 5 && !h.hot;
                  return d.jsxs(
                    "div",
                    {
                      className:
                        "group relative flex h-full flex-1 items-end justify-center",
                      children: [
                        d.jsx("div", {
                          className: `bar w-full max-w-[46px] rounded-[10px] ${h.hot ? "hatch bg-[#FF8A5C] shadow-[0_12px_22px_-10px_rgba(255,138,92,0.7)]" : "bg-[#ECECF4] transition-colors group-hover:bg-[#E1E2F0]"}`,
                          style: { height: `${h.v}%`, "--i": E },
                        }),
                        d.jsxs("div", {
                          role: "tooltip",
                          className: `pointer-events-none absolute z-10 w-max rounded-xl bg-[#17123A] px-3.5 py-2.5 text-[11.5px] leading-[1.55] shadow-xl shadow-[#17123A]/30 transition-all duration-200 ${h.hot ? "opacity-100" : "translate-y-1 opacity-0 group-hover:translate-y-0 group-hover:opacity-100"}`,
                          style: {
                            bottom: `calc(${h.v}% + 12px)`,
                            ...(_ ? { right: "42%" } : { left: "58%" }),
                          },
                          children: [
                            d.jsx("span", {
                              "aria-hidden": "true",
                              className: `absolute top-1/2 h-2.5 w-2.5 -translate-y-1/2 rotate-45 bg-[#17123A] ${_ ? "-right-1" : "-left-1"}`,
                            }),
                            d.jsxs("div", {
                              className: "flex items-center gap-2.5",
                              children: [
                                d.jsx("span", {
                                  className: "text-[#A9A5D4]",
                                  children: "Shipment Completed",
                                }),
                                d.jsx("span", {
                                  className: "font-bold text-white",
                                  children: h.done,
                                }),
                              ],
                            }),
                            d.jsxs("div", {
                              className: "flex items-center gap-2.5",
                              children: [
                                d.jsx("span", {
                                  className: "text-[#A9A5D4]",
                                  children: "Shipment Rejected",
                                }),
                                d.jsx("span", {
                                  className: "font-bold text-white",
                                  children: h.rej,
                                }),
                              ],
                            }),
                          ],
                        }),
                      ],
                    },
                    h.d,
                  );
                }),
              }),
            ],
          }),
        ],
      }),
      d.jsx("div", {
        className: "mt-3 flex pl-[52px] pr-2 sm:pl-[56px] sm:pr-4",
        "aria-hidden": "true",
        children: Y0.map((h) =>
          d.jsx(
            "span",
            {
              className:
                "flex-1 text-center text-[12px] font-medium text-[#9B9AB8]",
              children: h.d,
            },
            h.d,
          ),
        ),
      }),
    ],
  });
}
const qr = [
    { t: "Total Shipment Profit", c: "#74B3FF" },
    { t: "Air Freight Profit", c: "#FF8A8A" },
    { t: "Ocean Freight Profit", c: "#B18CF5" },
    { t: "Road Freight Profit", c: "#C3CFEC" },
  ],
  gf = [
    [0, 300, 28, 84],
    [90, 214, 96, 72],
    [180, 260, 84, 70],
    [270, 360, 100, 72],
    [360, 300, 28, 84],
  ];
function Yr(h) {
  for (let E = 0; E < gf.length - 1; E++) {
    const [_, r, U, R] = gf[E],
      [V, K, j, T] = gf[E + 1];
    if (h >= _ && h <= V) {
      const J = (h - _) / (V - _ || 1),
        B = r + (K - r) * J,
        Z = U + (j - U) * J,
        yl = R + (T - R) * J;
      return `hsl(${B.toFixed(1)} ${Z.toFixed(1)}% ${yl.toFixed(1)}%)`;
    }
  }
  return "#C3CFEC";
}
const X0 = 56,
  Gr = Array.from({ length: X0 }, (h, E) => {
    const _ = (E * 360) / X0,
      r = 0.32 + 0.68 * Math.min(1, Math.min(_, 360 - _) / 95);
    return { transform: `rotate(${_} 130 130)`, color: Yr(_), alpha: r, i: E };
  });
function Xr() {
  return d.jsxs("section", {
    "aria-label": "Profit statistics",
    className: "card flex h-full flex-col p-6",
    children: [
      d.jsxs("div", {
        className: "flex items-center justify-between gap-3",
        children: [
          d.jsx("h2", {
            className:
              "text-[19px] font-semibold tracking-tight text-[#191345]",
            children: "Profit statistics",
          }),
          d.jsx("button", {
            type: "button",
            "aria-label": "Profit options",
            className:
              "grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[#F3F4FA] text-[#4A4768] transition-colors hover:bg-[#ECEBFA] hover:text-[#191345]",
            children: d.jsx(Sr, { size: 16 }),
          }),
        ],
      }),
      d.jsx("div", {
        className: "mt-4 grid grid-cols-1 gap-x-4 gap-y-2.5 sm:grid-cols-2",
        children: qr.map((h) =>
          d.jsxs(
            "span",
            {
              className:
                "flex items-center gap-2 text-[12px] font-medium text-[#8A89A6]",
              children: [
                d.jsx("span", {
                  className: "h-2.5 w-2.5 shrink-0 rounded-full",
                  style: { background: h.c },
                }),
                h.t,
              ],
            },
            h.t,
          ),
        ),
      }),
      d.jsxs("div", {
        className: "relative mx-auto my-auto w-full max-w-[240px]",
        children: [
          d.jsx("svg", {
            viewBox: "0 0 260 260",
            className: "w-full",
            role: "img",
            "aria-label": "87 percent profit from yesterday",
            children: Gr.map((h) =>
              d.jsx(
                "rect",
                {
                  x: 127.25,
                  y: 20,
                  width: 5.5,
                  height: 27,
                  rx: 2.75,
                  fill: h.color,
                  transform: h.transform,
                  className: "tick",
                  style: { "--o": h.alpha, "--i": h.i },
                },
                h.i,
              ),
            ),
          }),
          d.jsxs("div", {
            className:
              "pointer-events-none absolute inset-0 flex flex-col items-center justify-center",
            children: [
              d.jsx("span", {
                className:
                  "text-[40px] font-bold leading-none tracking-tight text-[#191345]",
                children: "87%",
              }),
              d.jsx("span", {
                className: "mt-1.5 text-[12px] font-medium text-[#8A89A6]",
                children: "Profit from yesterday",
              }),
            ],
          }),
        ],
      }),
      d.jsxs("p", {
        className: "pb-1 text-center text-[13px] font-medium text-[#8A89A6]",
        children: [
          "Profit is ",
          d.jsx("span", {
            className: "font-bold text-[#191345]",
            children: "36%",
          }),
          " More than last week",
        ],
      }),
    ],
  });
}
function Qr() {
  return d.jsxs("section", {
    "aria-label": "Customer growth",
    className:
      "group/grow relative flex h-full min-h-[232px] flex-col overflow-hidden rounded-[20px] bg-[#1B1448] p-6 text-white shadow-[0_26px_52px_-22px_rgba(27,20,72,0.6)] ring-1 ring-white/10 transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_34px_64px_-24px_rgba(27,20,72,0.7)]",
    style: {
      backgroundImage:
        "radial-gradient(420px 220px at 88% -20%, rgba(108,92,231,0.4), transparent 65%)",
    },
    children: [
      d.jsx(Ln, {
        "aria-hidden": "true",
        strokeWidth: 1,
        className:
          "pointer-events-none absolute -bottom-10 -right-8 h-44 w-44 text-white/[.05]",
      }),
      d.jsxs("div", {
        className: "relative flex items-center justify-between gap-3",
        children: [
          d.jsxs("span", {
            className:
              "flex items-center gap-2.5 text-[14.5px] font-medium text-[#D9D5F2]",
            children: [
              d.jsx(Sf, { size: 17, className: "text-[#8F84D8]" }),
              "Customer Growth",
            ],
          }),
          d.jsx("button", {
            type: "button",
            "aria-label": "View growth details",
            className:
              "grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#6C5CE7] shadow-lg shadow-[#6C5CE7]/40 transition-transform duration-200 hover:scale-105 active:scale-95",
            children: d.jsx(Ln, { size: 17, strokeWidth: 2.4 }),
          }),
        ],
      }),
      d.jsxs("div", {
        className: "relative mt-2 flex flex-1 flex-col justify-center py-4",
        children: [
          d.jsxs("div", {
            className: "flex items-center gap-3",
            children: [
              d.jsx("span", {
                className: "text-[32px] font-bold leading-none tracking-tight",
                children: "+91.7%",
              }),
              d.jsxs("span", {
                className:
                  "flex items-center gap-1 rounded-md bg-[#B9E937] px-2 py-[6px] text-[11.5px] font-bold leading-none text-[#17123A]",
                children: [d.jsx(Ln, { size: 12, strokeWidth: 3.2 }), "10%"],
              }),
            ],
          }),
          d.jsx("div", {
            className: "relative mt-5 h-11 overflow-hidden rounded-xl bg-white",
            children: d.jsx("div", {
              className:
                "bar-fill hatch-dark absolute inset-y-0 left-0 flex items-center rounded-xl bg-[#6C5CE7] pl-4",
              style: { "--fill": "91.7%" },
              children: d.jsxs("span", {
                className: "bar-label flex items-baseline whitespace-nowrap",
                children: [
                  d.jsx("span", {
                    className: "text-[14px] font-bold leading-none text-white",
                    children: "+91.7%",
                  }),
                  d.jsx("span", {
                    className: "ml-1 text-[11px] font-medium text-white/70",
                    children: "/100",
                  }),
                ],
              }),
            }),
          }),
        ],
      }),
    ],
  });
}
const Zr = [
    {
      icon: or,
      color: "text-[#FF9F43]",
      value: "35,254",
      label: "Overall Page Visits",
    },
    {
      icon: od,
      color: "text-[#6C5CE7]",
      value: "10,372",
      label: "Overall Shipment",
    },
    { icon: Sf, color: "text-[#2BC96F]", value: "2100", label: "New Visitors" },
  ],
  Lr = [
    { x: 25.8, y: 21.4, name: "Toronto" },
    { x: 19.8, y: 26.9, name: "San Francisco" },
    { x: 55.9, y: 16, name: "Belarus", flag: !0 },
    { x: 64.2, y: 11.2, name: "Moscow" },
    { x: 70.8, y: 37.1, name: "Mumbai" },
    { x: 55.6, y: 86.7, name: "Johannesburg" },
    { x: 86.8, y: 83.3, name: "Sydney" },
  ];
function Vr({ className: h }) {
  return d.jsx("svg", {
    viewBox: "30 40 970 420",
    preserveAspectRatio: "none",
    className: h,
    "aria-hidden": "true",
    children: d.jsxs("g", {
      fill: "#E7EAF4",
      stroke: "#DFE3F0",
      strokeWidth: "1",
      children: [
        d.jsx("path", {
          d: "M 48 128 C 60 88 108 60 168 58 C 226 56 282 72 316 104 C 338 124 344 152 330 176 C 316 198 296 214 282 236 C 268 258 262 282 244 296 C 232 305 220 296 214 282 C 200 260 178 246 152 236 C 118 224 84 208 66 180 C 54 160 44 148 48 128 Z",
        }),
        d.jsx("path", {
          d: "M 244 296 C 258 306 268 322 266 340 C 264 356 252 364 242 354 C 232 344 228 328 230 314 C 232 302 236 294 244 296 Z",
        }),
        d.jsx("path", {
          d: "M 356 44 C 378 28 414 26 436 44 C 452 58 450 84 432 98 C 412 112 380 110 364 94 C 350 80 346 58 356 44 Z",
        }),
        d.jsx("path", {
          d: "M 292 368 C 312 350 348 352 368 372 C 386 390 392 420 382 448 C 372 476 350 500 328 496 C 310 492 300 468 294 442 C 288 412 284 384 292 368 Z",
        }),
        d.jsx("path", {
          d: "M 462 112 C 468 104 480 104 484 112 C 487 119 482 128 473 128 C 465 128 458 119 462 112 Z",
        }),
        d.jsx("path", {
          d: "M 474 138 C 486 112 520 100 554 104 C 584 108 608 122 614 146 C 618 166 602 180 582 184 C 562 188 548 198 532 194 C 508 188 486 172 478 156 C 474 148 472 144 474 138 Z",
        }),
        d.jsx("path", {
          d: "M 478 244 C 506 228 556 226 586 246 C 610 262 618 296 610 330 C 600 368 582 404 558 428 C 542 444 522 438 512 418 C 498 388 480 352 472 316 C 466 288 468 258 478 244 Z",
        }),
        d.jsx("path", {
          d: "M 622 96 C 686 62 788 56 866 82 C 926 102 962 142 952 186 C 942 222 902 242 862 252 C 830 260 802 276 776 296 C 750 316 726 330 706 320 C 686 310 672 290 662 268 C 642 246 626 220 622 192 C 619 164 616 126 622 96 Z",
        }),
        d.jsx("path", {
          d: "M 704 188 C 716 200 724 222 716 242 C 708 254 694 248 690 232 C 686 214 694 196 704 188 Z",
        }),
        d.jsx("path", {
          d: "M 828 332 C 848 322 880 326 894 342 C 900 354 888 362 868 362 C 848 362 828 348 828 332 Z",
        }),
        d.jsx("path", {
          d: "M 892 128 C 906 120 920 128 922 146 C 923 162 912 174 900 170 C 890 166 884 136 892 128 Z",
        }),
        d.jsx("path", {
          d: "M 812 402 C 842 386 892 390 916 410 C 932 428 922 450 896 458 C 864 468 826 460 810 440 C 800 428 802 410 812 402 Z",
        }),
      ],
    }),
  });
}
function Kr() {
  return d.jsxs("section", {
    "aria-label": "Most active orders in countries",
    className: "card flex h-full flex-col p-6",
    children: [
      d.jsxs("div", {
        className: "flex items-center justify-between gap-4",
        children: [
          d.jsx("h2", {
            className:
              "text-[19px] font-semibold tracking-tight text-[#191345]",
            children: "Most active orders in countries",
          }),
          d.jsx(xf, { options: ["Last 7 Days", "Last 30 Days", "This Year"] }),
        ],
      }),
      d.jsx("div", {
        className:
          "mt-4 grid grid-cols-1 divide-y divide-[#EDEEF5] rounded-xl border border-[#E9EAF3] bg-white sm:grid-cols-3 sm:divide-x sm:divide-y-0",
        children: Zr.map((h) =>
          d.jsxs(
            "div",
            {
              className: "flex items-center gap-2.5 px-4 py-3",
              children: [
                d.jsx(h.icon, {
                  size: 19,
                  className: `shrink-0 ${h.color}`,
                  strokeWidth: 2,
                }),
                d.jsx("span", {
                  className:
                    "whitespace-nowrap text-[15px] font-semibold text-[#191345]",
                  children: h.value,
                }),
                d.jsx("span", {
                  className:
                    "whitespace-nowrap text-[12px] font-medium text-[#9B9AB8]",
                  children: h.label,
                }),
              ],
            },
            h.label,
          ),
        ),
      }),
      d.jsxs("div", {
        className: "relative mt-5 min-h-[220px] flex-1",
        children: [
          d.jsx(Vr, { className: "absolute inset-0 h-full w-full" }),
          Lr.map((h) =>
            d.jsxs(
              "div",
              {
                className: "group absolute",
                style: { left: `${h.x}%`, top: `${h.y}%` },
                children: [
                  d.jsx("span", {
                    className:
                      "dot-pulse block h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#6C5CE7] shadow-[0_0_0_5px_rgba(108,92,231,0.15)] transition-transform duration-200 group-hover:scale-125",
                  }),
                  h.flag
                    ? d.jsxs("span", {
                        className:
                          "pointer-events-none absolute bottom-[170%] left-1/2 flex -translate-x-1/2 items-center gap-1.5 whitespace-nowrap rounded-lg bg-[#17123A] px-2.5 py-1.5 text-[11.5px] font-semibold text-white shadow-lg shadow-[#17123A]/30",
                        children: [
                          d.jsx("span", {
                            className: "h-2 w-2 rounded-full bg-[#E23A45]",
                          }),
                          h.name,
                          d.jsx("span", {
                            "aria-hidden": "true",
                            className:
                              "absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-[#17123A]",
                          }),
                        ],
                      })
                    : d.jsx("span", {
                        className:
                          "pointer-events-none absolute bottom-[170%] left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-[#17123A] px-2 py-1 text-[10.5px] font-semibold text-white opacity-0 shadow-lg transition-opacity duration-200 group-hover:opacity-100",
                        children: h.name,
                      }),
                ],
              },
              h.name,
            ),
          ),
        ],
      }),
    ],
  });
}
function Jr() {
  const [h, E] = ql.useState(!1);
  return d.jsxs("div", {
    className: "bg-app min-h-screen p-3 font-sans text-[#191345] sm:p-5 lg:p-7",
    children: [
      d.jsx("div", {
        "aria-hidden": "true",
        className: "dots-layer pointer-events-none fixed inset-0",
      }),
      d.jsxs("div", {
        className:
          "relative mx-auto flex max-w-[1760px] overflow-hidden rounded-[26px] bg-[#F1F2F8] shadow-[0_44px_100px_-32px_rgba(38,26,110,0.6)] ring-1 ring-white/25",
        children: [
          d.jsx(Ar, { open: h, onClose: () => E(!1) }),
          d.jsxs("main", {
            className: "flex min-w-0 flex-1 flex-col gap-5 p-4 sm:p-5",
            children: [
              d.jsx(_r, { onMenu: () => E(!0) }),
              d.jsxs("div", {
                className: "dash-grid",
                children: [
                  d.jsx(Na, {
                    delay: 0,
                    className: "ga-stats h-full",
                    children: d.jsx(jr, {}),
                  }),
                  d.jsx(Na, {
                    delay: 90,
                    className: "ga-rev h-full",
                    children: d.jsx(Br, {}),
                  }),
                  d.jsx(Na, {
                    delay: 140,
                    className: "ga-ship h-full",
                    children: d.jsx(Rr, {}),
                  }),
                  d.jsx(Na, {
                    delay: 200,
                    className: "ga-prof h-full",
                    children: d.jsx(Xr, {}),
                  }),
                  d.jsx(Na, {
                    delay: 260,
                    className: "ga-grow self-end",
                    children: d.jsx(Qr, {}),
                  }),
                  d.jsx(Na, {
                    delay: 320,
                    className: "ga-map h-full",
                    children: d.jsx(Kr, {}),
                  }),
                ],
              }),
            ],
          }),
        ],
      }),
    ],
  });
}
wh.createRoot(document.getElementById("root")).render(
  d.jsx(ql.StrictMode, { children: d.jsx(Jr, {}) }),
);
