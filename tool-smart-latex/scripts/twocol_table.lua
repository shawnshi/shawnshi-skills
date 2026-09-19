--[[
twocol_table.lua — Pandoc table → tabularx blocks for two-column LaTeX layouts.

Pandoc's LaTeX writer emits tables as `longtable`, which is not supported in
two-column mode ("longtable not in 1-column mode").  This filter rewrites every
Table into a `tabularx` inside an optional `table` float so that the academic
two-column preset can typeset tables at all.

Trade-off (documented in SKILL.md): a `tabularx` block cannot break across
pages, so a table taller than one column overflows instead of continuing on the
next page.  A hard compile failure is replaced by a visible overfull warning.
]]

local function align_name(spec)
  local align = spec and (spec.alignment or spec[1])
  if type(align) == "table" then
    align = align.t or align[1]
  end
  return tostring(align or "AlignDefault")
end

local function col_spec(colspecs)
  local out = {}
  for _, spec in ipairs(colspecs) do
    local name = align_name(spec)
    if name:match("Right") then
      out[#out + 1] = ">{\\raggedleft\\arraybackslash}X"
    elseif name:match("Center") then
      out[#out + 1] = ">{\\centering\\arraybackslash}X"
    else
      out[#out + 1] = ">{\\raggedright\\arraybackslash}X"
    end
  end
  return table.concat(out)
end

local function render_blocks(blocks)
  if not blocks or #blocks == 0 then
    return ""
  end
  local tex = pandoc.write(pandoc.Pandoc(blocks), "latex")
  return (tex:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function render_row(row)
  local cells = row.cells or row
  local parts = {}
  for _, cell in ipairs(cells) do
    local content = cell.contents or cell[5] or {}
    parts[#parts + 1] = render_blocks(content)
  end
  return table.concat(parts, " & ") .. " \\\\"
end

local function render_rows(rows, out)
  for _, row in ipairs(rows or {}) do
    out[#out + 1] = render_row(row)
  end
end

-- Pandoc >= 3 wraps the header/footer in TableHead/TableFoot objects (with a
-- `rows` field), while TableBody.head/body are plain row lists.  Accept both.
local function rows_of(part)
  if part == nil then
    return {}
  end
  if part.rows ~= nil then
    return part.rows
  end
  return part
end

function Table(tbl)
  local specs = tbl.colspecs
  if not specs or #specs == 0 then
    return nil
  end

  local lines = {}
  render_rows(rows_of(tbl.head), lines)
  local head_rows = #lines

  local body = {}
  for _, part in ipairs(tbl.bodies or {}) do
    render_rows(rows_of(part.head), body)
    render_rows(rows_of(part.body), body)
  end
  render_rows(rows_of(tbl.foot), body)

  local caption = tbl.caption and tbl.caption.long
  local has_caption = caption and #caption > 0

  local tab = { "\\begin{tabularx}{\\linewidth}{" .. col_spec(specs) .. "}", "\\toprule" }
  for i = 1, head_rows do
    tab[#tab + 1] = lines[i]
  end
  if head_rows > 0 and #body > 0 then
    tab[#tab + 1] = "\\midrule"
  end
  for _, row in ipairs(body) do
    tab[#tab + 1] = row
  end
  tab[#tab + 1] = "\\bottomrule"
  tab[#tab + 1] = "\\end{tabularx}"

  local block = {}
  if has_caption then
    local short = tbl.caption.short
    local short_tex = short and #short > 0 and ("[" .. render_blocks({ pandoc.Plain(short) }) .. "]") or ""
    block[#block + 1] = "\\begin{table}[htbp]"
    block[#block + 1] = "\\centering"
    block[#block + 1] = "\\caption" .. short_tex .. "{" .. render_blocks(caption) .. "}"
  else
    block[#block + 1] = "\\begin{center}"
  end
  for _, line in ipairs(tab) do
    block[#block + 1] = line
  end
  block[#block + 1] = has_caption and "\\end{table}" or "\\end{center}"

  return pandoc.RawBlock("latex", table.concat(block, "\n") .. "\n")
end
