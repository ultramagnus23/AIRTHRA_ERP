//! UART protocol of the SmartElex "Basic" HMI, as described in Robu's HMI
//! Editor User Manual V1.0. It is NOT the Nextion protocol.
//!
//! Host to screen:  P<page:3>T<type:3>I<id:3>V<value:12>
//! Screen to host:  the same shape, sent when a button or hotspot is used.
//!
//! The value is the text padded to the widget's `txt_maxl`, then filled with
//! '0' up to 12 bytes. The manual gives no line terminator for host frames.

pub const TYPE_REALTIME_TEXT: u16 = 1;
pub const TYPE_SQUARE_BUTTON: u16 = 4;
pub const TYPE_HOTSPOT: u16 = 11;

pub const VALUE_LEN: usize = 12;
const HEADER_LEN: usize = 13; // P000T000I000V

/// Builds a text update. `text` is cut or space-padded to exactly `maxl`.
/// Non-printable and non-ASCII characters become '?'.
pub fn encode_text(page: u16, id: u16, text: &str, maxl: usize) -> Vec<u8> {
    let maxl = maxl.clamp(3, VALUE_LEN);
    let mut value: String = text
        .chars()
        .map(|c| if (' '..='~').contains(&c) { c } else { '?' })
        .take(maxl)
        .collect();
    while value.len() < maxl {
        value.push(' ');
    }
    while value.len() < VALUE_LEN {
        value.push('0');
    }
    format!("P{page:03}T{TYPE_REALTIME_TEXT:03}I{id:03}V{value}").into_bytes()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Event {
    pub page: u16,
    pub kind: u16,
    pub id: u16,
    pub value: u32,
}

/// Incremental parser. Accepts the manual's fixed 12-digit value
/// ("001000000000", meaning 1) and the shorter newline-terminated form seen in
/// Robu's Arduino example ("V1\n"). Anything else is skipped.
#[derive(Default)]
pub struct Parser {
    buf: Vec<u8>,
}

impl Parser {
    pub fn push(&mut self, bytes: &[u8]) -> Vec<Event> {
        self.buf.extend_from_slice(bytes);
        self.drain(false)
    }

    /// Call when the line has gone quiet: a short value with no terminator is
    /// then complete.
    pub fn flush(&mut self) -> Vec<Event> {
        self.drain(true)
    }

    fn drain(&mut self, idle: bool) -> Vec<Event> {
        let mut events = Vec::new();
        loop {
            match self.buf.iter().position(|&b| b == b'P') {
                Some(start) => {
                    self.buf.drain(..start);
                }
                None => {
                    self.buf.clear();
                    break;
                }
            }
            if self.buf.len() <= HEADER_LEN {
                if idle {
                    self.buf.clear();
                }
                break;
            }
            let Some((page, kind, id)) = header(&self.buf[..HEADER_LEN]) else {
                self.buf.drain(..1);
                continue;
            };
            let digits = self.buf[HEADER_LEN..]
                .iter()
                .take(VALUE_LEN)
                .take_while(|b| b.is_ascii_digit())
                .count();
            let terminated = digits == VALUE_LEN || HEADER_LEN + digits < self.buf.len();
            if !terminated && !idle {
                break; // wait for the rest
            }
            if digits > 0 {
                let significant = if digits == VALUE_LEN { 3 } else { digits };
                let text = &self.buf[HEADER_LEN..HEADER_LEN + significant];
                if let Some(value) = std::str::from_utf8(text).ok().and_then(|s| s.parse().ok()) {
                    events.push(Event {
                        page,
                        kind,
                        id,
                        value,
                    });
                }
            }
            self.buf.drain(..HEADER_LEN + digits);
        }
        events
    }
}

fn header(h: &[u8]) -> Option<(u16, u16, u16)> {
    let number = |tag: u8, at: usize| -> Option<u16> {
        if h[at] != tag || !h[at + 1..at + 4].iter().all(u8::is_ascii_digit) {
            return None;
        }
        std::str::from_utf8(&h[at + 1..at + 4]).ok()?.parse().ok()
    };
    let page = number(b'P', 0)?;
    let kind = number(b'T', 4)?;
    let id = number(b'I', 8)?;
    (h[12] == b'V').then_some((page, kind, id))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encodes_the_manuals_example() {
        assert_eq!(encode_text(0, 0, "24.08", 5), b"P000T001I000V24.080000000");
    }

    #[test]
    fn pads_truncates_and_sanitises() {
        assert_eq!(encode_text(1, 2, "ab", 5), b"P001T001I002Vab   0000000");
        assert_eq!(
            encode_text(1, 2, "abcdefghijklmnop", 12),
            b"P001T001I002Vabcdefghijkl"
        );
        assert_eq!(encode_text(0, 0, "é\n", 3), b"P000T001I000V?? 000000000");
    }

    #[test]
    fn parses_the_manuals_button_example_split_across_reads() {
        let mut p = Parser::default();
        assert!(p.push(b"junkP000T004I0").is_empty());
        let got = p.push(b"00V001000000000");
        assert_eq!(
            got,
            vec![Event {
                page: 0,
                kind: 4,
                id: 0,
                value: 1
            }]
        );
    }

    #[test]
    fn parses_short_terminated_and_idle_forms() {
        let mut p = Parser::default();
        let got = p.push(b"P005T011I001V1\r\nP005T011I001V0\n");
        assert_eq!(got.iter().map(|e| e.value).collect::<Vec<_>>(), vec![1, 0]);
        assert!(p.push(b"P002T011I007V1").is_empty());
        assert_eq!(p.flush()[0].id, 7);
    }

    #[test]
    fn recovers_from_garbage() {
        let mut p = Parser::default();
        let got = p.push(b"PPPxx P00ZT004I000V1 P000T004I003V001000000000");
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].id, 3);
    }
}
