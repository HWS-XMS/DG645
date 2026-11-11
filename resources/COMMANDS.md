# DG645 — complete remote command list

Source: DG645 manual, Remote Programming chapter (pp. 46–59). Checked against the
official driver `srsinst.dg645` (components.py): both contain the same **70 commands**.

**Form:** S = set only, Q = query only, S/Q = both.
**Syntax:** `{}` = only when setting, `[]` = optional, `(?)` = query form optional.
**Parameters:** `i,j,k` integer · `t` time [s] · `f` frequency [Hz] · `v` voltage [V] ·
`c,d` delay channel (0 T0, 1 T1, 2 A, 3 B, 4 C, 5 D, 6 E, 7 F, 8 G, 9 H) ·
`b` output (0 T0, 1 AB, 2 CD, 3 EF, 4 GH).
Step commands: direction `i` = 1 up, 0 down, by the current step size.

## 1. IEEE-488.2 common commands (15)

| Command | Form | Function | Parameters / reply | Page |
|---|---|---|---|---|
| `*CAL?` | Q | Run auto calibration | 0 = OK, 17 = failed | 48 |
| `*CLS` | S | Clear status | clears ESR, INSR, error queue | 48 |
| `*ESE(?){i}` | S/Q | Standard event status enable | bit mask | 48 |
| `*ESR?` | Q | Standard event status register | bits: 0 OPC, 2 QYE, 3 DDE, 4 EXE, 5 CME, 7 PON; cleared on read | 48 |
| `*IDN?` | Q | Identification | `Stanford Research Systems,DG645,s/n…,ver…` | 48 |
| `*OPC(?)` | S/Q | Operation complete | set: OPC bit in ESR; query: returns 1 | 48 |
| `*PSC(?){i}` | S/Q | Power-on status clear | 0 = keep SRE/ESE through power cycle, 1 = clear | 49 |
| `*RCL i` | S | Recall settings | i = 0–9 (0 = factory defaults) | 49 |
| `*RST` | S | Reset to defaults | = `*RCL 0` | 49 |
| `*SAV i` | S | Save settings | i = 1–9 | 49 |
| `*SRE(?){i}` | S/Q | Service request enable | bit mask | 49 |
| `*STB?` | Q | Status byte | bits: 0 INSB, 1 BUSY, 2 BURST*, 4 MAV, 5 ESB, 6 MSS | 49 |
| `*TRG` | S | Trigger | single shot: fire; ext. single shot: arm | 50 |
| `*TST?` | Q | Self test | 0 = OK, 16 = failed | 50 |
| `*WAI` | S | Wait until prior commands done | — | 50 |

\* bit 2 is "reserved" on p. 49 but "BURST" on p. 60.

## 2. Status and display (6)

| Command | Form | Function | Parameters / reply | Page |
|---|---|---|---|---|
| `DISP(?){i,c}` | S/Q | Front-panel display | i = 0–14 display type (0 trig rate … 11 channel delay, 12 levels, 13 polarity, 14 burst T0), c = channel | 50 |
| `INSE(?){i}` | S/Q | Instrument status enable | bit mask | 51 |
| `INSR?` | Q | Instrument status register | bits: 0 TRIG, 1 RATE, 2 END_OF_DELAY, 3 END_OF_BURST, 4 INHIBIT, 5 ABORT_DELAY, 6 PLL_UNLOCK, 7 RB_UNLOCK; cleared on read | 51 |
| `LERR?` | Q | Pop last error | error code, 0 = none (queue: 20) | 51 |
| `SHDP(?){i}` | S/Q | Display on/off | 1 on, 0 off (manual writes `SHDP?{i}`) | 51 |
| `TIMB?` | Q | Timebase | 0 internal, 1 OCXO, 2 Rb, 3 external | 51 |

## 3. Trigger (18)

| Command | Form | Function | Parameters / reply | Page |
|---|---|---|---|---|
| `ADVT(?){i}` | S/Q | Advanced triggering | 0 off, 1 on (needed for prescale/holdoff) | 52 |
| `HOLD(?){t}` | S/Q | Trigger holdoff | t [s] (manual writes `HOLD?{t}`) | 52 |
| `INHB(?){i}` | S/Q | Inhibit input behaviour | 0 off, 1 triggers, 2 AB, 3 AB+CD, 4 AB+CD+EF, 5 all | 52 |
| `PHAS(?)i{,j}` | S/Q | Prescale phase | i = 1–4 (AB–GH), j = phase | 52 |
| `PRES(?)i{,j}` | S/Q | Prescale factor | i = 0 trigger, 1–4 AB–GH; j = factor | 53 |
| `SPHD i` | S | Step holdoff | direction | 53 |
| `SPPH i,j` | S | Step prescale phase | i = 1–4, j = direction | 53 |
| `SPPS i,j` | S | Step prescale factor | i = 0–4, j = direction | 53 |
| `SPTL i` | S | Step trigger level | direction | 53 |
| `SPTR i` | S | Step trigger rate | direction | 53 |
| `SSHD(?){t}` | S/Q | Step size holdoff | t [s] | 54 |
| `SSPH(?)i{,j}` | S/Q | Step size prescale phase | i = 1–4 | 54 |
| `SSPS(?)i{,j}` | S/Q | Step size prescale factor | i = 0–4 | 54 |
| `SSTL(?){v}` | S/Q | Step size trigger level | v [V] | 54 |
| `SSTR(?){f}` | S/Q | Step size trigger rate | f [Hz] | 54 |
| `TLVL(?){v}` | S/Q | External trigger level | v [V] | 54 |
| `TRAT(?){f}` | S/Q | Internal trigger rate | f [Hz] | 54 |
| `TSRC(?){i}` | S/Q | Trigger source | 0 internal, 1 ext ↑, 2 ext ↓, 3 single-shot ext ↑, 4 single-shot ext ↓, 5 single shot, 6 line | 54 |

