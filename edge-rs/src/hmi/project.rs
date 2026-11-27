//! Writes the layout as a Robu HMI Editor project (`.hmi`): base64-encoded
//! JSON. The attribute names and their order were taken from a project saved
//! by the editor itself.
//!
//! Open the file in the editor and choose Generate Output to get the `.tft`.

use super::layout::{Kind, Layout, Widget, PAGES};
use std::fmt::Write;

/// RGB565, written as the editor does: five decimal digits.
const fn rgb(r: u8, g: u8, b: u8) -> u16 {
    ((r as u16 >> 3) << 11) | ((g as u16 >> 2) << 5) | (b as u16 >> 3)
}

const BACKGROUND: u16 = rgb(11, 15, 20);
const TEXT: u16 = rgb(230, 237, 243);
const ACCENT: u16 = rgb(240, 136, 62);
const BUTTON: u16 = rgb(35, 134, 54);
const NAV: u16 = rgb(31, 79, 143);
const WHITE: u16 = rgb(255, 255, 255);

/// Editor font sizes: 0 small, 1 medium. Narrow fields need the small one.
fn font(widget: &Widget) -> u8 {
    match widget.kind {
        Kind::Field { maxl } if usize::from(widget.w) < maxl * 10 => 0,
        _ => 1,
    }
}

fn colour(value: u16) -> String {
    format!("{value:05}")
}

fn three(value: impl Into<usize>) -> String {
    format!("{:03}", value.into())
}

/// The editor's name for the widget and its attributes, in the editor's order.
fn attributes(w: &Widget) -> (&'static str, Vec<(&'static str, String)>) {
    let mut a = vec![
        ("type", three(w.type_code())),
        ("id", three(w.id)),
        ("vscope", "0".to_string()),
    ];
    // value1 = value2 = 1, so that every tap sends a non-zero event.
    let touch = |a: &mut Vec<(&'static str, String)>, to: Option<u16>| {
        a.push(("value1", "1".into()));
        a.push(("value2", "1".into()));
        a.push(("page_switch", u8::from(to.is_some()).to_string()));
        a.push(("next_page", three(to.unwrap_or(0))));
    };
    let text = |a: &mut Vec<(&'static str, String)>, maxl: usize, txt: Option<&str>| {
        a.push(("font", font(w).to_string()));
        a.push(("txt_maxl", three(maxl)));
        if let Some(txt) = txt {
            a.push(("txt", txt.to_string()));
        }
        a.push(("style", "0".into()));
    };
    let name = match &w.kind {
        Kind::Field { maxl } => {
            a.push(("b_fill", "0".into()));
            a.push(("b_col", colour(BACKGROUND)));
            a.push(("p_col", colour(TEXT)));
            text(&mut a, *maxl, None);
            "RealTimeText"
        }
        Kind::Label { text: label } => {
            a.push(("b_fill", "0".into()));
            a.push(("b_col", colour(BACKGROUND)));
            a.push(("p_col", colour(ACCENT)));
            text(&mut a, label.len(), Some(label));
            "Text"
        }
        Kind::Button { text: label } | Kind::Nav { text: label, .. } => {
            let to = match w.kind {
                Kind::Nav { to, .. } => Some(to),
                _ => None,
            };
            let fill = if to.is_some() { NAV } else { BUTTON };
            a.push(("b_fill", "0".into()));
            a.push(("b_col", colour(fill)));
            a.push(("b_col2", colour(fill)));
            a.push(("p_col", colour(WHITE)));
            a.push(("p_col2", colour(WHITE)));
            text(&mut a, label.len(), Some(label));
            touch(&mut a, to);
            "RectButton"
        }
        Kind::Hotspot => {
            touch(&mut a, None);
            "Hotspot"
        }
    };
    a.push(("x", three(w.x)));
    a.push(("y", three(w.y)));
    a.push(("w", three(w.w)));
    a.push(("h", three(w.h)));
    (name, a)
}

fn object(fields: &[(&str, String)]) -> String {
    let body: Vec<_> = fields
        .iter()
        .map(|(key, value)| format!("      \"{key}\": {}", quoted(value)))
        .collect();
    format!("{{\n{}\n    }}", body.join(",\n"))
}

fn quoted(text: &str) -> String {
    serde_json::Value::from(text).to_string()
}

/// The project as JSON, widgets in the order they are drawn.
pub fn json(layout: &Layout) -> String {
    let mut pages = Vec::new();
    for page in 0..PAGES.len() {
        let background = object(&[
            ("type", "000".into()),
            ("id", three(page)),
            ("b_fill", "0".into()),
            ("b_col", colour(BACKGROUND)),
        ]);
        let mut entries = vec![format!("    \"page\": {background}")];
        for w in layout
            .widgets
            .iter()
            .filter(|w| usize::from(w.page) == page)
        {
            let (name, fields) = attributes(w);
            entries.push(format!("    \"{name}_{}\": {}", w.id, object(&fields)));
        }
        pages.push(format!("  \"{page}\": {{\n{}\n  }}", entries.join(",\n")));
    }
    // Portrait, 320x480.
    let settings = object(&[("orientation", "0".into()), ("resolution", "1".into())]);
    let mut out = String::new();
    let _ = write!(
        out,
        "{{\n{},\n  \"-1\": {{\n    \"attributes\": {settings}\n  }}\n}}",
        pages.join(",\n")
    );
    out
}

fn base64(data: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let mut block = [0u8; 3];
        block[..chunk.len()].copy_from_slice(chunk);
        let bits = u32::from_be_bytes([0, block[0], block[1], block[2]]);
        for i in 0..4 {
            if i <= chunk.len() {
                out.push(TABLE[(bits >> (18 - 6 * i)) as usize & 63] as char);
            } else {
                out.push('=');
            }
        }
    }
    out
}

/// The bytes of the `.hmi` file.
pub fn file(layout: &Layout) -> String {
    base64(json(layout).replace('\n', "\r\n").as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64_matches_the_standard_vectors() {
        for (plain, encoded) in [
            ("", ""),
            ("f", "Zg=="),
            ("fo", "Zm8="),
            ("foo", "Zm9v"),
            ("foobar", "Zm9vYmFy"),
        ] {
            assert_eq!(base64(plain.as_bytes()), encoded);
        }
    }

    #[test]
    fn every_widget_is_written_with_the_id_the_daemon_uses() {
        let layout = Layout::new();
        let project: serde_json::Value = serde_json::from_str(&json(&layout)).unwrap();
        let mut count = 0;
        for w in &layout.widgets {
            let (name, _) = attributes(w);
            let entry = &project[w.page.to_string()][format!("{name}_{}", w.id)];
            assert_eq!(entry["type"], format!("{:03}", w.type_code()), "{}", w.name);
            assert_eq!(entry["id"], format!("{:03}", w.id), "{}", w.name);
            count += 1;
        }
        let written: usize = (0..PAGES.len())
            .map(|p| project[p.to_string()].as_object().unwrap().len() - 1)
            .sum();
        assert_eq!(written, count);
        assert_eq!(project["0"]["RectButton_3"]["next_page"], "003");
        assert_eq!(project["1"]["Hotspot_0"]["value1"], "1");
    }
}
