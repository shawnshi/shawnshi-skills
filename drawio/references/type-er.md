# ER Diagram Rules (实体关系图)

#### Entity (实体)

Use swimlane + text cell to create standard ER entity boxes:

```xml
<mxCell id="ent1" value="Patient" style="swimlane;fontStyle=1;startSize=26;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;fontFamily=Microsoft YaHei;fontSize=12;collapsible=0;" vertex="1" parent="1">
  <mxGeometry x="100" y="100" width="200" height="160" as="geometry"/>
</mxCell>
<mxCell id="ent1a" value="🔑 patient_id: VARCHAR(36)&#10;name: VARCHAR(100)&#10;gender: CHAR(1)&#10;birth_date: DATE&#10;🔗 org_id: VARCHAR(36)" style="text;align=left;verticalAlign=top;spacingLeft=4;spacingRight=4;overflow=hidden;whiteSpace=wrap;fillColor=#f0f8ff;strokeColor=#6c8ebf;fontColor=#333333;fontFamily=Consolas;fontSize=11;" vertex="1" parent="ent1">
  <mxGeometry y="26" width="200" height="134" as="geometry"/>
</mxCell>
```

#### Attribute markers

- 🔑 = Primary Key (PK)
- 🔗 = Foreign Key (FK)
- One attribute per line, format: `name: TYPE`, separated by `&#10;`
- Use `fontFamily=Consolas` for attribute text (monospace readability)

#### Relationship cardinality

| Cardinality  | Source Label | Target Label           |
|--------------|--------------|------------------------|
| One-to-One   | 1            | 1                      |
| One-to-Many  | 1            | N                      |
| Many-to-Many | M            | N (use junction table) |

- Identifying relationship: solid edge
- Non-identifying relationship: `dashed=1` edge
- Place cardinality labels near source/target using edge label positioning

#### Medical ER naming conventions

- Entity names: English PascalCase — Patient, Encounter, Observation, DiagnosticReport
- Attribute names: English snake_case — patient_id, birth_date, encounter_type
- FK pattern: `{referenced_entity}_id`
- Common medical entities: Patient, Encounter, Observation, DiagnosticReport, Medication, MedicationRequest, Procedure, Organization, Practitioner, Location, Condition, AllergyIntolerance