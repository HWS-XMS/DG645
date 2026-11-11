# DG645 library — resources & notes

Collected 2026-11-06 for the requirements analysis. Nothing here is a
dependency of our library; all of it is reference material.

## Contents of `resources/`

| Item | What it is | Source |
|---|---|---|
| `../documents/DG645_manual.pdf` | Official operation manual. Remote programming chapter starts p. 41 (command list p. 48, status bytes p. 60, error codes p. 62) | SRS |
| `DG645_manual.txt` | Text extracted from the PDF (`pdftotext -layout`) so it can be searched | generated |
| `srsinst.dg645/` | Official SRS Python driver, v0.1.0, MIT (latest commit `82a13f8`, 2026-04-03) | https://github.com/thinkSRS/srsinst.dg645 |
| `srsgui/` | SRS instrument/GUI framework the official driver is built on, v0.4.6 (latest commit `ba810d5`, 2024-08-30) | https://github.com/thinkSRS/srsgui |

Where to look in the official code:
- Command definitions: `srsinst.dg645/srsinst/dg645/instruments/components.py`
- Name/index tables: `srsinst.dg645/srsinst/dg645/instruments/keys.py`
- How commands are sent and replies parsed: `srsgui/srsgui/inst/commands.py`, `indexcommands.py`
- Serial I/O: `srsgui/srsgui/inst/communications/serialinterface.py`

External docs (not downloaded):
- pyserial: https://pyserial.readthedocs.io/ (current release 3.5)

## RS-232 facts (manual pp. 42, 44–45)

- Connector: DB-9 **female**, wired as **DCE** (TX on pin 3, RX on pin 2), so use a
  **straight-through** cable, not a null-modem cable.
- Fixed: 8 data bits, no parity, 1 stop bit, **RTS/CTS hardware flow control**.
- Baud: 4800 / 9600 (default) / 19200 / 38400 / 57600 / 115200. Change it on the front
  panel (SHIFT, RS232) or with `IFCF 1,<baud>`; it takes effect after an interface
  reset (`IFRS 0`) or a power cycle.
- On a Mac you need a USB-serial adapter that passes RTS/CTS through. FTDI-based adapters
  do; some cheap PL2303 clones don't.
- `REMT` / `LCAL` (front-panel lockout / back to local) **only work on RS-232 and
  telnet**, so they matter for us.

## Protocol facts (manual pp. 44–45)

- ASCII, 4-letter mnemonics (`*` + 3 letters for IEEE-488.2), case-insensitive.
- Commands end with `;`, CR or LF. Replies end with CR LF by default (`XTRM`).
- Set commands produce **no reply**. Errors must be fetched with `LERR?` (one per
  call, 0 = none; queue holds 20, code 254 = overflow) or `*ESR?` (bits CME/EXE).
- Command buffer 255 bytes, at most 3 parameters of 25 bytes each. Overflow flushes
  the I/O buffers.
- Example delay reply: `DLAY?3` → `2,+0.001000000000` (reference channel, seconds).

## Errors in the manual

- `HOLD?{t}` and `SHDP?{i}` are almost certainly meant to read `(?)` (both set and query).
- `*SAV`: the list of saved settings just says "TODO".
- `IFCF`: the text says "parameters 10–12 require an IP address", but its own table puts them at 11–13.
- `EPHY` example shows `EPHYS0,0` (stray "S").
- The status byte and ESR sections mention the "CG635" (copied from another manual).
- The status byte table (p. 60) defines bit 2 = BURST, while the `*STB?` command
  description (p. 49) lists bit 2 as reserved.
- Prescale (`PRES`/`PHAS`) and holdoff (`HOLD`) are only available with advanced triggering on (`ADVT 1`, manual pp. 23–24).

## Observations on the official driver

- It connects over serial **without** hardware flow control by default
  (`srsgui` `SerialInterface.connect(..., hardware_flow_control=False)`), although the
  manual says RTS/CTS is fixed. This needs checking against the real instrument.
- `srsgui` reads serial replies one byte at a time until LF.
- API style: `dg.delays.delay['B']['A'] = 500e-9`, with components `trigger`, `burst`,
  `delays`, `outputs`, `status`, `system`, `display`, `network`, `interface`.
- Its tests (`srsinst.dg645/tests/`) need a real instrument (see `conftest.py`).

