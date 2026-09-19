--[[
div_boxes.lua — map Pandoc fenced divs onto the templates' tcolorbox environments.

The engine passes the classes a given template can actuallytypeset:

    --lua-filter=div_boxes.lua -M boxes=definition:definitionBox,note:techNote

A div whose class is not in the mapping is restored unchanged and renders
normally, so a style that defines no boxes is unaffected.

Implementation note: Pandoc 3 applies the document-level handlers (Meta,
Pandoc) *after* walking the blocks, so `Div` cannot read `doc.meta` directly.
Divs are therefore parked in a table and resolved in one final pass, where the
metadata is available.
]]

local CANDIDATES = {
  definition = true,
  theorem = true,
  alert = true,
  note = true,
  tip = true,
  code = true,
}

local parked = {}
local MARKER = "SMARTLATEXBOX:"

local function parse_mapping(meta)
  local mapping = {}
  local raw = meta and meta.boxes and pandoc.utils.stringify(meta.boxes) or ""
  for entry in raw:gmatch("[^,]+") do
    local class, env = entry:match("^%s*([%w_%-]+)%s*:%s*([%w_%-]+)%s*$")
    if class and env then
      mapping[class] = env
    end
  end
  return mapping
end

local function box_latex(env, content)
  local body = pandoc.write(pandoc.Pandoc(content), "latex")
  body = body:gsub("^%s+", ""):gsub("%s+$", "")
  return pandoc.RawBlock(
    "latex",
    "\\begin{" .. env .. "}\n" .. body .. "\n\\end{" .. env .. "}\n"
  )
end

function Div(el)
  for _, class in ipairs(el.classes) do
    if CANDIDATES[class] then
      parked[#parked + 1] = el
      return pandoc.RawBlock("latex", MARKER .. #parked)
    end
  end
  return nil
end

function Pandoc(doc)
  if #parked == 0 then
    return doc
  end
  local mapping = parse_mapping(doc.meta)
  return doc:walk({
    RawBlock = function(block)
      local index = block.text:match("^" .. MARKER .. "(%d+)$")
      if not index then
        return nil
      end
      local div = parked[tonumber(index)]
      if not div then
        return nil
      end
      for _, class in ipairs(div.classes) do
        local env = mapping[class]
        if env then
          return box_latex(env, div.content)
        end
      end
      return div
    end,
  })
end
