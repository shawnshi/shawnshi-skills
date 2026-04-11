# Sequence Diagram Rules (时序图)

#### Participants (参与者)

Each participant is built from two elements stacked vertically:

1. **Header box** (top): rectangle with participant name
2. **Lifeline** (below): vertical dashed edge extending downward

Header style:
`rounded=1;whiteSpace=wrap;fillColor=#e8edf2;strokeColor=#9eafc0;fontColor=#333333;fontFamily=Microsoft YaHei;fontSize=12;fontStyle=1;`

Lifeline style (vertical dashed line, no arrows):
`endArrow=none;startArrow=none;dashed=1;strokeColor=#b3b3b3;`

#### Layout

- Participants: horizontal row at the top, spacing ≥ 200px
- Messages: horizontal arrows between lifelines, vertical spacing ≥ 40px
- Time flows **top-to-bottom**
- Activation bars: narrow rectangles (width=16) overlaid on lifelines during active processing

#### Message types

| Type              | Chinese  | Edge Style                                                                   |
|-------------------|----------|------------------------------------------------------------------------------|
| Synchronous call  | 同步调用 | `endArrow=block;endFill=1;strokeColor=#808080;` (solid line, filled arrow)   |
| Asynchronous call | 异步调用 | `endArrow=open;endFill=0;strokeColor=#808080;` (solid line, open arrow)      |
| Return message    | 返回消息 | `dashed=1;endArrow=open;endFill=0;strokeColor=#808080;` (dashed, open arrow) |
| Self-call         | 自调用   | Loop-back edge on same lifeline using waypoints                              |

#### Activation bar style
`rounded=0;fillColor=#f1f8e9;strokeColor=#82b366;fontColor=#333333;`
Width: 16px. Height varies by activity duration.

#### Medical sequence conventions

- Use system abbreviations as participant names: HIS, LIS, PACS, EMR, ESB, CDR
- Label messages with HL7/FHIR names when applicable (e.g., `ADT^A01`, `Patient/123`, `Bundle`)
- Return messages should include response status (e.g., `ACK^A01`, `200 OK`, `OperationOutcome`)