## To find out from the instrument

- `*IDN?` → model, serial number, firmware version.
- `TIMB?` → installed timebase (internal / OCXO / Rb / external).
- Rear-panel output option installed?
- Configured baud rate.

## Decisions so far

- Our own standalone library; the official one is reference only.
- Communication: RS-232 via **pyserial**, with RTS/CTS hardware flow control (`rtscts=True`), as the manual specifies.
- No GUI for now.

## To verify on the instrument (assumptions in `src/dg645/api.py`)

- `DISP?` reply assumed to be `i,c` (not shown in the manual).
- `IFCF?11..13` reply assumed to be a plain `a.b.c.d`; `EMAC?` returned as a raw string.
- Burst period upper limit: p. 55 says 2000 s − 10 ns, specs p. viii say 42.9 s. The API allows the looser one.
- Trigger holdoff upper limit is not documented; the API only rejects negative values.
- `*STB?` bit 2 (BURST vs. reserved).
- The API restricts `SPDL`/`SSDL`/`LINK?` to channels A–H (T0/T1 are predefined, p. 27); check the instrument agrees.
- Duration of `*TST?` and `*CAL?` (not in the manual). Default timeout 300 s, taken from srsinst's tests for `*CAL?`; shorten once measured.
- Whether `*STB?` is answered while `*TST?`/`*CAL?` run. Expected not: on RS-232 it is an ordinary queued command (serial poll is GPIB only).
- `HOLD`/`PRES`/`PHAS` while `ADVT 0`: stored for later, or error 11 (Illegal Mode)? The DDG refuses them either way.
- Read-back of trigger level and holdoff: no resolution documented, so with `verify=True` a value the instrument rounds will raise `DG645VerificationError`.
- Whether `*TST?` (which resets to defaults, p. 35) also drops `LOCK?`/`REMT`. The DDG runs it before locking.

## Comparison with srsinst.dg645 (2026-11-07)

Same 70 commands; same meaning for every index, enum value and status bit
(incl. STB bit 2 = BURST). Both assume `DISP?` returns `i,c`. Both write
status registers as full bytes (theirs notes bit-indexed forms time out).

Wire-format differences (ours follows the manual's examples literally):
- Queries: theirs `DLAY? 3`, ours `DLAY?3`.
- Indexed sets: theirs `LAMP 1,  3.5` (comma + two spaces), ours `LAMP 1,3.50`.
- `XTRM`: theirs always 3 values, ours 1–3 as documented.
- Serial: theirs RTS/CTS off by default, ours on.

Bug in theirs: `DLAY` is formatted with `{:e}` → 7 significant digits,
e.g. 123.456789125 s is sent as `1.234568e+02` (≈ 11 µs off).

Their min/max values are GUI metadata, not enforced, and several differ from
the manual: TRAT 1 mHz–1 MHz (manual 100 µHz–10 MHz), LOFF ±3 V (±2 V),
PRES ≤ 2^31−1 (2^30−1 trigger / 2^16−1 outputs), PHAS ≤ 2^31−2 (2^16−2),
BURC ≤ 2^31−1 (2^32−1), level steps 0.001 V (0.01 V). We keep the manual's values.

## Calibration commands outside the command index

The calibration chapter (pp. 73–76) documents `CALT(?)0{,i}` (timebase cal byte)
and `CALL(?)i{,j}` (output level cal bytes), which are not among the 70 indexed
commands. They change factory calibration data and are deliberately not implemented.

## DigitalDelayGenerator decisions (2026-11-07)

- Every set is followed by `LERR?` until empty; entries raise `DG645InstrumentError`.
- Read-back optional at construction (`verify=True`), compared with the rounded value sent.
- Connect: `*IDN?` (model must be DG645), `*CLS`, optional `*TST?`, `LOCK?`, `REMT`.
  Close: `UNLK?`, `LCAL`, close port.
- Advanced triggering is never switched implicitly; holdoff/prescale/phase setters
  raise `DG645ModeError` while it is off (switching it on activates stored values).
- One reentrant lock per instrument; "set, check errors, read back" is atomic.
- Timeouts: 1 s default; `*TST?`/`*CAL?` 300 s; `*OPC?` optional; input buffer
  flushed before every query so a late reply cannot shift later replies.
