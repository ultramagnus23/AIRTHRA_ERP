//! Single source of truth for the 320x480 portrait screen. The same list
//! drives the daemon and generates the build sheet used in Robu's HMI Editor.
//!
//! The editor numbers widgets per page and per type in the order they are
//! added, starting at 000. IDs here are assigned the same way, so widgets must
//! be added in the editor in the order listed.

use super::protocol::{TYPE_HOTSPOT, TYPE_REALTIME_TEXT, TYPE_SQUARE_BUTTON};
use std::collections::HashMap;
use std::fmt::Write;

pub const WIDTH: u16 = 320;
pub const HEIGHT: u16 = 480;
pub const PAGE_LIVE: u16 = 0;
pub const PAGE_WIFI: u16 = 1;
pub const PAGE_KEYS: u16 = 2;
pub const PAGE_STATUS: u16 = 3;
pub const PAGES: [&str; 4] = [
    "Live readings",
    "Wi-Fi networks",
    "Wi-Fi password",
    "Pi status",
];

pub const LIVE_ROWS: usize = 8;
pub const WIFI_ROWS: usize = 6;
pub const KEY_SLOTS: usize = 20;
pub const LOG_ROWS: usize = 6;
/// Fields side by side on one event line (12 characters each).
pub const LOG_COLS: usize = 3;
/// Status page rows: field name and the fixed label beside it.
const STATS: [(&str, &str); 8] = [
    ("s_cloud", "CLOUD"),
    ("s_sent", "SENT"),
    ("s_queued", "QUEUED"),
    ("s_last", "LAST SEND"),
    ("s_recorded", "RECORDED"),
    ("s_sensors", "SENSORS"),
    ("s_clock", "PI CLOCK"),
    ("s_uptime", "UPTIME"),
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Kind {
    /// Text the Pi writes (RealTimeText).
    Field { maxl: usize },
    /// Fixed label drawn by the screen (Text).
    Label { text: &'static str },
    /// SquareButton that sends an event to the Pi.
    Button { text: &'static str },
    /// Invisible touch area (Hotspot) that sends an event to the Pi.
    Hotspot,
    /// SquareButton that changes page on the screen itself.
    Nav { text: &'static str, to: u16 },
}

#[derive(Clone, Debug)]
pub struct Widget {
    pub name: String,
    pub page: u16,
    pub id: u16,
    pub kind: Kind,
    pub x: u16,
    pub y: u16,
    pub w: u16,
    pub h: u16,
}

impl Widget {
    pub fn type_code(&self) -> u16 {
        match self.kind {
            Kind::Field { .. } => TYPE_REALTIME_TEXT,
            Kind::Label { .. } => 2,
            Kind::Button { .. } | Kind::Nav { .. } => TYPE_SQUARE_BUTTON,
            Kind::Hotspot => TYPE_HOTSPOT,
        }
    }
}

pub struct Layout {
    pub widgets: Vec<Widget>,
    next_id: HashMap<(u16, u16), u16>,
}

impl Default for Layout {
    fn default() -> Self {
        Self::new()
    }
}

impl Layout {
    fn add(&mut self, page: u16, name: impl Into<String>, kind: Kind, rect: [u16; 4]) {
        let [x, y, w, h] = rect;
        let mut widget = Widget {
            name: name.into(),
            page,
            id: 0,
            kind,
            x,
            y,
            w,
            h,
        };
        let slot = self.next_id.entry((page, widget.type_code())).or_insert(0);
        widget.id = *slot;
        *slot += 1;
        self.widgets.push(widget);
    }

    fn field(&mut self, page: u16, name: impl Into<String>, maxl: usize, rect: [u16; 4]) {
        self.add(page, name, Kind::Field { maxl }, rect);
    }

    pub fn new() -> Self {
        let mut l = Layout {
            widgets: Vec::new(),
            next_id: HashMap::new(),
        };

        // Page 0: live readings.
        let p = PAGE_LIVE;
        l.add(p, "title", Kind::Label { text: "AIRTHRA" }, [8, 6, 90, 22]);
        l.field(p, "cloud", 12, [100, 6, 110, 22]);
        l.field(p, "pageno", 7, [230, 6, 82, 22]);
        l.field(p, "net", 12, [8, 30, 150, 20]);
        l.field(p, "alert", 12, [162, 30, 150, 20]);
        for i in 0..LIVE_ROWS {
            let y = 56 + i as u16 * 45;
            l.field(p, format!("name{i}"), 12, [4, y, 130, 40]);
            l.field(p, format!("value{i}"), 9, [138, y, 100, 40]);
            l.field(p, format!("state{i}"), 8, [242, y, 74, 40]);
        }
        l.add(p, "prev", Kind::Button { text: "< PREV" }, [4, 424, 75, 52]);
        l.add(
            p,
            "next",
            Kind::Button { text: "NEXT >" },
            [83, 424, 75, 52],
        );
        l.add(
            p,
            "to_wifi",
            Kind::Nav {
                text: "WI-FI",
                to: PAGE_WIFI,
            },
            [162, 424, 75, 52],
        );
        l.add(
            p,
            "to_status",
            Kind::Nav {
                text: "STATUS",
                to: PAGE_STATUS,
            },
            [241, 424, 75, 52],
        );

        // Page 1: networks.
        let p = PAGE_WIFI;
        l.add(p, "wtitle", Kind::Label { text: "WI-FI" }, [8, 6, 60, 22]);
        l.field(p, "current", 12, [72, 6, 150, 22]);
        l.field(p, "ip_a", 12, [72, 30, 150, 20]);
        l.field(p, "ip_b", 3, [222, 30, 40, 20]);
        l.field(p, "wmsg", 12, [8, 52, 304, 22]);
        for i in 0..WIFI_ROWS {
            let y = 80 + i as u16 * 48;
            l.field(p, format!("ssid{i}"), 12, [4, y, 200, 42]);
            l.field(p, format!("sig{i}"), 9, [210, y, 106, 42]);
            l.add(p, format!("pick{i}"), Kind::Hotspot, [0, y, 320, 44]);
        }
        l.add(p, "scan", Kind::Button { text: "SCAN" }, [4, 372, 154, 48]);
        l.add(
            p,
            "more",
            Kind::Button { text: "MORE" },
            [162, 372, 154, 48],
        );
        l.add(
            p,
            "to_live",
            Kind::Nav {
                text: "< LIVE",
                to: PAGE_LIVE,
            },
            [4, 426, 154, 50],
        );
        l.add(
            p,
            "to_keys",
            Kind::Nav {
                text: "PASSWORD >",
                to: PAGE_KEYS,
            },
            [162, 426, 154, 50],
        );

        // Page 2: password keypad.
        let p = PAGE_KEYS;
        for i in 0..3u16 {
            l.field(p, format!("target{i}"), 12, [4 + i * 105, 4, 102, 20]);
        }
        l.field(p, "pass0", 12, [4, 28, 154, 24]);
        l.field(p, "pass1", 12, [162, 28, 154, 24]);
        l.field(p, "kmsg", 12, [4, 56, 200, 20]);
        l.field(p, "count", 7, [230, 56, 86, 20]);
        for i in 0..KEY_SLOTS as u16 {
            let (x, y) = (4 + (i % 4) * 79, 80 + (i / 4) * 58);
            l.field(p, format!("key{i}"), 3, [x + 18, y + 14, 40, 24]);
            l.add(p, format!("tap{i}"), Kind::Hotspot, [x, y, 75, 54]);
        }
        l.add(
            p,
            "layer",
            Kind::Button { text: "ABC/123" },
            [4, 372, 102, 48],
        );
        l.add(
            p,
            "del",
            Kind::Button { text: "DELETE" },
            [109, 372, 102, 48],
        );
        l.add(
            p,
            "clear",
            Kind::Button { text: "CLEAR" },
            [214, 372, 102, 48],
        );
        l.add(
            p,
            "back",
            Kind::Nav {
                text: "< BACK",
                to: PAGE_WIFI,
            },
            [4, 426, 102, 50],
        );
        l.add(
            p,
            "show",
            Kind::Button { text: "SHOW" },
            [109, 426, 102, 50],
        );
        l.add(
            p,
            "join",
            Kind::Button { text: "JOIN" },
            [214, 426, 102, 50],
        );

        // Page 3: what the Pi is doing.
        let p = PAGE_STATUS;
        l.add(
            p,
            "stitle",
            Kind::Label { text: "PI STATUS" },
            [8, 6, 120, 22],
        );
        for (i, (name, text)) in STATS.into_iter().enumerate() {
            let y = 34 + i as u16 * 24;
            l.add(
                p,
                format!("{name}_label"),
                Kind::Label { text },
                [8, y, 120, 20],
            );
            l.field(p, name, 12, [140, y, 176, 20]);
        }
        let heading = Kind::Label {
            text: "EVENTS (UTC)",
        };
        l.add(p, "etitle", heading, [8, 230, 160, 20]);
        for row in 0..LOG_ROWS {
            for col in 0..LOG_COLS {
                // 12 characters of the 8-pixel font, edge to edge, so a word split
                // across two fields still reads as one.
                let (x, y) = (16 + col as u16 * 96, 256 + row as u16 * 27);
                l.field(p, format!("log{row}_{col}"), 12, [x, y, 96, 22]);
            }
        }
        l.add(
            p,
            "status_back",
            Kind::Nav {
                text: "< LIVE",
                to: PAGE_LIVE,
            },
            [4, 426, 312, 50],
        );
        l
    }

    /// The Pi-facing widget that sent `(page, type, id)`.
    pub fn touched(&self, page: u16, type_code: u16, id: u16) -> Option<&Widget> {
        self.widgets.iter().find(|w| {
            w.page == page
                && w.id == id
                && w.type_code() == type_code
                && !matches!(w.kind, Kind::Field { .. } | Kind::Label { .. })
        })
    }

    pub fn get(&self, name: &str) -> Option<&Widget> {
        self.widgets.iter().find(|w| w.name == name)
    }

    /// Markdown build sheet for the editor.
    pub fn build_sheet(&self) -> String {
        let mut out = String::new();
        out.push_str(
            "<!-- Generated by `airthra-edge hmi-layout`. Do not edit by hand. -->\n\n\
             # Screen build sheet (SmartElex Basic 4.0\", Robu HMI Editor)\n\n\
             New project: Basic, `SME40_480320RT` (320x480), orientation `0` (portrait). \
             Add four pages. On each page add the widgets **in the order listed**, because \
             the editor assigns IDs in that order. Check the `id` it shows against the table.\n\n\
             - **RealTimeText**: set `txt_maxl` exactly as listed. Font 1 (use 0 if clipped).\n\
             - **SquareButton (to Pi)**: `value1`=1, `value2`=1, `page_switch`=0, \
             `b_col2` the same as `b_col`.\n\
             - **SquareButton (page)**: `page_switch`=1 and `next_page` as listed.\n\
             - **Hotspot**: `value1`=1, `value2`=1, `page_switch`=0. Add it after the text under it.\n",
        );
        for (page, title) in PAGES.iter().enumerate() {
            let _ = write!(
                out,
                "\n## Page {page}: {title}\n\n\
                 | # | Widget | id | Name | x | y | w | h | Settings |\n\
                 |---|---|---|---|---|---|---|---|---|\n"
            );
            let on_page = self.widgets.iter().filter(|w| usize::from(w.page) == page);
            for (n, w) in on_page.enumerate() {
                let (tool, settings) = match &w.kind {
                    Kind::Field { maxl } => ("RealTimeText", format!("txt_maxl={maxl}")),
                    Kind::Label { text } => ("Text", format!("txt=`{text}`")),
                    Kind::Button { text } => ("SquareButton (to Pi)", format!("txt=`{text}`")),
                    Kind::Hotspot => ("Hotspot", String::new()),
                    Kind::Nav { text, to } => (
                        "SquareButton (page)",
                        format!("txt=`{text}`, next_page={to:03}"),
                    ),
                };
                let _ = writeln!(
                    out,
                    "| {} | {tool} | {:03} | {} | {} | {} | {} | {} | {settings} |",
                    n + 1,
                    w.id,
                    w.name,
                    w.x,
                    w.y,
                    w.w,
                    w.h
                );
            }
        }
        out
    }

    /// Draws the pages side by side, with `values` in the text fields.
    pub fn preview_svg(&self, values: &HashMap<String, String>) -> String {
        const GAP: u16 = 24;
        let pages = PAGES.len() as u16;
        let total = WIDTH * pages + GAP * (pages + 1);
        let mut out = format!(
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{total}\" height=\"{}\" \
             viewBox=\"0 0 {total} {}\" font-family=\"monospace\" font-size=\"15\">\
             <rect width=\"100%\" height=\"100%\" fill=\"#d0d4d9\"/>",
            HEIGHT + GAP * 2,
            HEIGHT + GAP * 2
        );
        for page in 0..pages {
            let ox = GAP + page * (WIDTH + GAP);
            let _ = write!(
                out,
                "<text x=\"{ox}\" y=\"17\" fill=\"#111\">Page {page}: {}</text>\
                 <rect x=\"{ox}\" y=\"{GAP}\" width=\"{WIDTH}\" height=\"{HEIGHT}\" fill=\"#0b0f14\"/>",
                PAGES[usize::from(page)]
            );
            for w in self.widgets.iter().filter(|w| w.page == page) {
                let (x, y) = (ox + w.x, GAP + w.y);
                let (text, fill, colour) = match &w.kind {
                    Kind::Field { .. } => (
                        values.get(&w.name).cloned().unwrap_or_default(),
                        "none",
                        "#e6edf3",
                    ),
                    Kind::Label { text } => (text.to_string(), "none", "#f0883e"),
                    Kind::Button { text } => (text.to_string(), "#238636", "#fff"),
                    Kind::Nav { text, .. } => (text.to_string(), "#1f4f8f", "#fff"),
                    Kind::Hotspot => (String::new(), "none", "none"),
                };
                let stroke = if w.kind == Kind::Hotspot {
                    "#30363d"
                } else {
                    "none"
                };
                let _ = write!(
                    out,
                    "<rect x=\"{x}\" y=\"{y}\" width=\"{}\" height=\"{}\" fill=\"{fill}\" stroke=\"{stroke}\"/>",
                    w.w, w.h
                );
                if !text.is_empty() {
                    let escaped = text
                        .replace('&', "&amp;")
                        .replace('<', "&lt;")
                        .replace('>', "&gt;");
                    let _ = write!(
                        out,
                        "<text x=\"{}\" y=\"{}\" fill=\"{colour}\" xml:space=\"preserve\">{escaped}</text>",
                        x + 3,
                        y + w.h / 2 + 5
                    );
                }
            }
        }
        out.push_str("</svg>\n");
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names_unique_ids_unique_and_everything_on_screen() {
        let l = Layout::new();
        let mut names = std::collections::HashSet::new();
        let mut keys = std::collections::HashSet::new();
        for w in &l.widgets {
            assert!(names.insert(w.name.clone()), "duplicate {}", w.name);
            assert!(keys.insert((w.page, w.type_code(), w.id)));
            assert!(
                w.x + w.w <= WIDTH && w.y + w.h <= HEIGHT,
                "{} off screen",
                w.name
            );
            if let Kind::Field { maxl } = w.kind {
                assert!((3..=12).contains(&maxl));
            }
        }
    }

    #[test]
    fn page_buttons_share_the_square_button_id_sequence() {
        let l = Layout::new();
        assert_eq!(l.get("prev").unwrap().id, 0);
        assert_eq!(l.get("to_wifi").unwrap().id, 2);
        assert_eq!(l.get("show").unwrap().id, 4);
        // Added after `to_wifi`, so the earlier live-page IDs did not move.
        assert_eq!(l.get("to_status").unwrap().id, 3);
    }
}