## 4. Burst (11)

| Command | Form | Function | Parameters / reply | Page |
|---|---|---|---|---|
| `BURC(?){i}` | S/Q | Burst count | delay cycles per trigger | 54 |
| `BURD(?){t}` | S/Q | Burst delay | t [s], trigger → first cycle | 55 |
| `BURM(?){i}` | S/Q | Burst mode | 0 off, 1 on | 55 |
| `BURP(?){t}` | S/Q | Burst period | 100 ns … 2000 s − 10 ns, 10 ns steps | 55 |
| `BURT(?){i}` | S/Q | Burst T0 configuration | 0 T0 on every cycle, 1 first cycle only | 55 |
| `SPBC i` | S | Step burst count | direction | 55 |
| `SPBD i` | S | Step burst delay | direction | 55 |
| `SPBP i` | S | Step burst period | direction | 55 |
| `SSBC(?){i}` | S/Q | Step size burst count | integer | 55 |
| `SSBD(?){t}` | S/Q | Step size burst delay | t [s] | 55 |
| `SSBP(?){t}` | S/Q | Step size burst period | t [s] | 55 |

## 5. Delay and output (11)

| Command | Form | Function | Parameters / reply | Page |
|---|---|---|---|---|
| `DLAY(?)c{,d,t}` | S/Q | Delay of channel c = channel d + t | reply `d,t`, e.g. `2,+0.001000000000` | 56 |
| `LAMP(?)b{,v}` | S/Q | Output amplitude | v [V] | 56 |
| `LINK(?)c{,d}` | S/Q | Link channel c to d | c ≠ T0; neither may be T1 | 56 |
| `LOFF(?)b{,v}` | S/Q | Output offset | v [V] | 57 |
| `LPOL(?)b{,i}` | S/Q | Output polarity | 1 positive, 0 negative | 57 |
| `SPDL c,i` | S | Step delay | direction | 57 |
| `SPLA b,i` | S | Step amplitude | direction | 57 |
| `SPLO b,i` | S | Step offset | direction | 57 |
| `SSDL(?)c{,t}` | S/Q | Step size delay | t [s] (manual writes `f`) | 57 |
| `SSLA(?)b{,v}` | S/Q | Step size amplitude | v [V] | 57 |
| `SSLO(?)b{,v}` | S/Q | Step size offset | v [V] | 57 |

## 6. Interface (9)

| Command | Form | Function | Parameters / reply | Page |
|---|---|---|---|---|
| `EMAC?` | Q | Ethernet MAC address | — | 57 |
| `EPHY(?)i{,j}` | S/Q | Ethernet link config | i = 0 auto-negotiation, 1 speed (10/100) | 57 |
| `IFCF(?)i{,j}` | S/Q | Interface configuration | i = 0 RS-232 on, 1 baud, 2 GPIB on, 3 GPIB addr, 4 TCP/IP, 5 DHCP, 6 Auto-IP, 7 static IP, 8 raw socket, 9 telnet, 10 VXI-11, 11 IP, 12 netmask, 13 gateway | 58 |
| `IFRS i` | S | Interface reset | 0 RS-232, 1 GPIB, 2 LAN | 58 |
| `LCAL` | S | Back to local (front panel on) | RS-232 and telnet only | 59 |
| `LOCK?` | Q | Request instrument lock | 1 granted, 0 not | 59 |
| `REMT` | S | Remote (front panel locked) | raw socket, telnet, RS-232 only | 59 |
| `UNLK?` | Q | Release lock | 1 released, 0 not | 59 |
| `XTRM i{,j,k}` | S | Response terminator | ASCII codes, default 13,10 | 59 |

## Not listed

The DG645 also accepts a **subset of the DG535 command set** (manual p. 68). The
manual doesn't list those commands; it only describes how DG535 outputs map onto
DG645 outputs. They are not relevant for a native DG645 library.
